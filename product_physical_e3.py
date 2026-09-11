#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any

LAB_REPO = "iamaman11/mobile-proxy-mish-lab"
PRODUCT_REPO = "iamaman11/mobile-proxy-mish"
TASK_SCHEMA = "mish.lab-task/v1"
RESULT_SCHEMA = "mish.lab-result/v1"
CANDIDATE_SCHEMA = "mish.product-physical-candidate/v1"
EXECUTION = "product_physical_e3"
PRODUCT_PACKAGE = "com.mobileproxymish.app"
TEST_PACKAGE = "com.mobileproxymish.app.test"
RUNNER = "androidx.test.runner.AndroidJUnitRunner"
TEST_CLASS = "com.mobileproxymish.app.cellular.CellularE3InstrumentedTest"
EXPECTED_MODEL = "SM-A022G"
EXPECTED_API = "30"
EXPECTED_ABI = "armeabi-v7a"


def run(
    cmd: list[str],
    *,
    capture: bool = True,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=check,
        timeout=timeout,
    )


def lab_root() -> Path:
    configured = os.environ.get("MISH_LAB_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        return Path(r"C:\mish-lab")
    return Path(tempfile.gettempdir()) / "mish-lab"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_adb() -> str | None:
    configured = os.environ.get("MISH_LAB_ADB")
    if configured and Path(configured).is_file():
        return configured
    managed = Path(r"C:\mish-lab\tools\android-sdk\platform-tools\adb.exe")
    if managed.is_file():
        return str(managed)
    return shutil.which("adb")


def find_gh() -> str:
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("GitHub CLI 'gh' is required")
    return gh


def gh_json(args: list[str]) -> Any:
    reply = run([find_gh(), *args])
    try:
        return json.loads(reply.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GitHub CLI returned invalid JSON: {exc}") from exc


def load_state_and_task() -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root = lab_root()
    state_path = root / "current.json"
    if not state_path.is_file():
        raise RuntimeError("no active LAB task; run mish-lab next first")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    workspace = Path(str(state.get("workspace") or ""))
    task_path = workspace / "task.json"
    if not task_path.is_file():
        raise RuntimeError("active LAB task.json is missing")
    task = json.loads(task_path.read_text(encoding="utf-8"))
    return root, state, task


def validate_task(state: dict[str, Any], task: dict[str, Any]) -> tuple[str, str]:
    if task.get("schema") != TASK_SCHEMA:
        raise RuntimeError("unsupported task schema")
    if task.get("operation") != "research.manual" or task.get("execution") != EXECUTION:
        raise RuntimeError("current task is not a product_physical_e3 execution")
    if state.get("execution") != EXECUTION:
        raise RuntimeError("current LAB state execution mismatch")
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or re.fullmatch(r"LAB-[0-9]{4}", task_id) is None:
        raise RuntimeError("invalid task_id")
    if state.get("task_id") != task_id:
        raise RuntimeError("task/current identity mismatch")
    product = task.get("product")
    if not isinstance(product, dict) or product.get("repo") != PRODUCT_REPO:
        raise RuntimeError(f"task product.repo must be {PRODUCT_REPO}")
    source_sha = product.get("source_sha")
    if not isinstance(source_sha, str) or re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise RuntimeError("task product.source_sha must be an exact lowercase commit SHA")
    if state.get("product_source_sha") != source_sha:
        raise RuntimeError("task/current PRODUCT source identity mismatch")
    return task_id, source_sha


def artifact_name(task_id: str, source_sha: str) -> str:
    return f"mish-product-e3-{task_id}-{source_sha}"


def verify_candidate(directory: Path, task_id: str, source_sha: str) -> tuple[Path, Path, dict[str, Any]]:
    manifest_path = directory / "candidate.json"
    product_apk = directory / "app-debug.apk"
    test_apk = directory / "app-debug-androidTest.apk"
    if not manifest_path.is_file() or not product_apk.is_file() or not test_apk.is_file():
        raise RuntimeError("physical candidate artifact is incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "schema": CANDIDATE_SCHEMA,
        "task_id": task_id,
        "source_repo": PRODUCT_REPO,
        "source_sha": source_sha,
        "product_package": PRODUCT_PACKAGE,
        "test_package": TEST_PACKAGE,
        "runner": RUNNER,
        "test_class": TEST_CLASS,
        "abi": EXPECTED_ABI,
        "build_type": "debug",
        "scope": "PHYSICAL_TEST_CANDIDATE_NOT_RELEASE",
        "product_apk": "app-debug.apk",
        "test_apk": "app-debug-androidTest.apk",
    }
    for key, expected in required.items():
        if manifest.get(key) != expected:
            raise RuntimeError(f"candidate manifest mismatch for {key}: expected {expected!r}, got {manifest.get(key)!r}")
    product_digest = sha256(product_apk)
    test_digest = sha256(test_apk)
    if product_digest != manifest.get("product_apk_sha256"):
        raise RuntimeError("PRODUCT APK digest mismatch")
    if test_digest != manifest.get("test_apk_sha256"):
        raise RuntimeError("androidTest APK digest mismatch")
    certificate = manifest.get("signing_certificate_sha256")
    if not isinstance(certificate, str) or re.fullmatch(r"[0-9a-f]{64}", certificate) is None:
        raise RuntimeError("candidate signing certificate digest is invalid")
    return product_apk, test_apk, manifest


def download_candidate(root: Path, task_id: str, source_sha: str) -> tuple[Path, Path, dict[str, Any]]:
    destination = root / "cache" / "product-e3" / source_sha / task_id
    if destination.is_dir():
        try:
            return verify_candidate(destination, task_id, source_sha)
        except Exception:
            shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    name = artifact_name(task_id, source_sha)
    query_name = urllib.parse.quote(name, safe="")
    payload = gh_json([
        "api",
        f"repos/{LAB_REPO}/actions/artifacts?name={query_name}&per_page=100",
    ])
    artifacts = [
        item for item in payload.get("artifacts", [])
        if item.get("name") == name and not item.get("expired", False)
    ]
    artifacts.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    if not artifacts:
        raise RuntimeError(f"no ready hosted physical candidate artifact named {name}; wait for Product Physical Candidate workflow")
    workflow_run = artifacts[0].get("workflow_run") or {}
    run_id = workflow_run.get("id")
    if not run_id:
        raise RuntimeError("candidate artifact does not identify its workflow run")
    run([
        find_gh(), "run", "download", str(run_id),
        "--repo", LAB_REPO,
        "--name", name,
        "--dir", str(destination),
    ], capture=False)
    return verify_candidate(destination, task_id, source_sha)


def attached_device(adb: str) -> None:
    lines = run([adb, "devices"]).stdout.splitlines()[1:]
    devices = [line for line in lines if "\tdevice" in line]
    if len(devices) != 1:
        raise RuntimeError(f"expected exactly one authorized ADB device, found {len(devices)}")


def adb_text(adb: str, *args: str) -> str:
    reply = run([adb, *args])
    return reply.stdout.strip()


def verify_device(adb: str) -> dict[str, str]:
    attached_device(adb)
    model = adb_text(adb, "shell", "getprop", "ro.product.model")
    api = adb_text(adb, "shell", "getprop", "ro.build.version.sdk")
    abi = adb_text(adb, "shell", "getprop", "ro.product.cpu.abi")
    if model != EXPECTED_MODEL:
        raise RuntimeError(f"DEVICE-1 model mismatch: expected {EXPECTED_MODEL}, got {model}")
    if api != EXPECTED_API:
        raise RuntimeError(f"DEVICE-1 API mismatch: expected {EXPECTED_API}, got {api}")
    if abi != EXPECTED_ABI:
        raise RuntimeError(f"DEVICE-1 ABI mismatch: expected {EXPECTED_ABI}, got {abi}")
    return {"model": model, "api": api, "abi": abi}


def install_apk(adb: str, apk: Path, label: str) -> None:
    reply = run([adb, "install", "-r", str(apk)], check=False)
    combined = (reply.stdout or "") + "\n" + (reply.stderr or "")
    if reply.returncode == 0 and "Success" in combined:
        return
    if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in combined:
        raise RuntimeError(
            f"ACTION_REQUIRED=REMOVE_CONFLICTING_{label}_SIGNATURE; automatic uninstall is forbidden"
        )
    raise RuntimeError(f"{label} APK install failed with adb exit {reply.returncode}")


def parse_kv_tail(line: str, marker: str) -> dict[str, str]:
    tail = line.split(marker, 1)[1].strip()
    fields: dict[str, str] = {}
    for token in tail.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if re.fullmatch(r"[A-Za-z0-9_]+", key):
            fields[key] = value
    return fields


def run_physical_e3(
    adb: str,
    product_apk: Path,
    test_apk: Path,
    grant_wait_seconds: int,
) -> tuple[dict[str, Any], str]:
    install_apk(adb, product_apk, "PRODUCT")
    install_apk(adb, test_apk, "TEST")

    run([adb, "shell", "am", "force-stop", PRODUCT_PACKAGE], check=False)
    launch = run([
        adb, "shell", "am", "start", "-W", "-n", f"{PRODUCT_PACKAGE}/.MainActivity"
    ], check=False)
    if launch.returncode != 0:
        raise RuntimeError("PRODUCT launcher activity failed to start")

    if grant_wait_seconds > 0:
        print(f"MISH_LAB_MAGISK_GRANT_WINDOW_SECONDS={grant_wait_seconds}")
        print(f"MISH_LAB_MAGISK_PACKAGE={PRODUCT_PACKAGE}")
        time.sleep(grant_wait_seconds)

    command = [
        adb, "shell", "am", "instrument", "-w", "-r",
        "-e", "class", TEST_CLASS,
        "-e", "e3Mode", "lifecycle",
        "-e", "e3Host", "checkip.amazonaws.com",
        "-e", "e3Port", "443",
        "-e", "e3Path", "/",
        f"{TEST_PACKAGE}/{RUNNER}",
    ]
    reply = run(command, check=False, timeout=900)
    raw = (reply.stdout or "") + (("\n" + reply.stderr) if reply.stderr else "")

    evidence: list[dict[str, str]] = []
    safe_failures: list[dict[str, str]] = []
    for line in raw.splitlines():
        if "E3_EVIDENCE " in line:
            evidence.append(parse_kv_tail(line, "E3_EVIDENCE "))
        if "E3_SAFE_FAILURE " in line:
            safe_failures.append(parse_kv_tail(line, "E3_SAFE_FAILURE "))

    phases = {item.get("phase") for item in evidence}
    runner_ok = "OK (1 test)" in raw and "FAILURES!!!" not in raw and "INSTRUMENTATION_FAILED" not in raw
    required_phases = {"positive", "negative", "recovery"}
    outcome = "PASS" if reply.returncode == 0 and runner_ok and required_phases.issubset(phases) else "FAIL"

    summary = {
        "outcome": outcome,
        "instrumentation_exit_code": reply.returncode,
        "runner_ok": runner_ok,
        "evidence": evidence,
        "safe_failures": safe_failures,
        "required_phases_present": required_phases.issubset(phases),
    }
    return summary, raw


def execute() -> int:
    root, state, task = load_state_and_task()
    task_id, source_sha = validate_task(state, task)
    product_apk, test_apk, manifest = download_candidate(root, task_id, source_sha)
    adb = find_adb()
    if not adb:
        raise RuntimeError("ADB is unavailable; run mish-lab doctor")
    device = verify_device(adb)

    raw_wait = task.get("grant_wait_seconds", 20)
    if not isinstance(raw_wait, int) or raw_wait < 0 or raw_wait > 120:
        raise RuntimeError("grant_wait_seconds must be an integer in 0..120")

    e3, raw = run_physical_e3(adb, product_apk, test_apk, raw_wait)
    workspace = Path(str(state["workspace"]))
    (workspace / "instrumentation.txt").write_text(raw, encoding="utf-8")

    result = {
        "schema": RESULT_SCHEMA,
        "task_id": task_id,
        "status": "CONCLUSIVE",
        "operation": state["operation"],
        "execution": EXECUTION,
        "outcome": e3["outcome"],
        "observations": {
            "device": device,
            "candidate": {
                "source_repo": manifest["source_repo"],
                "source_sha": manifest["source_sha"],
                "lab_sha": manifest["lab_sha"],
                "build_run_id": manifest["build_run_id"],
                "product_apk_sha256": manifest["product_apk_sha256"],
                "test_apk_sha256": manifest["test_apk_sha256"],
                "signing_certificate_sha256": manifest["signing_certificate_sha256"],
                "scope": manifest["scope"],
            },
            "e3": e3,
        },
        "product_source_sha": source_sha,
        "product_apk_sha256": manifest["product_apk_sha256"],
        "test_apk_sha256": manifest["test_apk_sha256"],
        "product_changed": False,
    }
    result_path = workspace / "result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("MISH_PRODUCT_PHYSICAL_E3=COMPLETE")
    print(f"TASK_ID={task_id}")
    print(f"SOURCE_SHA={source_sha}")
    print(f"PRODUCT_APK_SHA256={manifest['product_apk_sha256']}")
    print(f"TEST_APK_SHA256={manifest['test_apk_sha256']}")
    print(f"E3_OUTCOME={e3['outcome']}")
    print("RAW_INSTRUMENTATION=LOCAL_ONLY")
    return 0


def selftest() -> int:
    task_id = "LAB-0001"
    sha = "a" * 40
    expected = f"mish-product-e3-{task_id}-{sha}"
    if artifact_name(task_id, sha) != expected:
        raise AssertionError("artifact naming contract failed")
    evidence = parse_kv_tail(
        "prefix E3_EVIDENCE phase=negative owner_not_admitted=true dns_blocked=true",
        "E3_EVIDENCE ",
    )
    if evidence != {"phase": "negative", "owner_not_admitted": "true", "dns_blocked": "true"}:
        raise AssertionError("evidence parser contract failed")
    print("MISH_PRODUCT_PHYSICAL_E3_SELFTEST=PASS")
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "execute"
    try:
        if command == "execute":
            return execute()
        if command == "selftest":
            return selftest()
        raise RuntimeError(f"unsupported command: {command}")
    except subprocess.TimeoutExpired:
        print("MISH_PRODUCT_PHYSICAL_E3_ERROR=instrumentation timeout", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"MISH_PRODUCT_PHYSICAL_E3_ERROR={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

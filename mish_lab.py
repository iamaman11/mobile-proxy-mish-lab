#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

LAB_REPO = "iamaman11/mobile-proxy-mish-lab"
TASK_SCHEMA = "mish.lab-task/v1"
RESULT_SCHEMA = "mish.lab-result/v1"
BUILTIN_OPERATION = "android.device_facts_probe"
LAB_PACKAGE = "com.mobileproxymish.lab.devicefacts"
LAB_ACTIVITY = f"{LAB_PACKAGE}/.MainActivity"


def run(cmd: list[str], *, cwd: Path | None = None, capture: bool = True, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=check,
    )


def which_first(names: list[str], extra_globs: list[str] | None = None) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    for pattern in extra_globs or []:
        for candidate in sorted(Path().glob(pattern)):
            if candidate.is_file():
                return str(candidate)
    return None


def lab_root() -> Path:
    configured = os.environ.get("MISH_LAB_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    if os.name == "nt":
        return Path(r"C:\mish-lab")
    return Path(tempfile.gettempdir()) / "mish-lab"


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def ensure_layout() -> Path:
    root = lab_root()
    for child in ("work", "cache", "results", "locks"):
        (root / child).mkdir(parents=True, exist_ok=True)
    return root


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_adb() -> str | None:
    env = os.environ.get("MISH_LAB_ADB")
    if env and Path(env).is_file():
        return env
    common = Path(r"C:\mish-lab\tools\android-sdk\platform-tools\adb.exe")
    if common.is_file():
        return str(common)
    return shutil.which("adb")


def find_gradle() -> str | None:
    env = os.environ.get("MISH_LAB_GRADLE")
    if env and Path(env).is_file():
        return env
    found = shutil.which("gradle")
    if found:
        return found
    if os.name == "nt":
        tools = Path(r"C:\mish-lab\tools")
        if tools.is_dir():
            candidates = sorted(tools.glob("gradle*/bin/gradle.bat"), reverse=True)
            if candidates:
                return str(candidates[0])
    return None


def parse_task_body(body: str) -> dict[str, Any]:
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", body or "", flags=re.DOTALL | re.IGNORECASE)
    errors: list[str] = []
    for block in blocks:
        try:
            value = json.loads(block)
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
            continue
        if isinstance(value, dict) and value.get("schema") == TASK_SCHEMA:
            return value
    if errors:
        raise ValueError(f"no valid {TASK_SCHEMA} JSON block; parse errors: {errors[0]}")
    raise ValueError(f"issue body does not contain a {TASK_SCHEMA} JSON block")


def validate_task(task: dict[str, Any]) -> None:
    if task.get("schema") != TASK_SCHEMA:
        raise ValueError("unsupported task schema")
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not re.fullmatch(r"LAB-[0-9]{4}", task_id):
        raise ValueError("task_id must match LAB-NNNN")
    operation = task.get("operation")
    if operation not in {BUILTIN_OPERATION, "research.manual"}:
        raise ValueError(f"unsupported operation: {operation}")
    product = task.get("product")
    if product is not None:
        if not isinstance(product, dict):
            raise ValueError("product must be an object")
        source_sha = product.get("source_sha")
        if source_sha is not None and not re.fullmatch(r"[0-9a-f]{40}", str(source_sha)):
            raise ValueError("product.source_sha must be a 40-char lowercase Git SHA")
        apk_sha = product.get("apk_sha256")
        if apk_sha is not None and not re.fullmatch(r"[0-9a-f]{64}", str(apk_sha)):
            raise ValueError("product.apk_sha256 must be a lowercase SHA-256")


def gh_json(args: list[str]) -> Any:
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("GitHub CLI 'gh' is required for GitHub task transport")
    reply = run([gh, *args])
    try:
        return json.loads(reply.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GitHub CLI returned invalid JSON: {exc}") from exc


def resolve_issue(issue_arg: str) -> dict[str, Any]:
    if issue_arg == "next":
        issues = gh_json([
            "issue", "list", "--repo", LAB_REPO, "--state", "open",
            "--limit", "100", "--json", "number,title,body,author",
        ])
        matching = [item for item in issues if str(item.get("title", "")).startswith("[LAB TASK")]
        if not matching:
            raise RuntimeError("no open LAB TASK issue found")
        issue_number = min(int(item["number"]) for item in matching)
    else:
        issue_number = int(issue_arg)
    return gh_json([
        "issue", "view", str(issue_number), "--repo", LAB_REPO,
        "--json", "number,title,body,state,author,url",
    ])


def acquire_lock(root: Path, task_id: str) -> None:
    lock = root / "locks" / "DEVICE-1.lock"
    if lock.exists():
        existing = lock.read_text(encoding="utf-8").strip()
        if existing != task_id:
            raise RuntimeError(f"DEVICE-1 is already locked by {existing or 'UNKNOWN'}")
    lock.write_text(task_id + "\n", encoding="utf-8")


def release_lock(root: Path, task_id: str) -> None:
    lock = root / "locks" / "DEVICE-1.lock"
    if lock.exists() and lock.read_text(encoding="utf-8").strip() == task_id:
        lock.unlink()


def write_current(root: Path, state: dict[str, Any]) -> None:
    (root / "current.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def read_current(root: Path) -> dict[str, Any]:
    path = root / "current.json"
    if not path.is_file():
        raise RuntimeError("no active LAB task; run 'mish-lab work <issue>' first")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("current LAB state is invalid")
    return value


def ensure_product_source(task: dict[str, Any], workspace: Path) -> str | None:
    product = task.get("product") or {}
    repo = product.get("repo")
    source_sha = product.get("source_sha")
    if not repo or not source_sha:
        return None
    target = workspace / "product"
    if target.exists():
        shutil.rmtree(target)
    clone_url = f"https://github.com/{repo}.git"
    run(["git", "clone", "--filter=blob:none", "--no-checkout", clone_url, str(target)], capture=True)
    run(["git", "-C", str(target), "fetch", "--depth", "1", "origin", source_sha], capture=True)
    run(["git", "-C", str(target), "checkout", "--detach", source_sha], capture=True)
    actual = run(["git", "-C", str(target), "rev-parse", "HEAD"]).stdout.strip()
    if actual != source_sha:
        raise RuntimeError("product checkout identity mismatch")
    return actual


def ensure_product_apk(task: dict[str, Any], workspace: Path) -> str | None:
    product = task.get("product") or {}
    repo = product.get("repo")
    tag = product.get("release_tag")
    name = product.get("apk_name")
    expected = product.get("apk_sha256")
    if not all((repo, tag, name, expected)):
        return None
    destination = workspace / "inputs"
    destination.mkdir(exist_ok=True)
    apk = destination / str(name)
    if not apk.exists():
        gh = shutil.which("gh")
        if not gh:
            raise RuntimeError("gh is required to download release assets")
        run([gh, "release", "download", str(tag), "--repo", str(repo), "--pattern", str(name), "--dir", str(destination)])
    actual = sha256(apk)
    if actual != expected:
        raise RuntimeError(f"product APK digest mismatch: expected {expected}, got {actual}")
    return actual


def prepare_builtin_probe(workspace: Path) -> Path:
    source = repo_root() / "templates" / "android-device-facts"
    if not source.is_dir():
        raise RuntimeError("built-in Android probe template is missing")
    target = workspace / "probe"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def command_doctor(_: argparse.Namespace) -> int:
    root = ensure_layout()
    checks: dict[str, str] = {}
    checks["PYTHON"] = "PASS"
    checks["GIT"] = "PASS" if shutil.which("git") else "FAIL"
    checks["GH"] = "PASS" if shutil.which("gh") else "FAIL"
    checks["JAVA"] = "PASS" if shutil.which("java") else "FAIL"
    checks["GRADLE"] = "PASS" if find_gradle() else "FAIL"
    adb = find_adb()
    checks["ADB"] = "PASS" if adb else "FAIL"
    device_count = 0
    if adb:
        try:
            output = run([adb, "devices"]).stdout.splitlines()[1:]
            device_count = sum(1 for line in output if "\tdevice" in line)
        except Exception:
            checks["ADB"] = "FAIL"
    checks["DEVICE"] = "PASS" if device_count == 1 else "FAIL"
    overall = "PASS" if all(value == "PASS" for value in checks.values()) else "FAIL"
    print(f"MISH_LAB_DOCTOR={overall}")
    for key, value in checks.items():
        print(f"{key}={value}")
    print(f"LAB_ROOT={root}")
    print(f"READY_FOR_ANDROID_RESEARCH={'YES' if overall == 'PASS' else 'NO'}")
    return 0 if overall == "PASS" else 2


def command_work(args: argparse.Namespace) -> int:
    root = ensure_layout()
    issue = resolve_issue(args.issue)
    task = parse_task_body(str(issue.get("body") or ""))
    validate_task(task)
    task_id = str(task["task_id"])
    acquire_lock(root, task_id)
    workspace = root / "work" / task_id
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "task.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    product_source = ensure_product_source(task, workspace)
    product_apk = ensure_product_apk(task, workspace)
    if task["operation"] == BUILTIN_OPERATION:
        prepare_builtin_probe(workspace)
    state = {
        "task_id": task_id,
        "issue_number": int(issue["number"]),
        "issue_url": issue.get("url"),
        "operation": task["operation"],
        "workspace": str(workspace),
        "product_source_sha": product_source,
        "product_apk_sha256": product_apk,
    }
    write_current(root, state)
    print("MISH_LAB_WORK=READY")
    print(f"TASK_ID={task_id}")
    print(f"OPERATION={task['operation']}")
    print(f"WORKSPACE={workspace}")
    print(f"PRODUCT_SOURCE={'VERIFIED' if product_source else 'NOT_REQUIRED'}")
    print(f"PRODUCT_APK={'VERIFIED' if product_apk else 'NOT_REQUIRED'}")
    return 0


def build_probe_from_state(root: Path, state: dict[str, Any]) -> Path:
    if state.get("operation") != BUILTIN_OPERATION:
        raise RuntimeError("active task does not use the built-in Android probe")
    gradle = find_gradle()
    if not gradle:
        raise RuntimeError("Gradle is not available; run doctor")
    workspace = Path(str(state["workspace"]))
    probe = workspace / "probe"
    run([gradle, "--no-daemon", "-p", str(probe), ":app:assembleDebug"], capture=False)
    apk = probe / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if not apk.is_file():
        raise RuntimeError("Android probe build completed without expected APK")
    state["probe_apk"] = str(apk)
    state["probe_apk_sha256"] = sha256(apk)
    write_current(root, state)
    print("MISH_LAB_PROBE_BUILD=PASS")
    print(f"APK_SHA256={state['probe_apk_sha256']}")
    return apk


def command_probe_build(_: argparse.Namespace) -> int:
    root = ensure_layout()
    state = read_current(root)
    build_probe_from_state(root, state)
    return 0


def command_probe_run(_: argparse.Namespace) -> int:
    root = ensure_layout()
    state = read_current(root)
    apk_value = state.get("probe_apk")
    apk = Path(str(apk_value)) if apk_value else build_probe_from_state(root, state)
    if not apk.is_file():
        raise RuntimeError("probe APK is missing")
    adb = find_adb()
    if not adb:
        raise RuntimeError("ADB is not available; run doctor")
    devices = [line for line in run([adb, "devices"]).stdout.splitlines()[1:] if "\tdevice" in line]
    if len(devices) != 1:
        raise RuntimeError(f"expected exactly one ADB device, found {len(devices)}")
    run([adb, "install", "-r", str(apk)], capture=False)
    run([adb, "shell", "am", "force-stop", LAB_PACKAGE])
    run([adb, "shell", "am", "start", "-W", "-n", LAB_ACTIVITY])
    raw = run([adb, "shell", "run-as", LAB_PACKAGE, "cat", "files/result.json"]).stdout.strip()
    try:
        observed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"probe returned invalid JSON: {exc}") from exc
    required = {"status", "sdk", "abi", "wifi_present", "wifi_validated", "cellular_present", "cellular_validated", "vpn_present"}
    if not isinstance(observed, dict) or not required.issubset(observed):
        raise RuntimeError("probe result is missing required fields")
    result = {
        "schema": RESULT_SCHEMA,
        "task_id": state["task_id"],
        "status": "CONCLUSIVE" if observed.get("status") == "PASS" else "PARTIAL",
        "operation": state["operation"],
        "observations": observed,
        "product_source_sha": state.get("product_source_sha"),
        "product_apk_sha256": state.get("product_apk_sha256"),
    }
    result_path = Path(str(state["workspace"])) / "result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    state["result_file"] = str(result_path)
    write_current(root, state)
    print("MISH_LAB_PROBE_RUN=PASS")
    print(f"RESULT_FILE={result_path}")
    for key in ("sdk", "abi", "wifi_present", "wifi_validated", "cellular_present", "cellular_validated", "vpn_present"):
        print(f"{key.upper()}={observed[key]}")
    return 0


def command_status(_: argparse.Namespace) -> int:
    root = ensure_layout()
    state = read_current(root)
    print("MISH_LAB_STATUS=ACTIVE")
    for key in ("task_id", "operation", "workspace", "product_source_sha", "product_apk_sha256", "probe_apk_sha256", "result_file"):
        value = state.get(key)
        if value is not None:
            print(f"{key.upper()}={value}")
    return 0


def validate_result(value: Any, task_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("result must be a JSON object")
    if value.get("schema") != RESULT_SCHEMA:
        raise ValueError("unsupported result schema")
    if value.get("task_id") != task_id:
        raise ValueError("result task_id does not match active task")
    if value.get("status") not in {"CONCLUSIVE", "PARTIAL", "BLOCKED"}:
        raise ValueError("result status must be CONCLUSIVE, PARTIAL, or BLOCKED")
    return value


def result_markdown(result: dict[str, Any]) -> str:
    payload = json.dumps(result, indent=2, sort_keys=True)
    return f"## MISH Lab result\n\n```json\n{payload}\n```\n"


def command_submit(_: argparse.Namespace) -> int:
    root = ensure_layout()
    state = read_current(root)
    result_path_value = state.get("result_file")
    result_path = Path(str(result_path_value)) if result_path_value else Path(str(state["workspace"])) / "result.json"
    if not result_path.is_file():
        raise RuntimeError(f"result file is missing: {result_path}")
    result = validate_result(json.loads(result_path.read_text(encoding="utf-8")), str(state["task_id"]))
    report = Path(str(state["workspace"])) / "result-comment.md"
    report.write_text(result_markdown(result), encoding="utf-8")
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("gh is required to submit results")
    run([
        gh, "issue", "comment", str(state["issue_number"]), "--repo", LAB_REPO,
        "--body-file", str(report),
    ], capture=False)
    release_lock(root, str(state["task_id"]))
    print("MISH_LAB_SUBMIT=PASS")
    print(f"TASK_ID={state['task_id']}")
    print(f"RESULT_STATUS={result['status']}")
    return 0


def command_selftest(_: argparse.Namespace) -> int:
    sample = """# Task\n```json\n{\"schema\":\"mish.lab-task/v1\",\"task_id\":\"LAB-0001\",\"operation\":\"android.device_facts_probe\"}\n```\n"""
    task = parse_task_body(sample)
    validate_task(task)
    assert task["task_id"] == "LAB-0001"
    result = {"schema": RESULT_SCHEMA, "task_id": "LAB-0001", "status": "CONCLUSIVE", "observations": {}}
    validate_result(result, "LAB-0001")
    with tempfile.TemporaryDirectory() as temporary:
        os.environ["MISH_LAB_ROOT"] = temporary
        root = ensure_layout()
        acquire_lock(root, "LAB-0001")
        assert (root / "locks" / "DEVICE-1.lock").read_text(encoding="utf-8").strip() == "LAB-0001"
        release_lock(root, "LAB-0001")
        assert not (root / "locks" / "DEVICE-1.lock").exists()
    print("MISH_LAB_SELFTEST=PASS")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="mish-lab")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor").set_defaults(func=command_doctor)
    work = commands.add_parser("work")
    work.add_argument("issue", help="LAB task issue number or 'next'")
    work.set_defaults(func=command_work)
    probe = commands.add_parser("probe")
    probe_sub = probe.add_subparsers(dest="probe_command", required=True)
    probe_sub.add_parser("build").set_defaults(func=command_probe_build)
    probe_sub.add_parser("run").set_defaults(func=command_probe_run)
    commands.add_parser("status").set_defaults(func=command_status)
    commands.add_parser("submit").set_defaults(func=command_submit)
    commands.add_parser("selftest").set_defaults(func=command_selftest)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"MISH_LAB_ERROR={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

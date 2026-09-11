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
import time
from pathlib import Path
from typing import Any

LAB_REPO = "iamaman11/mobile-proxy-mish-lab"
TASK_SCHEMA = "mish.lab-task/v1"
RESULT_SCHEMA = "mish.lab-result/v1"
READY_ARTIFACT = "mish-lab-ready-probe"
READY_OPERATION = "android.device_facts_probe"
LAB_PACKAGE = "com.mobileproxymish.lab.devicefacts"
LAB_ACTIVITY = f"{LAB_PACKAGE}/.MainActivity"
SANDBOX_PACKAGE = "com.mobileproxymish.lab.product"
SANDBOX_ACTIVITY = f"{SANDBOX_PACKAGE}/com.mobileproxymish.app.MainActivity"


def run(cmd: list[str], *, cwd: Path | None = None, capture: bool = True, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=check,
    )


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
    configured = os.environ.get("MISH_LAB_ADB")
    if configured and Path(configured).is_file():
        return configured
    common = Path(r"C:\mish-lab\tools\android-sdk\platform-tools\adb.exe")
    if common.is_file():
        return str(common)
    return shutil.which("adb")


def find_gradle() -> str | None:
    configured = os.environ.get("MISH_LAB_GRADLE")
    if configured and Path(configured).is_file():
        return configured
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


def gh_json(args: list[str]) -> Any:
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("GitHub CLI 'gh' is required")
    reply = run([gh, *args])
    try:
        return json.loads(reply.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GitHub CLI returned invalid JSON: {exc}") from exc


def parse_task_body(body: str) -> dict[str, Any]:
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", body or "", flags=re.DOTALL | re.IGNORECASE)
    for block in blocks:
        try:
            value = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("schema") == TASK_SCHEMA:
            return value
    raise ValueError(f"Issue does not contain a {TASK_SCHEMA} JSON block")


def validate_task(task: dict[str, Any]) -> None:
    if task.get("schema") != TASK_SCHEMA:
        raise ValueError("unsupported task schema")
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not re.fullmatch(r"LAB-[0-9]{4}", task_id):
        raise ValueError("task_id must match LAB-NNNN")
    operation = task.get("operation")
    if operation not in {READY_OPERATION, "product.sandbox", "research.manual"}:
        raise ValueError(f"unsupported operation: {operation}")
    product = task.get("product")
    if product is not None:
        if not isinstance(product, dict):
            raise ValueError("product must be an object")
        source_sha = product.get("source_sha")
        if source_sha is not None and not re.fullmatch(r"[0-9a-f]{40}", str(source_sha)):
            raise ValueError("product.source_sha must be a lowercase 40-char SHA")
        apk_sha = product.get("apk_sha256")
        if apk_sha is not None and not re.fullmatch(r"[0-9a-f]{64}", str(apk_sha)):
            raise ValueError("product.apk_sha256 must be a lowercase SHA-256")


def resolve_issue(issue_arg: str) -> dict[str, Any]:
    if issue_arg == "next":
        issues = gh_json([
            "issue", "list", "--repo", LAB_REPO, "--state", "open", "--limit", "100",
            "--json", "number,title,body,author",
        ])
        matches = [item for item in issues if str(item.get("title", "")).startswith("[LAB TASK")]
        if not matches:
            raise RuntimeError("no open LAB TASK issue found")
        issue_number = min(int(item["number"]) for item in matches)
    else:
        issue_number = int(issue_arg)
    return gh_json([
        "issue", "view", str(issue_number), "--repo", LAB_REPO,
        "--json", "number,title,body,state,author,url",
    ])


def execution_kind(task: dict[str, Any]) -> str:
    explicit = task.get("execution")
    if explicit:
        return str(explicit)
    if task.get("operation") == READY_OPERATION:
        return "ready_probe"
    if task.get("operation") == "product.sandbox":
        return "product_sandbox"
    return "manual"


def acquire_lock(root: Path, task_id: str) -> None:
    lock = root / "locks" / "DEVICE-1.lock"
    if lock.exists():
        existing = lock.read_text(encoding="utf-8").strip()
        if existing != task_id:
            raise RuntimeError(f"DEVICE-1 already locked by {existing or 'UNKNOWN'}")
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
        raise RuntimeError("no active LAB task; run 'mish-lab next' or 'mish-lab work <issue>'")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("current LAB state is invalid")
    return value


def current_lab_sha() -> str:
    result = run(["git", "-C", str(repo_root()), "rev-parse", "HEAD"])
    return result.stdout.strip()


def ensure_product_apk(task: dict[str, Any], root: Path) -> tuple[str | None, str | None]:
    product = task.get("product") or {}
    repo = product.get("repo")
    tag = product.get("release_tag")
    name = product.get("apk_name")
    expected = product.get("apk_sha256")
    if not all((repo, tag, name, expected)):
        return None, None
    destination = root / "cache" / "product" / str(tag)
    destination.mkdir(parents=True, exist_ok=True)
    apk = destination / str(name)
    if not apk.exists():
        gh = shutil.which("gh")
        if not gh:
            raise RuntimeError("gh is required to download product release assets")
        run([gh, "release", "download", str(tag), "--repo", str(repo), "--pattern", str(name), "--dir", str(destination)])
    actual = sha256(apk)
    if actual != expected:
        raise RuntimeError(f"product APK digest mismatch: expected {expected}, got {actual}")
    return str(apk), actual


def clone_exact_product(task: dict[str, Any], destination: Path) -> str:
    product = task.get("product") or {}
    repo = product.get("repo")
    source_sha = product.get("source_sha")
    if not repo or not source_sha:
        raise RuntimeError("product repo/source_sha are required for Product Sandbox")
    if destination.exists():
        shutil.rmtree(destination)
    run(["git", "clone", "--filter=blob:none", "--no-checkout", f"https://github.com/{repo}.git", str(destination)])
    run(["git", "-C", str(destination), "fetch", "--depth", "1", "origin", str(source_sha)])
    run(["git", "-C", str(destination), "checkout", "--detach", str(source_sha)])
    actual = run(["git", "-C", str(destination), "rev-parse", "HEAD"]).stdout.strip()
    if actual != source_sha:
        raise RuntimeError("product checkout identity mismatch")
    return actual


def download_ready_probe(root: Path) -> tuple[Path, dict[str, Any]]:
    lab_sha = current_lab_sha()
    destination = root / "cache" / "ready-probe" / lab_sha
    manifest_path = destination / "probe.json"
    apk_path = destination / "mish-lab-device-facts.apk"
    if manifest_path.is_file() and apk_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("lab_sha") == lab_sha and sha256(apk_path) == manifest.get("sha256"):
            return apk_path, manifest
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    runs = gh_json([
        "run", "list", "--repo", LAB_REPO, "--workflow", "ci.yml", "--branch", "main",
        "--status", "success", "--limit", "50", "--json", "databaseId,headSha,conclusion",
    ])
    matching = next((item for item in runs if item.get("headSha") == lab_sha), None)
    if not matching:
        raise RuntimeError(f"no successful ready-probe build for LAB commit {lab_sha}; run/pull latest main after CI is green")
    gh = shutil.which("gh")
    assert gh
    run([
        gh, "run", "download", str(matching["databaseId"]), "--repo", LAB_REPO,
        "--name", READY_ARTIFACT, "--dir", str(destination),
    ])
    if not manifest_path.is_file() or not apk_path.is_file():
        raise RuntimeError("ready-probe artifact is incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("lab_sha") != lab_sha:
        raise RuntimeError("ready-probe LAB SHA mismatch")
    actual = sha256(apk_path)
    if actual != manifest.get("sha256"):
        raise RuntimeError("ready-probe APK digest mismatch")
    return apk_path, manifest


def prepare_local_probe(workspace: Path) -> Path:
    source = repo_root() / "templates" / "android-device-facts"
    target = workspace / "probe"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def build_local_probe(root: Path, state: dict[str, Any]) -> Path:
    gradle = find_gradle()
    if not gradle:
        raise RuntimeError("Gradle is unavailable; ordinary tasks should use the prebuilt probe")
    workspace = Path(str(state["workspace"]))
    probe = workspace / "probe"
    if not probe.is_dir():
        prepare_local_probe(workspace)
    run([gradle, "--no-daemon", "-p", str(probe), ":app:assembleDebug"], capture=False)
    apk = probe / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if not apk.is_file():
        raise RuntimeError("local probe build did not produce an APK")
    state["probe_apk"] = str(apk)
    state["probe_apk_sha256"] = sha256(apk)
    state["probe_origin"] = "LOCAL_BUILD"
    write_current(root, state)
    return apk


def prepare_product_sandbox(root: Path, state: dict[str, Any], task: dict[str, Any]) -> Path:
    workspace = Path(str(state["workspace"]))
    sandbox = workspace / "product-sandbox"
    exact = clone_exact_product(task, sandbox)
    gradle_file = sandbox / "android" / "app" / "build.gradle.kts"
    text = gradle_file.read_text(encoding="utf-8")
    old = 'applicationId = "com.mobileproxymish.app"'
    new = f'applicationId = "{SANDBOX_PACKAGE}"'
    if old not in text:
        raise RuntimeError("cannot create Product Sandbox: applicationId line not found")
    gradle_file.write_text(text.replace(old, new, 1), encoding="utf-8")
    state["sandbox_path"] = str(sandbox)
    state["product_source_sha"] = exact
    write_current(root, state)
    return sandbox


def attached_device(adb: str) -> None:
    lines = run([adb, "devices"]).stdout.splitlines()[1:]
    devices = [line for line in lines if "\tdevice" in line]
    if len(devices) != 1:
        raise RuntimeError(f"expected exactly one ADB device, found {len(devices)}")


def command_doctor(_: argparse.Namespace) -> int:
    root = ensure_layout()
    required: dict[str, str] = {
        "PYTHON": "PASS",
        "GIT": "PASS" if shutil.which("git") else "FAIL",
        "GH": "PASS" if shutil.which("gh") else "FAIL",
    }
    if required["GH"] == "PASS":
        auth = run([shutil.which("gh") or "gh", "auth", "status", "-h", "github.com"], check=False)
        required["GH_AUTH"] = "PASS" if auth.returncode == 0 else "FAIL"
    else:
        required["GH_AUTH"] = "FAIL"
    adb = find_adb()
    required["ADB"] = "PASS" if adb else "FAIL"
    if adb:
        try:
            attached_device(adb)
            required["DEVICE"] = "PASS"
        except Exception:
            required["DEVICE"] = "FAIL"
    else:
        required["DEVICE"] = "FAIL"
    optional = {
        "JAVA": "AVAILABLE" if shutil.which("java") else "UNAVAILABLE",
        "GRADLE": "AVAILABLE" if find_gradle() else "UNAVAILABLE",
        "RUST": "AVAILABLE" if shutil.which("cargo") else "UNAVAILABLE",
        "CARGO_NDK": "AVAILABLE" if shutil.which("cargo-ndk") else "UNAVAILABLE",
    }
    overall = "PASS" if all(value == "PASS" for value in required.values()) else "FAIL"
    print(f"MISH_LAB_DOCTOR={overall}")
    for key, value in required.items():
        print(f"{key}={value}")
    for key, value in optional.items():
        print(f"{key}={value}")
    print(f"LAB_ROOT={root}")
    print(f"READY_FOR_STANDARD_TASKS={'YES' if overall == 'PASS' else 'NO'}")
    return 0 if overall == "PASS" else 2


def command_update(_: argparse.Namespace) -> int:
    root = repo_root()
    run(["git", "-C", str(root), "pull", "--ff-only", "origin", "main"], capture=False)
    print("MISH_LAB_UPDATE=PASS")
    print(f"LAB_SHA={current_lab_sha()}")
    return 0


def prepare_task(issue_arg: str) -> int:
    root = ensure_layout()
    issue = resolve_issue(issue_arg)
    task = parse_task_body(str(issue.get("body") or ""))
    validate_task(task)
    task_id = str(task["task_id"])
    acquire_lock(root, task_id)
    workspace = root / "work" / task_id
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "task.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    product_apk_path, product_apk_sha = ensure_product_apk(task, root)
    kind = execution_kind(task)
    state: dict[str, Any] = {
        "task_id": task_id,
        "issue_number": int(issue["number"]),
        "issue_url": issue.get("url"),
        "operation": task["operation"],
        "execution": kind,
        "workspace": str(workspace),
        "product_source_sha": (task.get("product") or {}).get("source_sha"),
        "product_apk": product_apk_path,
        "product_apk_sha256": product_apk_sha,
        "lab_sha": current_lab_sha(),
    }
    if kind == "ready_probe":
        apk, manifest = download_ready_probe(root)
        state["probe_apk"] = str(apk)
        state["probe_apk_sha256"] = manifest["sha256"]
        state["probe_origin"] = "PREBUILT_CI"
    elif kind == "product_sandbox":
        prepare_product_sandbox(root, state, task)
    write_current(root, state)
    print("MISH_LAB_WORK=READY")
    print(f"TASK_ID={task_id}")
    print(f"EXECUTION={kind}")
    print(f"WORKSPACE={workspace}")
    print(f"PRODUCT_APK={'VERIFIED' if product_apk_sha else 'NOT_REQUIRED'}")
    if kind == "ready_probe":
        print("PROBE=READY_PREBUILT")
        print("NEXT=mish-lab run")
    elif kind == "product_sandbox":
        print("SANDBOX=READY")
        print("NEXT=edit workspace or run 'mish-lab sandbox build'")
    else:
        print("NEXT=work in the workspace, then create result.json and submit")
    return 0


def command_work(args: argparse.Namespace) -> int:
    return prepare_task(args.issue)


def command_next(_: argparse.Namespace) -> int:
    return prepare_task("next")


def run_ready_probe(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    apk = Path(str(state.get("probe_apk") or ""))
    if not apk.is_file():
        apk, manifest = download_ready_probe(root)
        state["probe_apk"] = str(apk)
        state["probe_apk_sha256"] = manifest["sha256"]
        state["probe_origin"] = "PREBUILT_CI"
        write_current(root, state)
    adb = find_adb()
    if not adb:
        raise RuntimeError("ADB is unavailable; run doctor")
    attached_device(adb)
    run([adb, "install", "-r", str(apk)], capture=False)
    run([adb, "shell", "am", "force-stop", LAB_PACKAGE], check=False)
    run([adb, "shell", "am", "start", "-W", "-n", LAB_ACTIVITY], capture=False)
    raw = ""
    for _ in range(20):
        reply = run([adb, "shell", "run-as", LAB_PACKAGE, "cat", "files/result.json"], check=False)
        if reply.returncode == 0 and reply.stdout.strip().startswith("{"):
            raw = reply.stdout.strip()
            break
        time.sleep(0.5)
    if not raw:
        raise RuntimeError("LAB probe did not produce result.json")
    try:
        observed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LAB probe returned invalid JSON: {exc}") from exc
    required = {"status", "sdk", "abi", "wifi_present", "wifi_validated", "cellular_present", "cellular_validated", "vpn_present"}
    if not isinstance(observed, dict) or not required.issubset(observed):
        raise RuntimeError("LAB probe result is missing required fields")
    result = {
        "schema": RESULT_SCHEMA,
        "task_id": state["task_id"],
        "status": "CONCLUSIVE" if observed.get("status") == "PASS" else "PARTIAL",
        "operation": state["operation"],
        "execution": state["execution"],
        "observations": observed,
        "product_source_sha": state.get("product_source_sha"),
        "product_apk_sha256": state.get("product_apk_sha256"),
        "probe_apk_sha256": state.get("probe_apk_sha256"),
        "product_changed": False,
    }
    return result


def command_run(_: argparse.Namespace) -> int:
    root = ensure_layout()
    state = read_current(root)
    if state.get("execution") != "ready_probe":
        raise RuntimeError(f"'run' is automatic only for ready_probe tasks; current execution={state.get('execution')}")
    result = run_ready_probe(root, state)
    workspace = Path(str(state["workspace"]))
    result_path = workspace / "result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    state["result"] = str(result_path)
    state["status"] = result["status"]
    write_current(root, state)
    print("MISH_LAB_RUN=PASS")
    print(f"TASK_ID={state['task_id']}")
    print(f"RESULT={result['status']}")
    print("NEXT=mish-lab submit")
    return 0


def command_build(_: argparse.Namespace) -> int:
    root = ensure_layout()
    state = read_current(root)
    apk = build_local_probe(root, state)
    print("MISH_LAB_BUILD=PASS")
    print(f"APK={apk}")
    print(f"APK_SHA256={sha256(apk)}")
    return 0


def load_task_from_state(state: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(state["workspace"])) / "task.json"
    return json.loads(path.read_text(encoding="utf-8"))


def command_sandbox_prepare(_: argparse.Namespace) -> int:
    root = ensure_layout()
    state = read_current(root)
    task = load_task_from_state(state)
    sandbox = prepare_product_sandbox(root, state, task)
    print("MISH_LAB_SANDBOX=READY")
    print(f"PATH={sandbox}")
    print(f"PACKAGE={SANDBOX_PACKAGE}")
    return 0


def command_sandbox_build(_: argparse.Namespace) -> int:
    root = ensure_layout()
    state = read_current(root)
    sandbox_value = state.get("sandbox_path")
    if not sandbox_value:
        command_sandbox_prepare(argparse.Namespace())
        state = read_current(root)
        sandbox_value = state.get("sandbox_path")
    sandbox = Path(str(sandbox_value))
    gradle = find_gradle()
    if not gradle:
        raise RuntimeError("Gradle is unavailable")
    if not shutil.which("cargo") or not shutil.which("cargo-ndk"):
        raise RuntimeError("cargo and cargo-ndk are required for Product Sandbox builds")
    run([gradle, "--no-daemon", "-p", str(sandbox / "android"), ":app:assembleDebug"], cwd=sandbox, capture=False)
    apk = sandbox / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if not apk.is_file():
        raise RuntimeError("Product Sandbox build did not produce APK")
    state["sandbox_apk"] = str(apk)
    state["sandbox_apk_sha256"] = sha256(apk)
    write_current(root, state)
    print("MISH_LAB_SANDBOX_BUILD=PASS")
    print(f"APK={apk}")
    return 0


def command_sandbox_run(_: argparse.Namespace) -> int:
    root = ensure_layout()
    state = read_current(root)
    apk_value = state.get("sandbox_apk")
    if not apk_value or not Path(str(apk_value)).is_file():
        command_sandbox_build(argparse.Namespace())
        state = read_current(root)
        apk_value = state.get("sandbox_apk")
    adb = find_adb()
    if not adb:
        raise RuntimeError("ADB is unavailable")
    attached_device(adb)
    run([adb, "install", "-r", str(apk_value)], capture=False)
    run([adb, "shell", "am", "start", "-W", "-n", SANDBOX_ACTIVITY], capture=False)
    print("MISH_LAB_SANDBOX_RUN=PASS")
    print(f"PACKAGE={SANDBOX_PACKAGE}")
    return 0


def command_status(_: argparse.Namespace) -> int:
    root = ensure_layout()
    state = read_current(root)
    print("MISH_LAB_STATUS=ACTIVE")
    print(f"TASK_ID={state.get('task_id')}")
    print(f"EXECUTION={state.get('execution')}")
    print(f"WORKSPACE={state.get('workspace')}")
    print(f"RESULT={'READY' if state.get('result') else 'PENDING'}")
    if state.get("status"):
        print(f"RESULT_STATUS={state['status']}")
    return 0


def command_submit(_: argparse.Namespace) -> int:
    root = ensure_layout()
    state = read_current(root)
    workspace = Path(str(state["workspace"]))
    result_path = Path(str(state.get("result") or workspace / "result.json"))
    if not result_path.is_file():
        raise RuntimeError(f"result not found: {result_path}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("schema") != RESULT_SCHEMA or result.get("task_id") != state.get("task_id"):
        raise RuntimeError("result schema/task identity mismatch")
    body_path = workspace / "submit.md"
    body_path.write_text("MISH_LAB_RESULT\n\n```json\n" + json.dumps(result, indent=2) + "\n```\n", encoding="utf-8")
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("gh is unavailable")
    issue = str(state["issue_number"])
    run([gh, "issue", "comment", issue, "--repo", LAB_REPO, "--body-file", str(body_path)], capture=False)
    run([gh, "issue", "close", issue, "--repo", LAB_REPO], capture=False)
    release_lock(root, str(state["task_id"]))
    current = root / "current.json"
    if current.exists():
        current.unlink()
    archive = root / "results" / f"{state['task_id']}.json"
    shutil.copy2(result_path, archive)
    print("MISH_LAB_SUBMIT=PASS")
    print(f"TASK_ID={state['task_id']}")
    print(f"ISSUE={issue}")
    return 0


def command_selftest(_: argparse.Namespace) -> int:
    sample = """```json\n{\"schema\":\"mish.lab-task/v1\",\"task_id\":\"LAB-0001\",\"operation\":\"android.device_facts_probe\"}\n```"""
    task = parse_task_body(sample)
    validate_task(task)
    if execution_kind(task) != "ready_probe":
        raise AssertionError("ready probe routing failed")
    sandbox = dict(task)
    sandbox["operation"] = "product.sandbox"
    validate_task(sandbox)
    if execution_kind(sandbox) != "product_sandbox":
        raise AssertionError("sandbox routing failed")
    print("MISH_LAB_SELFTEST=PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mish-lab", description="Simple local Android research lab")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor").set_defaults(func=command_doctor)
    sub.add_parser("update").set_defaults(func=command_update)
    sub.add_parser("next").set_defaults(func=command_next)
    work = sub.add_parser("work")
    work.add_argument("issue")
    work.set_defaults(func=command_work)
    sub.add_parser("run").set_defaults(func=command_run)
    sub.add_parser("build").set_defaults(func=command_build)
    sub.add_parser("status").set_defaults(func=command_status)
    sub.add_parser("submit").set_defaults(func=command_submit)
    sub.add_parser("selftest").set_defaults(func=command_selftest)
    sandbox = sub.add_parser("sandbox")
    sandbox_sub = sandbox.add_subparsers(dest="sandbox_command", required=True)
    sandbox_sub.add_parser("prepare").set_defaults(func=command_sandbox_prepare)
    sandbox_sub.add_parser("build").set_defaults(func=command_sandbox_build)
    sandbox_sub.add_parser("run").set_defaults(func=command_sandbox_run)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"MISH_LAB_ERROR={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

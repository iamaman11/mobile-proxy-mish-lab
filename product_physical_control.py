#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import mish_lab as lab
import product_physical_e3 as e3

CONTROL_ISSUE = 11
OWNER = "iamaman11"
RESULT_SCHEMA = "mish.product-physical-result/v1"
NO_PENDING = 3
BUILD_PENDING = 4
COMMAND_RE = re.compile(r"[0-9a-f]{40}")


def issue_comments() -> list[dict[str, Any]]:
    payload = e3.gh_json([
        "api", "--paginate", "--slurp",
        f"repos/{e3.LAB_REPO}/issues/{CONTROL_ISSUE}/comments?per_page=100",
    ])
    if not isinstance(payload, list):
        raise RuntimeError("control issue comments response is invalid")
    pages = payload if not payload or isinstance(payload[0], list) else [payload]
    comments: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, list):
            raise RuntimeError("control issue comments page is invalid")
        comments.extend(item for item in page if isinstance(item, dict))
    return comments


def latest_request(comments: list[dict[str, Any]]) -> tuple[int, str] | None:
    requests: list[tuple[int, str]] = []
    for item in comments:
        user = item.get("user") or {}
        body = str(item.get("body") or "")
        comment_id = item.get("id")
        if user.get("login") != OWNER or not isinstance(comment_id, int):
            continue
        if COMMAND_RE.fullmatch(body):
            requests.append((comment_id, body))
    return max(requests, default=None, key=lambda item: item[0])


def marker_matches(body: str, marker: str, request_id: int, source_sha: str) -> bool:
    if marker not in body:
        return False
    rid = re.search(r"REQUEST_COMMENT_ID=(\d+)", body)
    sha = re.search(r"SOURCE_SHA=([0-9a-f]{40})", body)
    return bool(rid and sha and int(rid.group(1)) == request_id and sha.group(1) == source_sha)


def request_state(comments: list[dict[str, Any]]) -> tuple[int, str, str]:
    request = latest_request(comments)
    if request is None:
        raise LookupError("NO_REQUEST")
    request_id, source_sha = request
    for item in comments:
        body = str(item.get("body") or "")
        if marker_matches(body, "PRODUCT_PHYSICAL_RESULT", request_id, source_sha):
            raise LookupError("ALREADY_COMPLETE")
        if marker_matches(body, "PRODUCT_PHYSICAL_CANDIDATE=FAILED", request_id, source_sha):
            return request_id, source_sha, "BUILD_FAILED"
    ready = any(
        marker_matches(str(item.get("body") or ""), "PRODUCT_PHYSICAL_CANDIDATE=READY", request_id, source_sha)
        for item in comments
    )
    return request_id, source_sha, "READY" if ready else "BUILDING"


def release_tag(request_id: int) -> str:
    return f"physical-e3-req-{request_id}"


def download_release_candidate(
    root: Path,
    request_id: int,
    source_sha: str,
) -> tuple[Path, Path, dict[str, Any]]:
    task_id = f"REQ-{request_id}"
    tag = release_tag(request_id)
    destination = root / "cache" / "product-e3-release" / source_sha / task_id
    if destination.is_dir():
        try:
            product_apk, test_apk, manifest = e3.verify_candidate(destination, task_id, source_sha)
            if manifest.get("request_comment_id") != request_id:
                raise RuntimeError("candidate request_comment_id mismatch")
            if manifest.get("issue_number") != CONTROL_ISSUE:
                raise RuntimeError("candidate control issue identity mismatch")
            if manifest.get("release_tag") != tag:
                raise RuntimeError("candidate release_tag mismatch")
            if manifest.get("distribution") != "LAB_GITHUB_PRERELEASE":
                raise RuntimeError("candidate distribution mismatch")
            return product_apk, test_apk, manifest
        except Exception:
            shutil.rmtree(destination)

    destination.mkdir(parents=True, exist_ok=True)
    e3.run([
        e3.find_gh(), "release", "download", tag,
        "--repo", e3.LAB_REPO,
        "--dir", str(destination),
    ], capture=False)
    product_apk, test_apk, manifest = e3.verify_candidate(destination, task_id, source_sha)
    if manifest.get("request_comment_id") != request_id:
        raise RuntimeError("candidate request_comment_id mismatch")
    if manifest.get("issue_number") != CONTROL_ISSUE:
        raise RuntimeError("candidate control issue identity mismatch")
    if manifest.get("release_tag") != tag:
        raise RuntimeError("candidate release_tag mismatch")
    if manifest.get("distribution") != "LAB_GITHUB_PRERELEASE":
        raise RuntimeError("candidate distribution mismatch")
    return product_apk, test_apk, manifest


def post_result(result: dict[str, Any]) -> None:
    body = (
        "PRODUCT_PHYSICAL_RESULT\n\n"
        f"`REQUEST_COMMENT_ID={result['request_comment_id']}`\n"
        f"`SOURCE_SHA={result['source_sha']}`\n"
        f"`E3_OUTCOME={result['outcome']}`\n\n"
        "```json\n" + json.dumps(result, indent=2) + "\n```\n"
    )
    e3.run([
        e3.find_gh(), "issue", "comment", str(CONTROL_ISSUE),
        "--repo", e3.LAB_REPO, "--body", body,
    ], capture=False)


def execute() -> int:
    comments = issue_comments()
    try:
        request_id, source_sha, state = request_state(comments)
    except LookupError as exc:
        print(f"MISH_PRODUCT_CONTROL={exc.args[0]}")
        return NO_PENDING

    print(f"MISH_PRODUCT_CONTROL_REQUEST={request_id}")
    print(f"SOURCE_SHA={source_sha}")
    if state == "BUILD_FAILED":
        print("MISH_PRODUCT_CONTROL=BUILD_FAILED")
        return 1
    if state != "READY":
        print("MISH_PRODUCT_CONTROL=BUILD_PENDING")
        return BUILD_PENDING

    root = lab.ensure_layout()
    task_id = f"REQ-{request_id}"
    lab.acquire_lock(root, task_id)
    try:
        product_apk, test_apk, manifest = download_release_candidate(root, request_id, source_sha)

        adb = e3.find_adb()
        if not adb:
            raise RuntimeError("ADB is unavailable; run mish-lab doctor")
        device = e3.verify_device(adb)
        summary, raw = e3.run_physical_e3(adb, product_apk, test_apk, 20)
        raw_path = root / "results" / f"product-physical-{request_id}-instrumentation.txt"
        raw_path.write_text(raw, encoding="utf-8")

        result = {
            "schema": RESULT_SCHEMA,
            "request_comment_id": request_id,
            "source_sha": source_sha,
            "outcome": summary["outcome"],
            "device": device,
            "candidate": {
                "release_tag": manifest["release_tag"],
                "distribution": manifest["distribution"],
                "lab_sha": manifest["lab_sha"],
                "build_run_id": manifest["build_run_id"],
                "product_apk_sha256": manifest["product_apk_sha256"],
                "test_apk_sha256": manifest["test_apk_sha256"],
                "signing_certificate_sha256": manifest["signing_certificate_sha256"],
                "scope": manifest["scope"],
            },
            "e3": summary,
            "raw_instrumentation": "LOCAL_ONLY",
        }
        post_result(result)
        print("MISH_PRODUCT_PHYSICAL_CONTROL=COMPLETE")
        print(f"REQUEST_COMMENT_ID={request_id}")
        print(f"RELEASE_TAG={manifest['release_tag']}")
        print(f"E3_OUTCOME={summary['outcome']}")
        return 0 if summary["outcome"] == "PASS" else 2
    finally:
        lab.release_lock(root, task_id)


def selftest() -> int:
    sha1 = "a" * 40
    sha2 = "b" * 40
    comments = [
        {"id": 10, "user": {"login": OWNER}, "body": sha1},
        {"id": 11, "user": {"login": "someone-else"}, "body": sha2},
        {"id": 12, "user": {"login": OWNER}, "body": sha2},
        {"id": 13, "user": {"login": "github-actions[bot]"}, "body": "PRODUCT_PHYSICAL_CANDIDATE=READY\n`REQUEST_COMMENT_ID=12`\n`SOURCE_SHA=" + sha2 + "`"},
    ]
    if latest_request(comments) != (12, sha2):
        raise AssertionError("latest request selection failed")
    if request_state(comments) != (12, sha2, "READY"):
        raise AssertionError("READY state resolution failed")
    if release_tag(12) != "physical-e3-req-12":
        raise AssertionError("release tag derivation failed")

    failed = comments[:-1] + [
        {"id": 13, "user": {"login": "github-actions[bot]"}, "body": "PRODUCT_PHYSICAL_CANDIDATE=FAILED\n`REQUEST_COMMENT_ID=12`\n`SOURCE_SHA=" + sha2 + "`"}
    ]
    if request_state(failed) != (12, sha2, "BUILD_FAILED"):
        raise AssertionError("build failure state resolution failed")

    comments.append({"id": 14, "user": {"login": OWNER}, "body": "PRODUCT_PHYSICAL_RESULT\n`REQUEST_COMMENT_ID=12`\n`SOURCE_SHA=" + sha2 + "`"})
    try:
        request_state(comments)
    except LookupError as exc:
        if exc.args[0] != "ALREADY_COMPLETE":
            raise
    else:
        raise AssertionError("completed request was not terminal")
    print("MISH_PRODUCT_PHYSICAL_CONTROL_SELFTEST=PASS")
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "execute"
    try:
        if command == "execute":
            return execute()
        if command == "selftest":
            return selftest()
        raise RuntimeError(f"unsupported command: {command}")
    except Exception as exc:
        print(f"MISH_PRODUCT_PHYSICAL_CONTROL_ERROR={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

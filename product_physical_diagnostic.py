#!/usr/bin/env python3
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import product_physical_e3 as e3

DIAGNOSTIC_TEST_CLASS = "com.mobileproxymish.app.cellular.PhysicalCompositionDiagnosticTest"
NOT_AVAILABLE_MARKERS = (
    "ClassNotFoundException",
    "Could not find class",
    "No tests found",
)


def _parse_marked_lines(raw: str, marker: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for line in raw.splitlines():
        if marker in line:
            items.append(e3.parse_kv_tail(line, marker))
    return items


def run_composition_diagnostic(
    adb: str,
    product_apk: Path,
    test_apk: Path,
    grant_wait_seconds: int,
) -> tuple[dict[str, Any], str]:
    """Run a read-only PRODUCT diagnostic before E3 without changing E3 acceptance semantics."""
    e3.install_apk(adb, product_apk, "PRODUCT")
    e3.install_apk(adb, test_apk, "TEST")

    e3.run([adb, "shell", "am", "force-stop", e3.PRODUCT_PACKAGE], check=False)
    launch = e3.run([
        adb,
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        f"{e3.PRODUCT_PACKAGE}/.MainActivity",
    ], check=False)
    if launch.returncode != 0:
        raise RuntimeError("PRODUCT launcher activity failed before composition diagnostic")

    if grant_wait_seconds > 0:
        print(f"MISH_LAB_MAGISK_GRANT_WINDOW_SECONDS={grant_wait_seconds}")
        print(f"MISH_LAB_MAGISK_PACKAGE={e3.PRODUCT_PACKAGE}")
        time.sleep(grant_wait_seconds)

    command = [
        adb,
        "shell",
        "am",
        "instrument",
        "-w",
        "-r",
        "-e",
        "class",
        DIAGNOSTIC_TEST_CLASS,
        f"{e3.TEST_PACKAGE}/{e3.RUNNER}",
    ]
    reply = e3.run(command, check=False, timeout=180)
    raw = (reply.stdout or "") + (("\n" + reply.stderr) if reply.stderr else "")

    unavailable = any(marker in raw for marker in NOT_AVAILABLE_MARKERS)
    runner_ok = (
        reply.returncode == 0
        and "OK (1 test)" in raw
        and "FAILURES!!!" not in raw
        and "INSTRUMENTATION_FAILED" not in raw
    )
    if unavailable:
        status = "NOT_AVAILABLE"
    elif runner_ok:
        status = "OBSERVED"
    else:
        status = "FAILED"

    summary: dict[str, Any] = {
        "status": status,
        "instrumentation_exit_code": reply.returncode,
        "runner_ok": runner_ok,
        "policy_candidates": _parse_marked_lines(raw, "PHYSICAL_POLICY_DIAGNOSTIC "),
        "proxy": _parse_marked_lines(raw, "PHYSICAL_PROXY_DIAGNOSTIC "),
        "general": _parse_marked_lines(raw, "PHYSICAL_DIAGNOSTIC "),
    }
    return summary, raw


def selftest() -> int:
    raw = (
        "I/System.out: PHYSICAL_POLICY_DIAGNOSTIC candidate=1 mark=0x200000 "
        "ipv4_priority_collision=false ipv6_priority_collision=true\n"
        "I/System.out: PHYSICAL_PROXY_DIAGNOSTIC runtime_state=RUNNING\n"
    )
    policy = _parse_marked_lines(raw, "PHYSICAL_POLICY_DIAGNOSTIC ")
    proxy = _parse_marked_lines(raw, "PHYSICAL_PROXY_DIAGNOSTIC ")
    if policy != [{
        "candidate": "1",
        "mark": "0x200000",
        "ipv4_priority_collision": "false",
        "ipv6_priority_collision": "true",
    }]:
        raise AssertionError("policy diagnostic parser failed")
    if proxy != [{"runtime_state": "RUNNING"}]:
        raise AssertionError("proxy diagnostic parser failed")
    print("MISH_PRODUCT_PHYSICAL_DIAGNOSTIC_SELFTEST=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest())

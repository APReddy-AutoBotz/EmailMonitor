"""Narrow approved disposable-host setup; never invoked by ordinary test imports."""

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

SETTINGS = ("net.ipv6.conf.all.forwarding", "net.ipv6.conf.default.forwarding")


def values() -> dict[str, int]:
    result: dict[str, int] = {}
    for setting in SETTINGS:
        raw = Path("/proc/sys/" + setting.replace(".", "/")).read_text(encoding="ascii")
        if raw not in ("0", "0\n", "1", "1\n"):
            raise RuntimeError("Unexpected existing IPv6 forwarding value")
        result[setting] = int(raw)
    return result


def state_digest() -> str:
    records = []
    for args in (
        ("address", "show"),
        ("-4", "route", "show", "table", "all"),
        ("-6", "route", "show", "table", "all"),
        ("-4", "rule", "show"),
        ("-6", "rule", "show"),
    ):
        result = subprocess.run(
            ["ip", "-j", *args], capture_output=True, text=True, check=True, timeout=5
        )
        parsed = json.loads(result.stdout)
        if type(parsed) is not list:
            raise RuntimeError("Missing disposable host-state evidence")
        records.append(parsed)
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()


def require_disposable_ci() -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
        or os.environ.get("RUNNER_OS") != "Linux"
        or os.environ.get("EM_REQUIRE_CONTROLLED_NETWORK") != "true"
    ):
        raise RuntimeError("Approved disposable GitHub-hosted Linux transport job required")


def initialize() -> None:
    require_disposable_ci()
    before, before_state = values(), state_digest()
    print(
        json.dumps({"ipv6_initialization_before": before, "host_state_digest": before_state}),
        flush=True,
    )
    for setting in SETTINGS:
        if before[setting] == 0:
            subprocess.run(
                ["sudo", "sysctl", "-w", setting + "=1"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
    after = values()
    if any(value != 1 for value in after.values()):
        raise RuntimeError("Approved IPv6 initialization did not establish both values")
    # Let kernel address/route initialization finish before the unchanged topology baseline.
    time.sleep(2)
    deadline, previous, stable = time.monotonic() + 10, "", 0
    while time.monotonic() < deadline:
        current = state_digest()
        stable = stable + 1 if current == previous else 1
        previous = current
        if stable >= 3:
            print(
                json.dumps({"ipv6_initialization_after": after, "host_state_digest": current}),
                flush=True,
            )
            return
        time.sleep(0.25)
    raise RuntimeError("Disposable host state did not settle before topology baseline")


if __name__ == "__main__":
    initialize()

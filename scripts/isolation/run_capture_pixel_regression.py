"""Fixed-output isolated Chromium regression. This is not app acceptance."""

import json
import os
import secrets
import subprocess
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from emailmonitor.fetching.browser_fixture import validate_applied_profile
from transport_topology import OWNER_LABEL, remove_owned, require_owner, resource

BRANCH = "refs/heads/codex/capture-pixel-regression-20261102"
COMMAND = [
    "python",
    "-c",
    (
        "from test_operator_capture_pixels import "
        "test_actual_sandboxed_chromium_redacts_temporarily_exposed_synthetic_values as run; run()"
    ),
]
PROXY_NAMES = {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
FAILURE_PHASE: ContextVar[str] = ContextVar("capture_failure_phase", default="admission")
FAILURE_PHASES = frozenset(
    {
        "admission",
        "build",
        "image_inspection",
        "create",
        "guest_preflight",
        "start",
        "wait",
        "guest_outcome",
        "guest_status",
    }
)


def validate_guest(value: dict[str, Any], image: str, owner: str, profile: Path) -> None:
    require_owner("container", value, owner)
    host, config = value["HostConfig"], value["Config"]
    env = config.get("Env") or []
    if (
        value["Image"] != image
        or config["User"] != "1000:1000"
        or config["Cmd"] != COMMAND
        or config.get("Tty")
        or config.get("OpenStdin")
        or any(item.partition("=")[0].lower() in PROXY_NAMES for item in env)
        or any(item.partition("=")[0] in {"DEBUG", "DEBUG_FILE", "PWDEBUG"} for item in env)
        or host["NetworkMode"] != "none"
        or host["Privileged"] is not False
        or host["CapAdd"]
        or host["CapDrop"] != ["ALL"]
        or not host["ReadonlyRootfs"]
        or host["Binds"]
        or host["IpcMode"] == "host"
        or host["PidMode"] == "host"
        or host["Memory"] != 536870912
        or host["MemorySwap"] != 536870912
        or host["NanoCpus"] != 1000000000
        or host["PidsLimit"] != 128
        or host["ShmSize"] != 134217728
        or host["PortBindings"]
        or host.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,size=256m"}
        or host.get("LogConfig", {}).get("Type") != "none"
        or set(value["NetworkSettings"]["Networks"]) != {"none"}
        or value["NetworkSettings"].get("Ports") not in (None, {})
        or config.get("Volumes")
        or any(
            item.get("Type") != "tmpfs" or item.get("Destination") not in {"/tmp", "/dev/shm"}
            for item in value["Mounts"]
        )
    ):
        raise RuntimeError("capture_pixel_guest_refused")
    validate_applied_profile(host["SecurityOpt"], json.loads(profile.read_text()))


def quiet_docker(*args: str, timeout: int) -> None:
    """No guest or build output crosses the fixed-output host boundary."""
    completed = subprocess.run(
        ["docker", *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError("capture_pixel_docker_refused")


def run() -> None:
    FAILURE_PHASE.set("admission")
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REF") != BRANCH:
        raise RuntimeError("capture_pixel_ci_refused")
    root = Path(__file__).resolve().parents[2]
    owner = secrets.token_hex(16)
    image_name, guest_name = "em-pixel-" + owner, "em-pixel-guest-" + owner
    profile = root / "scripts/isolation/seccomp-browser.json"
    operation_uncertain = True
    clean = True
    try:
        FAILURE_PHASE.set("build")
        quiet_docker(
            "build",
            "--platform=linux/amd64",
            "--label",
            OWNER_LABEL + "=" + owner,
            "--file",
            str(root / "scripts/isolation/Dockerfile.capture-pixel"),
            "--tag",
            image_name,
            str(root),
            timeout=600,
        )
        operation_uncertain = False
        FAILURE_PHASE.set("image_inspection")
        image = resource("image", image_name)
        if image is None:
            raise RuntimeError("capture_pixel_image_refused")
        require_owner("image", image, owner)
        image_id = str(image["Id"])
        operation_uncertain = True
        FAILURE_PHASE.set("create")
        quiet_docker(
            "create",
            "--name",
            guest_name,
            "--label",
            OWNER_LABEL + "=" + owner,
            "--network=none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--security-opt=seccomp=" + str(profile),
            "--read-only",
            "--user=1000:1000",
            "--memory=512m",
            "--memory-swap=512m",
            "--cpus=1.0",
            "--pids-limit=128",
            "--ulimit=nofile=256:256",
            "--ulimit=core=0:0",
            "--shm-size=128m",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=256m",
            "--log-driver=none",
            "--env=HOME=/tmp/browser-home",
            "--env=XDG_CONFIG_HOME=/tmp/browser-config",
            "--env=CHROME_CONFIG_HOME=/tmp/browser-config",
            "--env=XDG_CACHE_HOME=/tmp/browser-cache",
            image_id,
            *COMMAND,
            timeout=120,
        )
        operation_uncertain = False
        FAILURE_PHASE.set("guest_preflight")
        guest = resource("container", guest_name)
        if guest is None:
            raise RuntimeError("capture_pixel_guest_missing")
        validate_guest(guest, image_id, owner, profile)
        operation_uncertain = True
        FAILURE_PHASE.set("start")
        quiet_docker("start", guest_name, timeout=30)
        operation_uncertain = False
        FAILURE_PHASE.set("wait")
        quiet_docker("wait", guest_name, timeout=190)
        FAILURE_PHASE.set("guest_outcome")
        guest = resource("container", guest_name)
        if guest is None:
            raise RuntimeError("capture_pixel_guest_missing")
        validate_guest(guest, image_id, owner, profile)
        FAILURE_PHASE.set("guest_status")
        if (
            guest["State"]["Running"]
            or guest["State"]["OOMKilled"]
            or guest["State"]["ExitCode"] != 0
        ):
            raise RuntimeError("capture_pixel_test_refused")
    finally:
        for kind, name in (("container", guest_name), ("image", image_name)):
            try:
                remove_owned(kind, name, owner)
            except BaseException:  # noqa: BLE001 - cleanup uncertainty is a hard failure
                clean = False
        # A timed-out daemon mutation may complete after a point-in-time inspection.
        if operation_uncertain or not clean:
            raise RuntimeError("capture_pixel_cleanup_uncertain") from None


def main() -> None:
    FAILURE_PHASE.set("admission")
    try:
        run()
    except BaseException as error:  # noqa: BLE001 - never emit guest or Docker output
        if type(error) is RuntimeError and error.args == ("capture_pixel_cleanup_uncertain",):
            result = "capture_focus_result=cleanup_uncertain"
        else:
            phase = FAILURE_PHASE.get()
            result = "capture_focus_result=failed\ncapture_focus_phase=" + (
                phase if phase in FAILURE_PHASES else "unavailable"
            )
    else:
        print("capture_focus_result=passed")
        return
    # Write only after the triggering exception is cleared, so even a broken
    # output sink cannot chain its traceback to potentially sensitive details.
    print(result)
    raise SystemExit(1) from None


if __name__ == "__main__":
    main()

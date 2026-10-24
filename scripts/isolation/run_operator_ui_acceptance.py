"""Unique owned network-none UI guest, multiplexed actual ASGI diagnostic transport."""

import json
import os
import secrets
import selectors
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from emailmonitor.fetching.browser_fixture import validate_applied_profile, write_bounded_reply
from fastapi import FastAPI
from operator_ui_asgi import relay
from operator_ui_protocol import DiagnosticFrame, RequestFrame, encoded_reply, stderr_summary
from transport_topology import OWNER_LABEL, docker, remove_owned, require_owner, resource


def validate_guest(value: dict[str, Any], image: str, owner: str, profile: Path) -> None:
    require_owner("container", value, owner)
    host, config = value["HostConfig"], value["Config"]
    if (
        value["Image"] != image
        or config["User"] != "1000:1000"
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
        or host["PidsLimit"] != 128
        or host["ShmSize"] != 134217728
        or host["NanoCpus"] != 1000000000
        or host["PortBindings"]
        or host.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,size=256m"}
        or set(value["NetworkSettings"]["Networks"]) != {"none"}
        or value["NetworkSettings"].get("Ports") not in (None, {})
        or config.get("Volumes")
        or config["Cmd"] != ["python", "/app/operator_ui_acceptance.py"]
        or any(
            item.get("Type") != "tmpfs" or item.get("Destination") not in {"/tmp", "/dev/shm"}
            for item in value["Mounts"]
        )
    ):
        raise RuntimeError("Original approved isolated browser restrictions required")
    validate_applied_profile(host["SecurityOpt"], json.loads(profile.read_text()))


def request_reply(
    app: FastAPI,
    control: Callable[[str], None],
    raw: bytes,
    before_reply: Callable[[RequestFrame], bool],
) -> dict[str, object]:
    import asyncio

    try:
        value = json.loads(raw)
        if value.get("kind") == "control":
            if (
                set(value) != {"kind", "identifier", "action"}
                or type(value["identifier"]) is not int
                or value["action"]
                not in {
                    "publish",
                    "wait_exports",
                    "wait_jobs",
                    "fault_contacts",
                    "fault_quality",
                    "hold_quality",
                    "release_quality",
                    "hold_contacts",
                    "hold_events",
                    "release_contacts",
                    "wait_held",
                }
            ):
                raise ValueError("Fixed UI control grammar required")
            control(value["action"])
            return encoded_reply(value["identifier"], 200, {}, b"{}")
        request = RequestFrame.model_validate(value)
        reply = asyncio.run(relay(app, request))
        if before_reply(request):
            return {"kind": "reply", "identifier": request.identifier, "transport_abort": True}
        return reply
    except Exception as error:
        # Do not echo cookies, credentials or arbitrary request bodies in CI logs.
        raise RuntimeError("Owned UI request failed: " + type(error).__name__) from None


def conversation(
    name: str,
    app: FastAPI,
    setup: dict[str, object],
    control: Callable[[str], None],
    before_reply: Callable[[RequestFrame], bool],
) -> dict[str, Any]:
    process = subprocess.Popen(
        ["docker", "start", "--attach", "--interactive", name],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    assert process.stdin and process.stdout and process.stderr
    deadline = time.monotonic() + 180
    buffer, errors = bytearray(), bytearray()
    total, last_identifier = 0, 0
    pending: set[Future[dict[str, object]]] = set()
    result: dict[str, Any] | None = None
    stage, stages = "bootstrap", 0
    statuses: list[int] = []
    try:
        write_bounded_reply(process.stdin.fileno(), json.dumps(setup).encode() + b"\n", deadline)
        with ThreadPoolExecutor(max_workers=8) as executor, selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while result is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(
                        "UI diagnostic absolute deadline exceeded at "
                        + stage
                        + "; sanitized stderr="
                        + str(stderr_summary(bytes(errors)))
                        + "; actual reply statuses="
                        + str(statuses)
                    )
                for future in tuple(pending):
                    if future.done():
                        pending.remove(future)
                        reply = future.result()
                        status = reply.get("status")
                        if type(status) is int:
                            statuses.append(status)
                        write_bounded_reply(
                            process.stdin.fileno(),
                            json.dumps(reply).encode() + b"\n",
                            deadline,
                        )
                for key, _ in selector.select(min(remaining, 0.05)):
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > 4 * 1024 * 1024:
                        raise RuntimeError("UI diagnostic total output exceeded")
                    if key.data == "stderr":
                        errors.extend(chunk)
                        if len(errors) > 16384:
                            raise RuntimeError(
                                "UI diagnostic stderr exceeded at "
                                + stage
                                + "; sanitized stderr="
                                + str(stderr_summary(bytes(errors)))
                                + "; actual reply statuses="
                                + str(statuses)
                            )
                        continue
                    buffer.extend(chunk)
                    while b"\n" in buffer:
                        line, _, rest = buffer.partition(b"\n")
                        buffer = bytearray(rest)
                        if len(line) > 32768:
                            raise RuntimeError("UI request frame exceeded")
                        value = json.loads(line)
                        if value.get("kind") in {"stage", "failure"}:
                            diagnostic = DiagnosticFrame.model_validate(value)
                            if diagnostic.kind == "failure":
                                if diagnostic.stage != stage:
                                    raise RuntimeError("Unmatched UI failure stage")
                                raise RuntimeError(
                                    "Actual UI failure at "
                                    + stage
                                    + ": "
                                    + str(diagnostic.error)
                                    + "; fixed reason="
                                    + diagnostic.reason
                                    + (
                                        "; installed login phase="
                                        + diagnostic.installed_login_phase
                                        if diagnostic.installed_login_phase is not None
                                        else ""
                                    )
                                    + (
                                        "; outcome phase=" + diagnostic.outcome_phase
                                        if diagnostic.outcome_phase is not None
                                        else ""
                                    )
                                    + (
                                        "; focus exhaustion="
                                        + json.dumps(diagnostic.model_dump()["focus_exhaustion"])
                                        if diagnostic.focus_exhaustion is not None
                                        else ""
                                    )
                                    + (
                                        "; observation trace="
                                        + json.dumps(diagnostic.model_dump()["observation_trace"])
                                        if diagnostic.observation_trace is not None
                                        else ""
                                    )
                                    + (
                                        "; evidence phase=" + diagnostic.evidence_phase
                                        if diagnostic.evidence_phase is not None
                                        else ""
                                    )
                                    + (
                                        "; callback delivery="
                                        + diagnostic.installed_callback_delivery
                                        if diagnostic.installed_callback_delivery is not None
                                        else ""
                                    )
                                    + "; actual reply statuses="
                                    + str(diagnostic.api_statuses)
                                )
                            stages += 1
                            if stages > 32:
                                raise RuntimeError("UI diagnostic stage cap exceeded")
                            stage = diagnostic.stage
                            continue
                        if value.get("kind") == "result":
                            if pending:
                                raise RuntimeError("Guest completed with pending requests")
                            result = value
                            break
                        identifier = value.get("identifier")
                        if (
                            type(identifier) is not int
                            or identifier != last_identifier + 1
                            or identifier > 512
                            or len(pending) >= 8
                        ):
                            raise RuntimeError("Bounded ordered UI request identifiers required")
                        last_identifier = identifier
                        pending.add(
                            executor.submit(request_reply, app, control, bytes(line), before_reply)
                        )
                    if len(buffer) > 32768:
                        raise RuntimeError("UI request frame exceeded")
                if process.poll() is not None and result is None:
                    raise RuntimeError(
                        "Actual UI guest failed at "
                        + stage
                        + "; sanitized stderr="
                        + str(stderr_summary(bytes(errors)))
                        + "; actual reply statuses="
                        + str(statuses)
                    )
        process.stdin.close()
        if process.wait(timeout=10) != 0 or result.get("diagnostic") != "synthetic-operator-ui":
            raise RuntimeError("Actual UI completion evidence missing")
        return result
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()


def run(
    app: FastAPI,
    setup: dict[str, object],
    control: Callable[[str], None],
    before_reply: Callable[[RequestFrame], bool],
) -> dict[str, Any]:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("EM_REQUIRE_OPERATOR_UI") != "true"
    ):
        raise RuntimeError("Reviewed disposable CI only; no local browser execution")
    root = Path(__file__).resolve().parents[2]
    owner = secrets.token_hex(16)
    image_name, container_name = "emailmonitor-ui-" + owner, "emailmonitor-ui-guest-" + owner
    profile = root / "scripts/isolation/seccomp-browser.json"
    # Register unique names before daemon actions, allowing owned-only ambiguous-outcome cleanup.
    try:
        docker(
            "build",
            "--platform=linux/amd64",
            "--label",
            OWNER_LABEL + "=" + owner,
            "--file",
            str(root / "scripts/isolation/Dockerfile.operator-ui"),
            "--tag",
            image_name,
            str(root),
            timeout=600,
        )
        image = resource("image", image_name)
        if image is None:
            raise RuntimeError("Owned UI image missing")
        require_owner("image", image, owner)
        image_id = str(image["Id"])
        docker(
            "create",
            "--name",
            container_name,
            "--label",
            OWNER_LABEL + "=" + owner,
            "--interactive",
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
            "--env=EM_ISOLATION_DIAGNOSTIC=synthetic-operator-ui",
            "--env=HOME=/tmp/browser-home",
            "--env=XDG_CONFIG_HOME=/tmp/browser-config",
            "--env=CHROME_CONFIG_HOME=/tmp/browser-config",
            "--env=XDG_CACHE_HOME=/tmp/browser-cache",
            image_id,
            "python",
            "/app/operator_ui_acceptance.py",
        )
        guest = resource("container", container_name)
        if guest is None:
            raise RuntimeError("Owned UI guest missing")
        validate_guest(guest, image_id, owner, profile)
        result = conversation(container_name, app, setup, control, before_reply)
        guest = resource("container", container_name)
        if guest is None:
            raise RuntimeError("Final guest state missing")
        validate_guest(guest, image_id, owner, profile)
        if (
            guest["State"]["Running"]
            or guest["State"]["OOMKilled"]
            or guest["State"]["ExitCode"] != 0
        ):
            raise RuntimeError("Actual UI guest did not stop cleanly")
        return result
    finally:
        cleanup_errors = []
        for kind, name in (("container", container_name), ("image", image_name)):
            try:
                remove_owned(kind, name, owner)
            except Exception as error:
                cleanup_errors.append(type(error).__name__)
        if cleanup_errors:
            raise RuntimeError("Owned UI cleanup failed: " + ",".join(cleanup_errors))

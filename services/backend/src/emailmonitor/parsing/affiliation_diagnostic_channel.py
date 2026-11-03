"""Fixed private diagnostic transport, separate from normal XML observations.

Only a trusted composer may call this after private admission. Authored synthetic
tests may exercise it directly. No command, mount, environment or image selection
comes from a manifest, XML document, API or queue message.
"""

import json
import os
import selectors
import subprocess
import time
from collections.abc import Mapping

from emailmonitor.extraction.sciencedirect import MAX_BYTES
from emailmonitor.fetching.safety import IsolationUnavailable
from emailmonitor.parsing.affiliation_diagnostic import (
    MAX_OUTPUT,
    AffiliationDiagnostic,
    decode_output,
)
from emailmonitor.parsing.xml_channel import IMAGE, PRIVATE_PROFILE
from emailmonitor.parsing.xml_channel import _docker as _docker
from emailmonitor.parsing.xml_protocol import XmlExpectation, encode_input

COMMAND = ("python", "-m", "emailmonitor.parsing.affiliation_diagnostic_worker")
MARKER = "EM_PRIVATE_AFFILIATION_DIAGNOSTIC=one-file-private-diagnostic"
PROFILE = (*PRIVATE_PROFILE[:-1], "--env=" + MARKER)


def verify_profile(metadata: Mapping[str, object]) -> None:
    """Verify this exact mode against original inspect data, without rewriting it."""
    config = metadata["HostConfig"]
    image_config = metadata["Config"]
    if not isinstance(config, dict) or not isinstance(image_config, dict):
        raise ValueError("Diagnostic container profile required")
    mounts = metadata.get("Mounts", [])
    if (
        not isinstance(mounts, list)
        or len(mounts) > 1
        or any(
            not isinstance(mount, dict)
            or mount.get("Type") != "tmpfs"
            or mount.get("Destination") != "/tmp"
            or mount.get("Source", "") != ""
            for mount in mounts
        )
    ):
        raise ValueError("Host/volume mounts forbidden")
    limits = config.get("Ulimits")
    if (
        not isinstance(limits, list)
        or len(limits) != 2
        or any(not isinstance(limit, dict) for limit in limits)
    ):
        raise ValueError("Exact diagnostic ulimits required")
    expected = {
        "NetworkMode": "none",
        "Privileged": False,
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges"],
        "ReadonlyRootfs": True,
        "Memory": 134217728,
        "MemorySwap": 134217728,
        "PidsLimit": 32,
        "NanoCpus": 500000000,
    }
    if (
        any(config.get(k) != v or type(config.get(k)) is not type(v) for k, v in expected.items())
        or config.get("CapAdd")
        or config.get("Binds")
        or config.get("Mounts")
        or image_config.get("Volumes")
        or sorted(limits, key=lambda limit: str(limit.get("Name")))
        != [
            {"Name": "core", "Hard": 0, "Soft": 0},
            {"Name": "nofile", "Hard": 64, "Soft": 64},
        ]
        or any(type(limit.get(key)) is not int for limit in limits for key in ("Hard", "Soft"))
        or image_config.get("User") != "65532:65532"
        or image_config.get("Cmd") != list(COMMAND)
        or image_config.get("Entrypoint") not in (None, [])
        or config.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,size=16m"}
    ):
        raise ValueError("Diagnostic isolation/resource configuration mismatch")
    environment = image_config.get("Env", [])
    allowed = {
        "PATH",
        "LANG",
        "GPG_KEY",
        "PYTHON_VERSION",
        "PYTHON_SHA256",
        "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE",
        "EM_PRIVATE_AFFILIATION_DIAGNOSTIC",
    }
    if not isinstance(environment, list) or any(
        not isinstance(value, str) or "=" not in value or value.split("=", 1)[0] not in allowed
        for value in environment
    ):
        raise ValueError("Diagnostic container environment invalid")
    names = [value.split("=", 1)[0] for value in environment]
    if environment.count(MARKER) != 1 or len(names) != len(set(names)):
        raise ValueError("Exact diagnostic marker required")


def exchange(command: list[str], data: bytes, timeout: float = 30) -> bytes:
    """Bound both pipes while running, including before the process exits."""
    with subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as process:
        assert (
            process.stdin is not None and process.stdout is not None and process.stderr is not None
        )
        buffers = {"output": bytearray(), "error": bytearray()}
        offset = 0
        deadline = time.monotonic() + timeout
        try:
            with selectors.DefaultSelector() as selector:
                for stream, kind in (
                    (process.stdin, "input"),
                    (process.stdout, "output"),
                    (process.stderr, "error"),
                ):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(
                        stream,
                        selectors.EVENT_WRITE if kind == "input" else selectors.EVENT_READ,
                        kind,
                    )
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise IsolationUnavailable("affiliation_diagnostic_timeout")
                    for key, _ in selector.select(remaining):
                        if key.data == "input":
                            offset += os.write(key.fd, data[offset : offset + 8192])
                            if offset == len(data):
                                selector.unregister(key.fileobj)
                                process.stdin.close()
                        else:
                            chunk = os.read(key.fd, 4096)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            buffer = buffers[key.data]
                            buffer.extend(chunk)
                            if len(buffer) > (MAX_OUTPUT if key.data == "output" else 4096):
                                raise IsolationUnavailable("affiliation_diagnostic_output_limit")
                code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
                if code or buffers["error"]:
                    raise IsolationUnavailable("affiliation_diagnostic_failed")
                return bytes(buffers["output"])
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            raise


def _inspect(*args: str) -> dict[str, object]:
    result = json.loads(_docker(*args))
    if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
        raise IsolationUnavailable("affiliation_diagnostic_inspect_invalid")
    metadata: dict[str, object] = result[0]
    return metadata


def diagnose_in_container(data: bytes, expected: XmlExpectation) -> AffiliationDiagnostic:
    """One admitted buffer and expectation → one owned fixed-mode guest → counters.

    The shared input protocol validates content, identifier and profile in the guest.
    Output deliberately contains no digest or identifier; the newly created and
    verified container binds the response to this one invocation instead.
    """
    if type(data) is not bytes or not 1 <= len(data) <= MAX_BYTES:
        raise ValueError("Bounded diagnostic input required")
    framed = encode_input(data, expected)
    image_id = _inspect("image", "inspect", IMAGE).get("Id", "")
    if (
        not isinstance(image_id, str)
        or len(image_id) != 71
        or not image_id.startswith("sha256:")
        or any(c not in "0123456789abcdef" for c in image_id[7:])
    ):
        raise IsolationUnavailable("affiliation_diagnostic_image_identity_invalid")
    identifier = (
        _docker("create", "--pull=never", "--interactive", *PROFILE, image_id, *COMMAND)
        .decode("ascii")
        .strip()
    )
    if len(identifier) != 64 or any(c not in "0123456789abcdef" for c in identifier):
        raise IsolationUnavailable("affiliation_diagnostic_container_identity_invalid")
    try:
        metadata = _inspect("inspect", identifier)
        verify_profile(metadata)
        if metadata.get("Image") != image_id:
            raise IsolationUnavailable("affiliation_diagnostic_image_identity_mismatch")
        output = exchange(["docker", "start", "--attach", "--interactive", identifier], framed)
        state = _inspect("inspect", identifier).get("State")
        if (
            not isinstance(state, dict)
            or state.get("Running") is not False
            or type(state.get("ExitCode")) is not int
            or state.get("ExitCode") != 0
            or state.get("OOMKilled") is not False
        ):
            raise IsolationUnavailable("affiliation_diagnostic_exit_invalid")
        try:
            return decode_output(output)
        except (ValueError, TypeError, KeyError):
            raise IsolationUnavailable("affiliation_diagnostic_output_invalid") from None
    finally:
        _docker("rm", "--force", identifier)

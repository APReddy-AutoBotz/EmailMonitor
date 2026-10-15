"""Trusted synthetic host channel. No credentials/mounts/commands enter the sandbox."""

import json
import os
import selectors
import subprocess
import time
from collections.abc import Mapping

from emailmonitor.config import Settings
from emailmonitor.extraction.sciencedirect import MAX_BYTES, XmlObservation
from emailmonitor.extraction.xml_retained import (
    MAX_ENVELOPE,
    XML_DIGEST,
    XML_IDENTIFIER,
    XML_PROFILE,
)
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.fetching.safety import IsolationUnavailable
from emailmonitor.parsing.xml_protocol import XmlExpectation, encode_input

IMAGE = "emailmonitor-parser-diagnostic:local"
PROFILE = (
    "--network=none",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
    "--read-only",
    "--user=65532:65532",
    "--memory=128m",
    "--memory-swap=128m",
    "--cpus=0.5",
    "--pids-limit=32",
    "--ulimit=nofile=64:64",
    "--ulimit=core=0:0",
    "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
    "--env=EM_ISOLATION_DIAGNOSTIC=synthetic-test-only",
)
COMMAND = ("python", "-m", "emailmonitor.parsing.xml_worker")


def fixture_expectation() -> XmlExpectation:
    return XmlExpectation.model_validate(
        {
            "requested_identifier": XML_IDENTIFIER,
            "content_digest": XML_DIGEST,
            "source_profile": XML_PROFILE,
        }
    )


def decode_output(
    output: bytes, data: bytes, expected: XmlExpectation | None = None
) -> XmlObservation:
    expected = expected or fixture_expectation()
    expected = XmlExpectation.model_validate(expected.model_dump())
    expected.check_bytes(data)
    if not output or len(output) > MAX_ENVELOPE:
        raise ValueError("Bounded parser output required")

    # Reject duplicate keys, nonfinite numbers, trailing JSON and trailing garbage.
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate parser field")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise ValueError("Invalid parser number")

    decoder = json.JSONDecoder(object_pairs_hook=pairs, parse_constant=constant)
    document, end = decoder.raw_decode(output.decode("utf-8"))
    if output.decode("utf-8")[end:] != "\n" or not isinstance(document, dict):
        raise ValueError("Exact parser envelope required")
    if (
        set(document) != {"profile", "observation"}
        or document["profile"] != "network-none-parser-v1"
    ):
        raise ValueError("Registered parser profile required")
    observed = XmlObservation.model_validate(document["observation"])
    expected.check_observation(observed)
    return observed


def verify_profile(metadata: Mapping[str, object]) -> None:
    config = metadata["HostConfig"]
    image_config = metadata["Config"]
    if not isinstance(config, dict) or not isinstance(image_config, dict):
        raise ValueError("Container profile required")
    mounts = metadata.get("Mounts", [])
    if not isinstance(mounts, list) or any(
        not isinstance(mount, dict)
        or mount.get("Type") != "tmpfs"
        or mount.get("Destination") != "/tmp"
        or mount.get("Source", "") != ""
        for mount in mounts
    ):
        raise ValueError("Host/volume mounts forbidden")
    limits = config.get("Ulimits")
    if (
        not isinstance(limits, list)
        or len(limits) != 2
        or any(not isinstance(limit, dict) for limit in limits)
    ):
        raise ValueError("Exact parser ulimits required")
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
        any(config.get(k) != v for k, v in expected.items())
        or config.get("CapAdd")
        or config.get("Binds")
        or config.get("Mounts")
        or image_config.get("Volumes")
        or sorted(limits, key=lambda limit: str(limit.get("Name")))
        != [
            {"Name": "core", "Hard": 0, "Soft": 0},
            {"Name": "nofile", "Hard": 64, "Soft": 64},
        ]
        or image_config.get("User") != "65532:65532"
        or image_config.get("Cmd") != list(COMMAND)
        or image_config.get("Entrypoint") not in (None, [])
        or config.get("Tmpfs") != {"/tmp": "rw,noexec,nosuid,size=16m"}
    ):
        raise ValueError("Container isolation/resource configuration mismatch")


def _docker(*args: str) -> bytes:
    # Docker control responses use the same while-running bounded pipe reader.
    # No post-hoc unbounded capture_output/communicate buffer is permitted.
    try:
        output = exchange(["docker", *args], b"", timeout=15)
    except Exception:
        raise IsolationUnavailable("xml_container_control_failed") from None
    if len(output) > 65536:
        raise IsolationUnavailable("xml_container_control_failed")
    return output


def exchange(command: list[str], data: bytes, timeout: float = 30) -> bytes:
    """Bound concurrent stdout/stderr while writing input; no unbounded communicate()."""
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
                        raise IsolationUnavailable("xml_parser_timeout")
                    for key, _ in selector.select(remaining):
                        if key.data == "input":
                            offset += os.write(key.fd, data[offset : offset + 8192])
                            if offset == len(data):
                                selector.unregister(key.fileobj)
                                process.stdin.close()
                        else:
                            chunk = os.read(key.fd, 8192)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            buffer = buffers[key.data]
                            buffer.extend(chunk)
                            if len(buffer) > (MAX_ENVELOPE if key.data == "output" else 4096):
                                raise IsolationUnavailable("xml_parser_output_limit")
                code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
                if code or buffers["error"]:
                    raise IsolationUnavailable("xml_parser_failed")
                return bytes(buffers["output"])
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            raise


def parse_isolated(
    settings: Settings, data: bytes, *, expected: XmlExpectation | None = None
) -> XmlObservation:
    require_fixture(settings)
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_BYTES:
        raise ValueError("Bounded XML input required")
    expected = expected or fixture_expectation()
    framed = encode_input(data, expected)
    image_metadata = json.loads(_docker("image", "inspect", IMAGE))[0]
    image_id = image_metadata.get("Id", "")
    if (
        not isinstance(image_id, str)
        or len(image_id) != 71
        or not image_id.startswith("sha256:")
        or any(c not in "0123456789abcdef" for c in image_id[7:])
    ):
        raise IsolationUnavailable("xml_image_identity_invalid")
    identifier = (
        _docker("create", "--pull=never", "--interactive", *PROFILE, image_id, *COMMAND)
        .decode()
        .strip()
    )
    if len(identifier) != 64 or any(c not in "0123456789abcdef" for c in identifier):
        raise IsolationUnavailable("xml_container_identity_invalid")
    try:
        metadata = json.loads(_docker("inspect", identifier))[0]
        verify_profile(metadata)
        if metadata.get("Image") != image_id:
            raise IsolationUnavailable("xml_image_identity_mismatch")
        environment = metadata["Config"].get("Env", [])
        allowed = {
            "PATH",
            "LANG",
            "GPG_KEY",
            "PYTHON_VERSION",
            "PYTHON_SHA256",
            "PYTHONPATH",
            "PYTHONDONTWRITEBYTECODE",
            "EM_ISOLATION_DIAGNOSTIC",
        }
        if not isinstance(environment, list) or any(
            not isinstance(value, str) or value.split("=", 1)[0] not in allowed
            for value in environment
        ):
            raise IsolationUnavailable("xml_container_environment_invalid")
        output = exchange(["docker", "start", "--attach", "--interactive", identifier], framed)
        state = json.loads(_docker("inspect", identifier))[0]["State"]
        if (
            state.get("Running") is not False
            or state.get("ExitCode") != 0
            or state.get("OOMKilled") is not False
        ):
            raise IsolationUnavailable("xml_parser_exit_invalid")
        try:
            return decode_output(output, data, expected)
        except (ValueError, TypeError, KeyError):
            raise IsolationUnavailable("xml_parser_output_invalid") from None
    finally:
        _docker("rm", "--force", identifier)

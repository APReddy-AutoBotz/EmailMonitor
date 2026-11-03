"""Synthetic/mock transport checks; these are not actual Docker evidence."""

import copy
import hashlib
import io
import json
import sys
from collections.abc import Callable
from typing import Any

import pytest
from emailmonitor.extraction.sciencedirect import MAX_BYTES, parse_article
from emailmonitor.fetching.safety import IsolationUnavailable
from emailmonitor.parsing import affiliation_diagnostic_channel as channel
from emailmonitor.parsing import xml_channel
from emailmonitor.parsing.affiliation_diagnostic import diagnose, encode_output
from emailmonitor.parsing.xml_protocol import XmlExpectation, read_input
from test_affiliation_diagnostic_reproduction import IDENTIFIER, synthetic
from test_xml_pipeline import profile as normal_profile


def expectation(data: bytes) -> XmlExpectation:
    return XmlExpectation(
        requested_identifier=IDENTIFIER,
        content_digest=hashlib.sha256(data).hexdigest(),
        source_profile="xocs_document",
    )


def profile() -> dict[str, Any]:
    metadata = normal_profile()
    config = metadata["Config"]
    assert isinstance(config, dict)
    config.update(Cmd=list(channel.COMMAND), Env=[channel.MARKER])
    metadata["Image"] = "sha256:" + "a" * 64
    metadata["State"] = {"Running": False, "ExitCode": 0, "OOMKilled": False}
    return metadata


def docker_double(
    monkeypatch: pytest.MonkeyPatch,
    output: bytes,
    *,
    mutate: Callable[[dict[str, Any]], None] | None = None,
    fault: str = "",
) -> tuple[list[tuple[str, ...]], list[tuple[list[str], bytes]]]:
    calls: list[tuple[str, ...]] = []
    exchanges: list[tuple[list[str], bytes]] = []
    container = "b" * 64

    def docker(*args: str) -> bytes:
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            return json.dumps(
                [{"Id": "invalid" if fault == "image" else "sha256:" + "a" * 64}]
            ).encode()
        if args[0] == "create":
            assert args[-3:] == channel.COMMAND
            assert all(flag in args for flag in xml_channel.PRIVATE_PROFILE[:-1])
            assert "--pull=never" in args
            assert "--env=" + channel.MARKER in args
            assert "--env=" + xml_channel.PRIVATE_MARKER not in args
            assert xml_channel.PROFILE[-1] not in args
            assert args[-4] == "sha256:" + "a" * 64
            return b"invalid" if fault == "container" else container.encode()
        if args[0] == "inspect":
            metadata = profile()
            if mutate is not None:
                mutate(metadata)
            return json.dumps([metadata]).encode()
        assert args == ("rm", "--force", container)
        if fault == "cleanup":
            raise RuntimeError("private@example.org /private/path")
        return b""

    def exchange(command: list[str], data: bytes) -> bytes:
        exchanges.append((command, data))
        if fault == "exchange":
            raise IsolationUnavailable("affiliation_diagnostic_timeout")
        return output

    monkeypatch.setattr(channel, "_docker", docker)
    monkeypatch.setattr(channel, "exchange", exchange)
    return calls, exchanges


def test_separate_exact_profile_and_bound_single_buffer() -> None:
    metadata = profile()
    original = copy.deepcopy(metadata)
    channel.verify_profile(metadata)
    assert metadata == original
    assert channel.PROFILE[:-1] == xml_channel.PRIVATE_PROFILE[:-1]
    for private in (False, True):
        with pytest.raises(ValueError):
            xml_channel.verify_profile(metadata, private_offline=private)
    for command in (xml_channel.COMMAND, xml_channel.PRIVATE_COMMAND):
        metadata["Config"]["Cmd"] = list(command)
        with pytest.raises(ValueError):
            channel.verify_profile(metadata)


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("HostConfig", "NetworkMode", "bridge"),
        ("HostConfig", "Privileged", True),
        ("HostConfig", "Privileged", 0),
        ("HostConfig", "CapDrop", []),
        ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
        ("HostConfig", "SecurityOpt", ["seccomp=unconfined"]),
        ("HostConfig", "ReadonlyRootfs", False),
        ("HostConfig", "Memory", 0),
        ("HostConfig", "MemorySwap", -1),
        ("HostConfig", "PidsLimit", 0),
        ("HostConfig", "NanoCpus", 0),
        ("HostConfig", "Binds", ["/secret:/secret"]),
        ("HostConfig", "Mounts", [{"Type": "bind"}]),
        ("HostConfig", "Ulimits", []),
        ("HostConfig", "Tmpfs", {"/tmp": "rw,exec"}),
        ("Config", "User", "0:0"),
        ("Config", "Entrypoint", ["sh"]),
        ("Config", "Volumes", {"/secret": {}}),
        ("Config", "Env", []),
        ("Config", "Env", [channel.MARKER, channel.MARKER]),
        ("Config", "Env", [channel.MARKER, "EM_PRIVATE_AFFILIATION_DIAGNOSTIC=wrong"]),
        ("Config", "Env", ["EM_PRIVATE_AFFILIATION_DIAGNOSTIC=wrong"]),
        ("Config", "Env", [channel.MARKER, xml_channel.PRIVATE_MARKER]),
        ("Config", "Env", [channel.MARKER, "EM_ISOLATION_DIAGNOSTIC=synthetic-test-only"]),
        ("Config", "Env", [channel.MARKER, "SECRET=private@example.org"]),
        ("Config", "Env", [channel.MARKER, "PATH=/a", "PATH=/b"]),
        ("Config", "Env", [channel.MARKER, "PATH"]),
        ("Config", "Env", [channel.MARKER, 1]),
    ],
)
def test_profile_mismatch_refuses_before_start_and_cleans_owned_container(
    monkeypatch: pytest.MonkeyPatch, section: str, key: str, value: object
) -> None:
    data = synthetic()

    def mutate(metadata: dict[str, Any]) -> None:
        metadata[section][key] = value

    calls, exchanges = docker_double(monkeypatch, b"", mutate=mutate)
    with pytest.raises(ValueError):
        channel.diagnose_in_container(data, expectation(data))
    assert exchanges == []
    assert calls[-1] == ("rm", "--force", "b" * 64)


def test_exact_input_response_and_owned_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    data = synthetic(reference="cor")
    expected = expectation(data)
    diagnostic = diagnose(data, expected)
    calls, exchanges = docker_double(monkeypatch, encode_output(diagnostic))
    assert channel.diagnose_in_container(data, expected) == diagnostic
    assert len(exchanges) == 1
    command, framed = exchanges[0]
    assert command == ["docker", "start", "--attach", "--interactive", "b" * 64]
    assert read_input(io.BytesIO(framed)) == (data, expected)
    assert calls[-1] == ("rm", "--force", "b" * 64)
    assert sum(call[0] == "create" for call in calls) == 1
    assert sum(call[0] == "inspect" for call in calls) == 2


@pytest.mark.parametrize("fault", ["image", "container", "exchange", "cleanup"])
def test_control_failures_fail_closed(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    data = synthetic()
    output = encode_output(diagnose(data, expectation(data)))
    calls, exchanges = docker_double(monkeypatch, output, fault=fault)
    with pytest.raises((IsolationUnavailable, RuntimeError)):
        channel.diagnose_in_container(data, expectation(data))
    if fault in {"image", "container"}:
        assert exchanges == []
        assert all(call[0] != "rm" for call in calls)
    else:
        assert calls[-1] == ("rm", "--force", "b" * 64)


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("State", "Running", True),
        ("State", "ExitCode", 1),
        ("State", "ExitCode", False),
        ("State", "OOMKilled", True),
        ("State", "OOMKilled", None),
    ],
)
def test_exit_state_must_be_successful(
    monkeypatch: pytest.MonkeyPatch, section: str, key: str, value: object
) -> None:
    data = synthetic()

    def mutate(metadata: dict[str, Any]) -> None:
        metadata[section][key] = value

    calls, _ = docker_double(
        monkeypatch, encode_output(diagnose(data, expectation(data))), mutate=mutate
    )
    with pytest.raises(IsolationUnavailable, match="affiliation_diagnostic_exit_invalid"):
        channel.diagnose_in_container(data, expectation(data))
    assert calls[-1] == ("rm", "--force", "b" * 64)


@pytest.mark.parametrize("fault", ["image", "mount", "state", "ulimit"])
def test_other_metadata_mismatch_refuses(monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    data = synthetic()

    def mutate(metadata: dict[str, Any]) -> None:
        if fault == "image":
            metadata["Image"] = "sha256:" + "c" * 64
        elif fault == "mount":
            metadata["Mounts"] = [{"Type": "bind", "Source": "/private", "Destination": "/tmp"}]
        elif fault == "state":
            metadata["State"] = None
        else:
            metadata["HostConfig"]["Ulimits"][1]["Soft"] = False

    calls, _ = docker_double(monkeypatch, b"", mutate=mutate)
    with pytest.raises((ValueError, IsolationUnavailable)):
        channel.diagnose_in_container(data, expectation(data))
    assert calls[-1] == ("rm", "--force", "b" * 64)


def test_input_validation_precedes_container(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, _ = docker_double(monkeypatch, b"")
    data = synthetic()
    for changed in (b"", b"x" * (MAX_BYTES + 1), data + b" "):
        with pytest.raises(ValueError):
            channel.diagnose_in_container(changed, expectation(data))
    assert calls == []


def test_cross_mode_outputs_refuse_and_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    data = synthetic()
    normal = parse_article(data, IDENTIFIER)
    output = (
        json.dumps(
            {"profile": "network-none-parser-v1", "observation": normal.model_dump(mode="json")}
        ).encode()
        + b"\n"
    )
    calls, _ = docker_double(monkeypatch, output)
    with pytest.raises(IsolationUnavailable, match="affiliation_diagnostic_output_invalid"):
        channel.diagnose_in_container(data, expectation(data))
    assert calls[-1] == ("rm", "--force", "b" * 64)
    diagnostic_output = encode_output(diagnose(data, expectation(data)))
    with pytest.raises(ValueError):
        xml_channel.decode_output(diagnostic_output, data, expectation(data))


@pytest.mark.parametrize(
    "program,reason",
    [
        ("import sys; sys.stdout.write('x'*4097)", "output_limit"),
        ("import sys; sys.stderr.write('x'*4097)", "output_limit"),
        ("import sys; sys.stderr.write('private@example.org')", "failed"),
        ("raise SystemExit(1)", "failed"),
        ("import time; time.sleep(2)", "timeout"),
    ],
)
def test_live_pipe_limits_and_deadline(program: str, reason: str) -> None:
    with pytest.raises(IsolationUnavailable, match="affiliation_diagnostic_" + reason):
        channel.exchange([sys.executable, "-c", program], b"", timeout=0.1)


def test_concurrent_pipe_reader_handles_bounded_input_and_exact_limit() -> None:
    command = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(b'x'*4096); "
        "sys.stdout.flush(); sys.stdin.buffer.read()",
    ]
    assert channel.exchange(command, b"x" * MAX_BYTES) == b"x" * 4096

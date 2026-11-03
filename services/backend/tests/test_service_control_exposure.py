"""Mock-only evidence checks; never invoke Docker, sudo or host listener probes."""

import json
import os
from pathlib import Path

import pytest
from emailmonitor.runtime import control_exposure as control

UNIX = 'u_str LISTEN 0 4096 /run/docker.sock 100 * 0 users:(("dockerd",pid=42,fd=3))\n'
TCP = 'LISTEN 0 128 127.0.0.1:5432 0.0.0.0:* users:(("postgres",pid=43,fd=5))\n'


class Evidence:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.endpoint: object = "unix:///var/run/docker.sock"
        self.unix = UNIX
        self.tcp = TCP
        self.calls: list[list[str]] = []
        for key in tuple(os.environ):
            if key.startswith("DOCKER_"):
                monkeypatch.delenv(key)
        monkeypatch.setattr(os, "geteuid", lambda: 1000)
        monkeypatch.setattr(Path, "resolve", lambda self, strict=False: Path("/run/docker.sock"))
        monkeypatch.setattr(Path, "is_socket", lambda self: True)
        monkeypatch.setattr(control, "read_control", self.read)

    def read(self, command: list[str]) -> bytes:
        self.calls.append(command)
        if command == ["docker", "context", "inspect", "--format={{json .Endpoints.docker.Host}}"]:
            return json.dumps(self.endpoint).encode()
        prefix = [] if os.geteuid() == 0 else ["/usr/bin/sudo", "-n"]
        if command == [*prefix, "/usr/bin/ss", "-H", "-ltnp"]:
            return self.tcp.encode()
        if command == [*prefix, "/usr/bin/ss", "-H", "-lxnp"]:
            return self.unix.encode()
        raise AssertionError(f"Unexpected command: {command}")


@pytest.fixture
def evidence(monkeypatch: pytest.MonkeyPatch) -> Evidence:
    return Evidence(monkeypatch)


def test_exact_privileged_readonly_probes(evidence: Evidence) -> None:
    control.require_local_control_only()
    assert evidence.calls == [
        ["docker", "context", "inspect", "--format={{json .Endpoints.docker.Host}}"],
        ["/usr/bin/sudo", "-n", "/usr/bin/ss", "-H", "-ltnp"],
        ["/usr/bin/sudo", "-n", "/usr/bin/ss", "-H", "-lxnp"],
    ]


def test_existing_root_reads_directly(evidence: Evidence, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    control.require_local_control_only()
    assert evidence.calls[1:] == [["/usr/bin/ss", "-H", "-ltnp"], ["/usr/bin/ss", "-H", "-lxnp"]]


@pytest.mark.parametrize(
    "selector", ["DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY"]
)
def test_docker_selector_refused_before_probe(
    evidence: Evidence, monkeypatch: pytest.MonkeyPatch, selector: str
) -> None:
    monkeypatch.setenv(selector, "untrusted")
    with pytest.raises(control.ControlExposureRefused, match="exposure_unverified"):
        control.require_local_control_only()
    assert not evidence.calls


@pytest.mark.parametrize(
    "endpoint", ["tcp://127.0.0.1:2375", "ssh://host", "unix:///tmp/docker.sock", "", None]
)
def test_nonlocal_or_unknown_context_refused(evidence: Evidence, endpoint: object) -> None:
    evidence.endpoint = endpoint
    with pytest.raises(control.ControlExposureRefused):
        control.require_local_control_only()
    assert len(evidence.calls) == 1


@pytest.mark.parametrize("failure", ["wrong_target", "not_socket", "missing"])
def test_unix_path_must_be_existing_canonical_socket(
    evidence: Evidence, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    if failure == "wrong_target":
        monkeypatch.setattr(Path, "resolve", lambda self, strict=False: Path("/tmp/other.sock"))
    elif failure == "not_socket":
        monkeypatch.setattr(Path, "is_socket", lambda self: False)
    else:

        def missing(self: Path, strict: bool = False) -> Path:
            raise FileNotFoundError

        monkeypatch.setattr(Path, "resolve", missing)
    with pytest.raises(control.ControlExposureRefused):
        control.require_local_control_only()
    assert len(evidence.calls) == 1


@pytest.mark.parametrize("address", ["127.0.0.1:2375", "0.0.0.0:443", "[::]:2376", "[::1]:65432"])
def test_dockerd_tcp_on_any_address_or_port_refused(evidence: Evidence, address: str) -> None:
    evidence.tcp = f'LISTEN 0 128 {address} *:* users:(("dockerd",pid=42,fd=9))\n'
    with pytest.raises(control.ControlExposureRefused):
        control.require_local_control_only()


@pytest.mark.parametrize(
    "tcp",
    [
        "LISTEN 0 128 127.0.0.1:1234 *:*\n",
        'LISTEN 0 128 127.0.0.1:1234 *:* users:(("dockerd",pid=0,fd=3))\n',
        'LISTEN 0 128 127.0.0.1:1234 *:* users:(("dockerd",pid=x,fd=3))\n',
    ],
)
def test_missing_or_malformed_tcp_ownership_refused(evidence: Evidence, tcp: str) -> None:
    evidence.tcp = tcp
    with pytest.raises(control.ControlExposureRefused):
        control.require_local_control_only()


@pytest.mark.parametrize(
    "unix",
    [
        "",
        UNIX * 2,
        UNIX.replace('"dockerd"', '"other"'),
        UNIX.replace('"dockerd"', '"systemd"'),
        UNIX.replace("u_str LISTEN", "u_dgr UNCONN"),
        UNIX.replace("/run/docker.sock", "/tmp/run/docker.sock"),
        UNIX.replace('users:(("dockerd",pid=42,fd=3))', ""),
        UNIX.replace("fd=3))", 'fd=3),("other",pid=44,fd=4))'),
        UNIX.replace("fd=3))", 'fd=3),("dockerd",pid=42,fd=4))'),
    ],
)
def test_ambiguous_or_unowned_unix_listener_refused(evidence: Evidence, unix: str) -> None:
    evidence.unix = unix
    with pytest.raises(control.ControlExposureRefused):
        control.require_local_control_only()


def test_systemd_and_daemon_shared_listener_accepted(evidence: Evidence) -> None:
    evidence.unix = UNIX.replace("fd=3))", 'fd=3),("systemd",pid=1,fd=4))')
    control.require_local_control_only()


def test_empty_tcp_evidence_with_owned_unix_listener_accepted(evidence: Evidence) -> None:
    evidence.tcp = ""
    evidence.endpoint = "unix:///run/docker.sock"
    control.require_local_control_only()


def test_probe_error_redacted_and_fail_closed(
    evidence: Evidence, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(command: list[str]) -> bytes:
        raise RuntimeError("private process details")

    monkeypatch.setattr(control, "read_control", fail)
    with pytest.raises(control.ControlExposureRefused) as caught:
        control.require_local_control_only()
    assert str(caught.value) == "service_control_exposure_unverified"
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("length,success", [(0, True), (65536, True), (65537, False)])
def test_read_control_output_ceiling(
    monkeypatch: pytest.MonkeyPatch, length: int, success: bool
) -> None:
    calls: list[tuple[list[str], bytes, float]] = []

    def exchange(command: list[str], data: bytes, timeout: float) -> bytes:
        calls.append((command, data, timeout))
        return b"x" * length

    monkeypatch.setattr(control, "exchange", exchange)
    command = ["fixed-test-command"]
    if success:
        assert control.read_control(command) == b"x" * length
    else:
        with pytest.raises(control.ControlExposureRefused):
            control.read_control(command)
    assert calls == [(command, b"", 5)]


def test_read_control_timeout_redacts_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    def exchange(command: list[str], data: bytes, timeout: float) -> bytes:
        raise TimeoutError("private listener details")

    monkeypatch.setattr(control, "exchange", exchange)
    with pytest.raises(control.ControlExposureRefused) as caught:
        control.read_control(["fixed-test-command"])
    assert str(caught.value) == "service_control_exposure_unverified"

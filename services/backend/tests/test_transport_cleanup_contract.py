"""Pure owned-control and daemon-timeout regressions; no Docker/network calls."""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest
import transport_topology as topology_module
from transport_fixture import State, fixture_command
from transport_topology import (
    OWNER_LABEL,
    Topology,
    baseline_diagnostic,
    check_host_ipv6_forwarding,
    remove_owned,
)


@pytest.mark.parametrize("name", ["all", "default"])
@pytest.mark.parametrize("invalid", ["0\n", "2\n", "", "unknown", "1\n0\n"])
def test_existing_forwarding_requires_both_exact_enabled_values(
    monkeypatch: pytest.MonkeyPatch, name: str, invalid: str
) -> None:
    def read(path: Path, **kwargs: object) -> str:
        assert str(path) in {
            "/proc/sys/net/ipv6/conf/all/forwarding",
            "/proc/sys/net/ipv6/conf/default/forwarding",
        }
        return invalid if path.parent.name == name else "1\n"

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(RuntimeError, match="Unsupported runner"):
        check_host_ipv6_forwarding()


def test_existing_forwarding_is_read_only_and_missing_evidence_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[str] = []

    def read(path: Path, **kwargs: object) -> str:
        reads.append(str(path))
        return "1\n"

    monkeypatch.setattr(Path, "read_text", read)
    check_host_ipv6_forwarding()
    assert reads == [
        "/proc/sys/net/ipv6/conf/all/forwarding",
        "/proc/sys/net/ipv6/conf/default/forwarding",
    ]

    def missing(path: Path, **kwargs: object) -> str:
        raise OSError("Synthetic missing evidence")

    monkeypatch.setattr(Path, "read_text", missing)
    with pytest.raises(RuntimeError, match="cannot be verified"):
        check_host_ipv6_forwarding()


def test_preflight_refuses_before_any_daemon_or_build_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse() -> None:
        raise RuntimeError("Synthetic unsupported forwarding")

    def unexpected(*args: object, **kwargs: object) -> object:
        pytest.fail("Daemon/build called before forwarding preflight")

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(topology_module, "check_host_ipv6_forwarding", refuse)
    monkeypatch.setattr(topology_module, "check_daemon", unexpected)
    monkeypatch.setattr(topology_module, "docker", unexpected)
    monkeypatch.setattr(Topology, "_build", unexpected)
    with pytest.raises(RuntimeError, match="Synthetic unsupported"):
        Topology()
    value = shell(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="Synthetic unsupported"):
            value.start()
        assert not value.network_created
    finally:
        value.directory.cleanup()


def test_forwarding_is_rechecked_after_build_before_network_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = shell(tmp_path)
    calls: list[str] = []

    def preflight() -> None:
        calls.append("preflight")
        if len(calls) > 1:
            raise RuntimeError("Synthetic forwarding changed while building")

    def built(*args: object) -> None:
        calls.append("build")

    def unexpected(*args: object, **kwargs: object) -> object:
        pytest.fail("Network created after unsupported forwarding")

    monkeypatch.setattr(topology_module, "check_host_ipv6_forwarding", preflight)
    monkeypatch.setattr(Topology, "_build", built)
    monkeypatch.setattr(topology_module, "docker", unexpected)
    try:
        with pytest.raises(RuntimeError, match="changed while building"):
            value.start()
        assert calls == ["preflight", "build", "preflight"] and not value.network_created
    finally:
        value.directory.cleanup()


def test_baseline_diagnostic_distinguishes_order_and_actual_field_changes() -> None:
    before: dict[str, object] = {"routes": [{"dst": "default"}, {"dst": "127.0.0.1"}]}
    reordered: dict[str, object] = {"routes": [{"dst": "127.0.0.1"}, {"dst": "default"}]}
    order = json.loads(baseline_diagnostic(before, reordered))["host_baseline_difference"]
    assert order["routes"]["order_only"] and before != reordered
    changed: dict[str, object] = {"routes": [{"dst": "default", "gateway": "192.0.2.1"}]}
    fields = json.loads(baseline_diagnostic(before, changed))["host_baseline_difference"]
    assert not fields["routes"]["order_only"]
    assert fields["routes"]["removed_count"] == 2
    assert fields["routes"]["added_count"] == 1
    assert "192.0.2.1" in fields["routes"]["added"][0]
    assert before != changed


def test_baseline_diagnostic_is_bounded_and_retains_duplicate_counts() -> None:
    before: dict[str, object] = {"routes": [{"dst": "x" * 20000}] * 100}
    after: dict[str, object] = {"routes": []}
    diagnostic = baseline_diagnostic(before, after)
    section = json.loads(diagnostic)["host_baseline_difference"]["routes"]
    assert len(diagnostic) < 16384 and section["removed_count"] == 100
    assert len(section["removed"]) == 4
    assert all(len(row) <= 512 for row in section["removed"])


@pytest.mark.parametrize("kind", ["snapshot", "inspect", "stop"])
def test_fixture_all_owned_control_commands_dispatch(kind: str) -> None:
    state = State("redirect", 2)
    calls: list[dict[str, object]] = [{"synthetic": True}]
    queries: list[dict[str, object]] = [{"kind": 1}]
    probes: list[bool] = []

    def inspect() -> dict[str, Any]:
        probes.append(True)
        return {"synthetic_probe_contract": True}

    result, finished = fixture_command({"kind": kind}, state, calls, queries, [], inspect)
    assert (
        result["kind"] == {"snapshot": "snapshot", "inspect": "inspected", "stop": "stopped"}[kind]
    )
    assert finished == (kind == "stop")
    assert bool(probes) == (kind == "inspect")
    assert calls and queries and state.mode == "redirect"


def test_fixture_mode_reset_is_bounded_and_inspection_is_not_reset() -> None:
    state = State("redirect", 9)
    calls: list[dict[str, object]] = [{"synthetic": True}]
    queries: list[dict[str, object]] = [{"kind": 1}]
    assert fixture_command({"mode": "normal"}, state, calls, queries, [], lambda: {}) == (
        {"kind": "configured"},
        False,
    )
    assert state == State() and calls == queries == []


def test_fixture_refuses_unknown_control_or_extra_fields() -> None:
    values: list[object] = [
        {"kind": "snapshot", "mode": "private"},
        {"mode": "unknown"},
        [],
        {"kind": "reset"},
    ]
    for value in values:
        with pytest.raises(RuntimeError):
            fixture_command(value, State(), [], [], [], lambda: {})


class Daemon:
    def __init__(self, owner: str, fail: str) -> None:
        self.owner, self.fail = owner, fail
        self.values: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls: list[tuple[str, ...]] = []

    def call(
        self, *args: str, timeout: float = 120, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if len(args) >= 3 and args[1] == "inspect":
            value = self.values.get((args[0], args[2]))
            return subprocess.CompletedProcess(
                list(args),
                0 if value else 1,
                json.dumps([value]) if value else "[]",
                "" if value else "Error: No such object: " + args[2],
            )
        if args[:2] == ("network", "create"):
            self.values[("network", args[-1])] = {"Labels": {OWNER_LABEL: self.owner}}
            if self.fail == "network":
                raise subprocess.TimeoutExpired("docker network create", timeout)
            return subprocess.CompletedProcess(list(args), 0, "b" * 64, "")
        if args[0] == "create":
            name = next(value.split("=", 1)[1] for value in args if value.startswith("--name="))
            self.values[("container", name)] = {
                "Id": "a" * 64,
                "Config": {"Labels": {OWNER_LABEL: self.owner}},
            }
            raise subprocess.TimeoutExpired("docker create", timeout)
        if args[0] == "build":
            name = args[args.index("--tag") + 1]
            self.values[("image", name)] = {"Config": {"Labels": {OWNER_LABEL: self.owner}}}
            raise subprocess.TimeoutExpired("docker build", timeout)
        if args[0] == "rm":
            self.values.pop(("container", args[-1]))
        elif args[1] == "rm":
            self.values.pop((args[0], args[-1]))
        else:
            raise AssertionError("Unexpected mocked command")
        return subprocess.CompletedProcess(list(args), 0, "", "")


def shell(tmp_path: Path) -> Topology:
    value = Topology.__new__(Topology)
    value.owner = "test-owner"
    value.name, value.bridge, value.suffix = "owned", "owned0", "unit"
    value.identifiers, value.processes, value.container_names = {}, {}, {}
    value.images = []
    value.network_created = False
    value.browser_identifier = None
    value.directory = tempfile.TemporaryDirectory(dir=tmp_path)
    value.root = tmp_path
    value.baseline = {}
    return value


@pytest.mark.parametrize("failure", ["network", "container", "image"])
def test_creation_timeout_reconciles_only_exact_owned_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    value = shell(tmp_path)
    daemon = Daemon(value.owner, failure)
    monkeypatch.setattr(topology_module, "docker", daemon.call)
    monkeypatch.setattr(topology_module, "host_baseline", lambda: {})
    monkeypatch.setattr(topology_module, "check_host_ipv6_forwarding", lambda: None)

    def built(self: Topology, root: Path, directory: Path, suffix: str) -> None:
        self.images = ["fixture", "gateway"]
        for image in self.images:
            daemon.values[("image", image)] = {"Config": {"Labels": {OWNER_LABEL: self.owner}}}

    monkeypatch.setattr(Topology, "_build", built)
    with pytest.raises(subprocess.TimeoutExpired):
        if failure == "image":
            value._build_image("owned-image", tmp_path)
        else:
            value.start()
    value.close()
    assert daemon.values == {}
    assert any(
        (command[0] == "rm" or len(command) > 1 and command[1] == "rm") for command in daemon.calls
    )
    assert all("prune" not in command for command in daemon.calls)


def test_unknown_owner_is_preserved_and_absence_error_never_means_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon = Daemon("other-owner", "network")
    daemon.values[("network", "owned")] = {"Labels": {OWNER_LABEL: "other-owner"}}
    monkeypatch.setattr(topology_module, "docker", daemon.call)
    with pytest.raises(RuntimeError, match="unknown resource"):
        remove_owned("network", "owned", "test-owner")
    assert daemon.values and all(command[1] != "rm" for command in daemon.calls)

    def disconnected(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(args), 1, "", "Cannot connect to daemon")

    monkeypatch.setattr(topology_module, "docker", disconnected)
    with pytest.raises(RuntimeError, match="absence"):
        remove_owned("network", "owned", "test-owner")

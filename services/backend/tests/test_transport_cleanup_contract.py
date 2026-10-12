"""Pure owned-control and daemon-timeout regressions; no Docker/network calls."""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest
import transport_topology as topology_module
from transport_fixture import State, fixture_command
from transport_topology import OWNER_LABEL, Topology, remove_owned


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

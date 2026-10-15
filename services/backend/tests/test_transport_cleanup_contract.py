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
    monkeypatch.setattr(topology_module, "require_disposable_ci", refuse)
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


def test_forwarding_verification_fails_before_capture_or_network_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = shell(tmp_path)
    calls: list[str] = []

    def refuse() -> None:
        calls.append("verified")
        raise RuntimeError("Synthetic forwarding not established")

    monkeypatch.setattr(topology_module, "check_host_ipv6_forwarding", refuse)
    monkeypatch.setattr(topology_module, "host_baseline", lambda: pytest.fail("Premature capture"))
    try:
        with pytest.raises(RuntimeError, match="not established"):
            value._capture_baseline()
        assert value.baseline is None and not value.network_created and calls == ["verified"]
    finally:
        value.directory.cleanup()


@pytest.mark.parametrize("section", ["addresses", "routes", "rules"])
def test_protected_baseline_is_captured_only_once_and_repeated_start_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, section: str
) -> None:
    value = shell(tmp_path)
    expected: dict[str, object] = {section: [{"synthetic": True}]}
    monkeypatch.setattr(topology_module, "check_host_ipv6_forwarding", lambda: None)
    monkeypatch.setattr(topology_module, "require_disposable_ci", lambda: None)
    monkeypatch.setattr(topology_module, "host_baseline", lambda: expected)
    monkeypatch.setattr(Topology, "_build", lambda *args: pytest.fail("Repeated preparation"))
    try:
        value._capture_baseline()
        assert value.baseline == expected
        with pytest.raises(RuntimeError, match="cannot be recaptured"):
            value._capture_baseline()
        with pytest.raises(RuntimeError, match="already started"):
            value.start()
        assert value.baseline == expected and not value.network_created
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
    value.image_provenance = {}
    value.network_created = False
    value.browser_identifier = None
    value.directory = tempfile.TemporaryDirectory(dir=tmp_path)
    value.root = tmp_path
    value.preparation_baseline = {}
    value.baseline = None
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
    monkeypatch.setattr(topology_module, "require_disposable_ci", lambda: None)
    monkeypatch.setattr(topology_module, "initialize", lambda: None)

    def built(self: Topology, root: Path, directory: Path, suffix: str) -> None:
        self.images = ["fixture", "gateway", "browser"]
        for image in self.images:
            daemon.values[("image", image)] = {
                "Id": "sha256:" + "c" * 64,
                "Config": {"Labels": {OWNER_LABEL: self.owner}},
            }
            self.image_provenance[image] = {"image_id": "sha256:" + "c" * 64}

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


def test_trusted_preparation_initialization_capture_and_creation_are_ordered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    value = shell(tmp_path)
    order: list[str] = []
    metadata: dict[str, Any] = {
        "Id": "sha256:" + "c" * 64,
        "Config": {"Labels": {OWNER_LABEL: value.owner}},
    }

    def built(*args: object) -> None:
        order.append("build")
        value.images = ["fixture", "gateway", "browser"]
        value.image_provenance = {image: {"image_id": metadata["Id"]} for image in value.images}

    def initialized() -> None:
        order.append("initialize")

    def snapshot() -> dict[str, object]:
        order.append("snapshot")
        return {"routes": [{"synthetic_prepared_state": True}]}

    def create(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args[:2] == ("network", "create")
        order.append("network")
        raise subprocess.TimeoutExpired("synthetic creation boundary", 1)

    monkeypatch.setattr(topology_module, "require_disposable_ci", lambda: None)
    monkeypatch.setattr(Topology, "_build", built)
    monkeypatch.setattr(topology_module, "resource", lambda *args: metadata)
    monkeypatch.setattr(topology_module, "initialize", initialized)
    monkeypatch.setattr(topology_module, "host_baseline", snapshot)
    monkeypatch.setattr(
        topology_module, "check_host_ipv6_forwarding", lambda: order.append("verify")
    )
    monkeypatch.setattr(topology_module, "docker", create)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            value.start()
        assert order == ["build", "snapshot", "initialize", "verify", "snapshot", "network"]
        assert value.baseline == {"routes": [{"synthetic_prepared_state": True}]}
        output = capsys.readouterr().out
        assert "trusted_image_preparation_before_initialization" in output
        assert "owned_prepared_images" in output and "protected_baseline_digest" in output
    finally:
        value.directory.cleanup()


@pytest.mark.parametrize("problem", ["missing", "changed", "foreign_owner"])
def test_prepared_image_identity_and_ownership_are_rechecked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    value = shell(tmp_path)
    identifier = "sha256:" + "c" * 64
    value.image_provenance = {"prepared": {"image_id": identifier}}
    metadata: dict[str, Any] = {
        "Id": identifier,
        "Config": {"Labels": {OWNER_LABEL: value.owner}},
    }
    if problem == "changed":
        metadata["Id"] = "sha256:" + "d" * 64
    elif problem == "foreign_owner":
        metadata["Config"]["Labels"][OWNER_LABEL] = "other-owner"
    result = None if problem == "missing" else metadata
    monkeypatch.setattr(topology_module, "resource", lambda *args: result)
    try:
        with pytest.raises(RuntimeError):
            value._prepared_image("prepared")
    finally:
        value.directory.cleanup()


def test_protected_cleanup_drift_fails_without_recapturing_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = shell(tmp_path)
    value.baseline = {"routes": []}
    monkeypatch.setattr(topology_module, "host_baseline", lambda: {"routes": [{"changed": True}]})
    with pytest.raises(RuntimeError, match="baseline_cleanup"):
        value.close()
    assert value.baseline == {"routes": []}


def test_build_records_exact_owned_image_and_pinned_recipe_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    value = shell(tmp_path)
    recipe = b"FROM python:3.12@sha256:synthetic-unit-recipe\n"
    (tmp_path / "Dockerfile").write_bytes(recipe)
    identifier = "sha256:" + "c" * 64
    results = iter([None, {"Id": identifier, "Config": {"Labels": {OWNER_LABEL: value.owner}}}])
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(topology_module, "resource", lambda *args: next(results))

    def built(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(list(args), 0, "", "")

    monkeypatch.setattr(topology_module, "docker", built)
    try:
        value._build_image("prepared", tmp_path)
        assert value.images == ["prepared"]
        assert value.image_provenance["prepared"] == {
            "image_id": identifier,
            "dockerfile_sha256": hashlib.sha256(recipe).hexdigest(),
            "pinned_base": recipe.decode().strip(),
        }
        assert calls[0][0] == "build" and "--label=" + OWNER_LABEL + "=" + value.owner in calls[0]
    finally:
        value.directory.cleanup()


def test_fixture_delay_release_is_exact_owned_control_and_bounded() -> None:
    state = State()
    result, stopped = fixture_command({"mode": "slow"}, state, [], [], [], lambda: {})
    assert result == {"kind": "configured"} and not stopped and not state.release.is_set()
    result, stopped = fixture_command({"kind": "release"}, state, [], [], [], lambda: {})
    assert result == {"kind": "released"} and not stopped and state.release.is_set()
    with pytest.raises(RuntimeError):
        fixture_command({"kind": "release", "arbitrary_delay": 9999}, state, [], [], [], lambda: {})


class HeldFixture:
    def __init__(self, events: list[str], problem: str = "") -> None:
        self.events, self.problem = events, problem
        self.poisoned = problem == "poisoned"
        self.deadlines: list[float] = []

    def send(self, value: dict[str, object], deadline: float) -> None:
        assert value == {"kind": "release"} and not self.poisoned
        self.events.append("release_send")
        self.deadlines.append(deadline)
        if self.problem == "send":
            raise OSError("private-send-content")

    def receive(self, deadline: float) -> dict[str, object]:
        self.events.append("release_receive")
        self.deadlines.append(deadline)
        if self.problem == "receive":
            raise RuntimeError("private-receive-content")
        if self.problem == "release_timeout":
            raise TimeoutError("private-timeout-content")
        if self.problem == "wrong_ack":
            return {"kind": "released", "unexpected": "private-frame-content"}
        return {"kind": "released"}


class HeldResult:
    def __init__(self, events: list[str], problem: str = "") -> None:
        self.events, self.problem = events, problem

    def result(self, timeout: float | None = None) -> bytes:
        assert timeout == 20
        self.events.append("future_result")
        if self.problem == "future":
            raise RuntimeError("private-future-content")
        if self.problem == "future_timeout":
            raise TimeoutError("private-future-timeout-content")
        return b"unexpected body" if self.problem == "body" else b"synthetic marker"


def held_cleanup_case(
    monkeypatch: pytest.MonkeyPatch, problem: str = "", future_problem: str = ""
) -> tuple[Topology, HeldFixture, Any, list[str]]:
    from typing import cast

    from transport_rpc import OwnedProcess

    events: list[str] = []
    fixture = HeldFixture(events, problem)
    value = Topology.__new__(Topology)
    value.processes = {"fixture-a": cast(OwnedProcess, fixture)}
    pending = HeldResult(events, future_problem or problem)
    monkeypatch.setattr("transport_cleanup.time.monotonic", lambda: 100.0)
    return value, fixture, pending, events


def test_held_response_cleanup_runs_once_after_fairness_before_executor_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager

    from transport_cleanup import held_response_cleanup

    value, fixture, pending, events = held_cleanup_case(monkeypatch)

    @contextmanager
    def executor_scope() -> Iterator[None]:
        try:
            yield
        finally:
            events.append("executor_exit")

    with executor_scope(), held_response_cleanup(value, pending):
        assert events == []
        events.append("fairness_assertions")
    assert events == [
        "fairness_assertions",
        "release_send",
        "release_receive",
        "future_result",
        "executor_exit",
    ]
    assert fixture.deadlines == [105.0, 105.0] and not fixture.poisoned


@pytest.mark.parametrize("cancelled", [False, True])
def test_held_response_primary_failure_or_cancellation_is_preserved(
    monkeypatch: pytest.MonkeyPatch, cancelled: bool
) -> None:
    import asyncio

    from transport_cleanup import held_response_cleanup

    value, _, pending, events = held_cleanup_case(monkeypatch)
    primary = asyncio.CancelledError() if cancelled else AssertionError("primary-fairness")
    with pytest.raises(type(primary)) as observed, held_response_cleanup(value, pending):
        raise primary
    assert observed.value is primary
    assert not getattr(primary, "__notes__", [])
    assert events == ["release_send", "release_receive", "future_result"]


CLEANUP_FAILURES = [
    ("send", "release_send:OSError"),
    ("receive", "release_receive:RuntimeError"),
    ("release_timeout", "release_receive:TimeoutError"),
    ("wrong_ack", "release_acknowledgement:AssertionError"),
    ("poisoned", "fixture_poisoned:RuntimeError"),
    ("future", "future_result:RuntimeError"),
    ("future_timeout", "future_result:TimeoutError"),
    ("body", "future_body:AssertionError"),
]


@pytest.mark.parametrize(("problem", "note"), CLEANUP_FAILURES)
@pytest.mark.parametrize("has_primary", [False, True])
def test_held_response_cleanup_failures_never_retry_or_mask_primary(
    monkeypatch: pytest.MonkeyPatch, problem: str, note: str, has_primary: bool
) -> None:
    from transport_cleanup import held_response_cleanup

    value, fixture, pending, events = held_cleanup_case(monkeypatch, problem)
    primary = AssertionError("primary-fairness")
    with pytest.raises(Exception) as observed, held_response_cleanup(value, pending):
        if has_primary:
            raise primary
    error = observed.value
    assert (error is primary) == has_primary
    assert error.__notes__ == ["held_response_cleanup:" + note]
    assert all("private" not in item and len(item) < 100 for item in error.__notes__)
    assert events.count("release_send") == (0 if problem == "poisoned" else 1)
    assert events.count("release_receive") == (0 if problem in {"poisoned", "send"} else 1)
    assert events.count("future_result") == 1 and events[-1] == "future_result"
    assert fixture.poisoned == (problem in {row[0] for row in CLEANUP_FAILURES[:5]})


def test_held_response_collects_failed_future_even_after_uncertain_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from transport_cleanup import held_response_cleanup

    value, fixture, pending, events = held_cleanup_case(monkeypatch, "receive", "future")
    primary = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError) as observed, held_response_cleanup(value, pending):
        raise primary
    assert observed.value is primary and fixture.poisoned
    assert primary.__notes__ == [
        "held_response_cleanup:release_receive:RuntimeError",
        "held_response_cleanup:future_result:RuntimeError",
    ]
    assert events == ["release_send", "release_receive", "future_result"]


def test_held_response_poisoned_gateway_never_prevents_healthy_fixture_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import cast

    from transport_cleanup import held_response_cleanup
    from transport_rpc import OwnedProcess

    value, fixture, pending, events = held_cleanup_case(monkeypatch)
    gateway = HeldFixture([], "poisoned")
    other = HeldFixture([])
    value.processes.update(
        {"gateway": cast(OwnedProcess, gateway), "fixture-b": cast(OwnedProcess, other)}
    )
    with held_response_cleanup(value, pending):
        pass
    assert events == ["release_send", "release_receive", "future_result"]
    assert not fixture.poisoned and gateway.poisoned
    assert not gateway.events and not other.events


def test_actual_held_request_is_guarded_inside_executor_before_all_fairness_assertions() -> None:
    import ast

    path = Path(__file__).resolve().parents[3] / "scripts/isolation/test_transport_acceptance.py"
    module = ast.parse(path.read_text())
    case = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_actual_blocked_source")
    )
    executor = next(node for node in case.body if isinstance(node, ast.With))
    assert ast.unparse(executor.items[0].context_expr) == "ThreadPoolExecutor(max_workers=1)"
    assert len(executor.body) == 2 and isinstance(executor.body[0], ast.Assign)
    cleanup = executor.body[1]
    assert isinstance(cleanup, ast.With)
    assert ast.unparse(cleanup.items[0].context_expr) == "held_response_cleanup(topology, pending)"
    body = ast.unparse(cleanup)
    assert "wait_for_held_receipt(topology, pending, deadline)" in body
    assert "resource.active_units['http'] == 1" in body
    assert "run_until_terminal(other, other_org, job)" in body
    assert "results.download(other_org, export.id).body" in body
    assert ast.unparse(cleanup.body[-1]) == "assert not pending.done()"
    assert body.count("assert not pending.done()") == 2
    assert "release" not in body and "pending.result" not in body


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
def test_terminal_held_future_is_collected_once_by_cleanup_after_receipt_failure(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    import time
    from concurrent.futures import CancelledError, Future
    from typing import cast

    from test_admission_acceptance_contract import helper
    from transport_cleanup import held_response_cleanup

    value, _, _, events = held_cleanup_case(monkeypatch)
    primary: list[BaseException] = []
    stored_failure = RuntimeError("original-fetch-failure")

    class CountingFuture(Future[bytes]):
        def result(self, timeout: float | None = None) -> bytes:
            assert timeout == 20
            events.append("future_result")
            return super().result(timeout)

        def exception(self, timeout: float | None = None) -> BaseException | None:
            assert timeout == 0
            events.append("future_exception")
            return super().exception(timeout)

    pending = CountingFuture()
    if outcome == "success":
        pending.set_result(b"synthetic marker")
    elif outcome == "failure":
        pending.set_exception(stored_failure)
    else:
        assert pending.cancel()

    def snapshot(topology: object) -> object:
        pytest.fail("Terminal fetch must not consume fixture control frames")

    wait = helper(
        "wait_for_held_receipt", {"time": time, "snapshot": snapshot, "cast": cast, "Any": Any}
    )
    expected = {"success": AssertionError, "failure": RuntimeError, "cancelled": CancelledError}
    with pytest.raises(expected[outcome]) as observed, held_response_cleanup(value, pending):
        try:
            wait(value, pending, 110)
        except BaseException as error:
            primary.append(error)
            raise
    assert observed.value is primary[0]
    if outcome == "failure":
        assert observed.value is stored_failure
    elif outcome == "success":
        assert str(observed.value) == "Synthetic response completed before held receipt"
    assert events == ["future_exception", "release_send", "release_receive", "future_result"]

"""Owned pipe concurrency and failure cleanup; actual worker/UI proof is separate CI."""

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from operator_provider_worker import PipeOwner
from transport_rpc import OwnedProcess

ROOT = Path(__file__).resolve().parents[3]


def fixture() -> tuple[PipeOwner, list[object]]:
    calls: list[object] = []

    def send(value: object, deadline: float) -> None:
        calls.append((value, deadline))

    def receive(deadline: float) -> dict[str, Any]:
        calls.append(deadline)
        return {"kind": "owned"}

    pipe = PipeOwner(
        cast(OwnedProcess, SimpleNamespace(poisoned=False, send=send, receive=receive))
    )
    pipe.owner = threading.get_ident()
    return pipe, calls


@pytest.mark.parametrize("method", ["send", "receive"])
@pytest.mark.parametrize("invalid", ["unbound", "foreign", "revoked"])
def test_pipe_rejects_unowned_or_revoked_io(method: str, invalid: str) -> None:
    pipe, calls = fixture()
    if invalid == "unbound":
        pipe.owner = None
    elif invalid == "foreign":
        pipe.owner = threading.get_ident() + 1
    else:
        pipe.revoke()
    with pytest.raises(RuntimeError, match="ownership refused"):
        if method == "send":
            pipe.send({"kind": "owned"}, time.monotonic() + 5)
        else:
            pipe.receive(time.monotonic() + 5)
    assert calls == []


@pytest.mark.parametrize("method", ["send", "receive"])
def test_owned_io_preserves_tighter_deadline_and_caps_larger_one(method: str) -> None:
    pipe, calls = fixture()
    now = time.monotonic()
    for deadline in (now + 1, now + 200):
        if method == "send":
            pipe.send({"kind": "owned"}, deadline)
        else:
            assert pipe.receive(deadline) == {"kind": "owned"}
    deadlines = [entry[1] if isinstance(entry, tuple) else entry for entry in calls]
    assert deadlines[0] == now + 1
    assert isinstance(deadlines[1], float) and now + 20 <= deadlines[1] < now + 21


@pytest.mark.parametrize("active", [False, True])
def test_revocation_is_idempotent_and_poisons_only_interrupted_protocol(active: bool) -> None:
    pipe, _ = fixture()
    pipe.active = active
    pipe.revoke()
    pipe.revoke()
    assert pipe.closed.is_set() and pipe.poisoned is active


def test_revocation_waits_for_current_io_but_refuses_late_callback() -> None:
    entered, release, revoked = threading.Event(), threading.Event(), threading.Event()
    calls: list[str] = []
    failures: list[str] = []

    def receive(deadline: float) -> dict[str, Any]:
        entered.set()
        assert release.wait(timeout=3)
        calls.append("receive")
        return {"kind": "owned"}

    pipe = PipeOwner(cast(OwnedProcess, SimpleNamespace(poisoned=False, receive=receive)))
    pipe.active = True

    def worker() -> None:
        pipe.owner = threading.get_ident()
        pipe.receive(time.monotonic() + 3)
        assert revoked.wait(timeout=3)
        try:
            pipe.receive(time.monotonic() + 3)
        except RuntimeError:
            failures.append("late callback refused")

    def closer() -> None:
        pipe.revoke()
        revoked.set()

    thread = threading.Thread(target=worker)
    cleanup = threading.Thread(target=closer)
    thread.start()
    try:
        assert entered.wait(timeout=3)
        cleanup.start()
        assert pipe.closed.wait(timeout=3)
        assert not revoked.is_set()
        release.set()
        assert revoked.wait(timeout=3)
    finally:
        release.set()
        thread.join(timeout=3)
        if cleanup.ident is not None:
            cleanup.join(timeout=3)
    assert not thread.is_alive() and not cleanup.is_alive()
    assert calls == ["receive"] and failures == ["late callback refused"] and pipe.poisoned


def test_worker_and_ui_keep_separate_bounded_controls_and_isolation() -> None:
    helper = (ROOT / "scripts/isolation/operator_provider_worker.py").read_text()
    static = (ROOT / "scripts/isolation/test_operator_ui_acceptance.py").read_text()
    guest = (ROOT / "scripts/isolation/operator_ui_acceptance.py").read_text()
    workflow = (ROOT / ".github/workflows/transport-isolation.yml").read_text()
    actual = (ROOT / "scripts/isolation/test_operator_provider_acceptance.py").read_text()
    assert "ready.wait(20)" in helper and "thread.join(timeout=150)" in helper
    assert helper.index("pipe.revoke()") < helper.index("thread.join(timeout=150)")
    assert 'pool="solo"' in helper and "app.WorkController(" in helper
    assert "wait_for(complete, seconds=8)" in static
    assert "RPC_DEADLINE = 10.0" in guest and "timeout=75000" in guest
    assert "test_operator_provider_acceptance.py" in workflow
    assert "EM_REQUIRE_REAL_BROKER" in workflow and "EM_REQUIRE_CONTROLLED_NETWORK" in workflow
    assert "consumer_count > 0" in actual and "for q in owned_queues(cfg.queue)" in actual
    assert '"/policies"' in actual and '"/policy-state"' in actual
    assert '"fetch_xml"' in actual
    assert "journey.process(" not in actual and "claim(progress" not in actual

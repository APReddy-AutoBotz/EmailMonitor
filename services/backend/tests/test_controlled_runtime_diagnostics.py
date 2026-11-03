"""Supervisor-only constant-size telemetry; no payload values become diagnostics."""

import dataclasses
import os
import struct
import time
from typing import Any, cast

import pytest
from emailmonitor.runtime.controlled_diagnostics import (
    CallbackKind,
    DiagnosticTracker,
    Failure,
    Origin,
    Phase,
)
from emailmonitor.runtime.controlled_launcher import OwnedWorker, _Relay
from emailmonitor.runtime.controlled_pipes import FramedPipes
from test_controlled_runtime_channel import boundary


def pipes(tracker: DiagnosticTracker) -> tuple[FramedPipes, int, int]:
    incoming, peer_write = os.pipe()
    peer_read, outgoing = os.pipe()
    return FramedPipes(incoming, outgoing, diagnostics=tracker), peer_read, peer_write


def test_snapshot_is_immutable_bounded_and_first_failure_survives_cleanup() -> None:
    tracker = DiagnosticTracker()
    tracker.phase(Phase.CALLBACK_WAIT, CallbackKind.CURRENT)
    for _ in range(1000):
        tracker.count("sent")
    tracker.fail(Failure.TIMEOUT, Origin.PIPE)
    observed = tracker.snapshot
    tracker.phase(Phase.IDLE, CallbackKind.NONE)
    tracker.count("received")
    tracker.fail(Failure.ALREADY_POISONED, Origin.PIPE)
    tracker.fail(Failure.WORKER_EXIT, Origin.WORKER)
    assert tracker.snapshot is observed
    assert observed.callback_sent == 128 and observed.callback_received == 0
    assert observed.phase is Phase.CALLBACK_WAIT and observed.failure is Failure.TIMEOUT
    with pytest.raises(dataclasses.FrozenInstanceError):
        cast(Any, observed).failure = Failure.EOF
    assert set(dataclasses.asdict(observed)) == {
        "phase",
        "origin",
        "failure",
        "callback_kind",
        "callback_sent",
        "callback_received",
        "callback_validated",
        "last_completed_kind",
        "worker_elapsed_bucket",
        "supervisor_roundtrip_bucket",
        "initial_acquire_remaining_bucket",
    }


@pytest.mark.parametrize(
    "fault", ["timeout", "eof", "framing", "read", "write", "already_poisoned", "stderr_limit"]
)
def test_transport_failure_classified_at_origin_without_raw_payload(fault: str) -> None:
    tracker = DiagnosticTracker()
    tracker.phase(Phase.CALLBACK_WAIT, CallbackKind.CURRENT)
    pipe, reader, writer = pipes(tracker)
    extra: list[int] = []
    sentinel = "private payload never enters telemetry"
    try:
        if fault == "eof":
            os.close(writer)
            writer = -1
        elif fault == "framing":
            raw = (sentinel + "{").encode()
            os.write(writer, struct.pack("!I", len(raw)) + raw)
        elif fault == "read":
            os.close(pipe.incoming)
        elif fault == "write":
            os.close(reader)
            reader = -1
        elif fault == "already_poisoned":
            pipe.poisoned = True
        elif fault == "stderr_limit":
            error_read, error_write = os.pipe()
            pipe.errors = error_read
            extra.append(error_write)
            os.write(error_write, b"x" * 4097)
        with pytest.raises(RuntimeError, match="^Controlled pipe failed$"):
            if fault == "write":
                pipe.send({"payload": sentinel}, time.monotonic() + 1)
            else:
                pipe.receive(time.monotonic() + (0.001 if fault == "timeout" else 1))
        assert pipe.poisoned
        assert tracker.snapshot.failure.value == fault
        assert tracker.snapshot.origin is Origin.PIPE
        assert sentinel not in repr(tracker.snapshot)
        first = tracker.snapshot
        with pytest.raises(RuntimeError):
            pipe.receive(time.monotonic() + 1)
        assert tracker.snapshot is first
    finally:
        pipe.close()
        for descriptor in (reader, writer, *extra):
            if descriptor >= 0:
                os.close(descriptor)


@pytest.mark.parametrize("kind", ["current", "resource_acquire", "resource_finish"])
def test_callback_sent_received_and_validated_are_separate(kind: str) -> None:
    tracker = DiagnosticTracker()
    bound = boundary()

    class Pipe:
        def send(self, value: dict[str, object], deadline: float) -> None:
            assert tracker.snapshot.phase is Phase.CALLBACK_SEND
            assert tracker.snapshot.callback_kind is CallbackKind(kind)

        def receive(self, deadline: float) -> dict[str, object]:
            assert tracker.snapshot.phase is Phase.CALLBACK_WAIT
            assert tracker.snapshot.callback_sent == 1
            return {
                "kind": "callback",
                "id": "fixed",
                "sequence": 0,
                "ok": True,
                "elapsed_bucket": "lt_1ms",
                "initial_acquire_remaining_bucket": "lt_20s",
            }

    relay = _Relay(cast(Any, Pipe()), "fixed", bound.binding, tracker)
    relay.callback(kind, {})
    assert tracker.snapshot.phase is Phase.ACQUIRE_PROVIDER
    assert (
        tracker.snapshot.callback_sent,
        tracker.snapshot.callback_received,
        tracker.snapshot.callback_validated,
    ) == (1, 1, 1)


def test_invalid_callback_records_fixed_origin_without_untrusted_reply() -> None:
    tracker = DiagnosticTracker()

    class Pipe:
        def send(self, value: dict[str, object], deadline: float) -> None:
            pass

        def receive(self, deadline: float) -> dict[str, object]:
            return {"payload": "private reply content"}

    relay = _Relay(cast(Any, Pipe()), "fixed", boundary().binding, tracker)
    with pytest.raises(RuntimeError, match="^Controlled callback failed$"):
        relay.current()
    assert tracker.snapshot.phase is Phase.CALLBACK_RETURN
    assert tracker.snapshot.failure is Failure.FRAMING
    assert tracker.snapshot.origin is Origin.CALLBACK
    assert tracker.snapshot.callback_received == 1 and tracker.snapshot.callback_validated == 0
    assert "private reply" not in repr(tracker.snapshot)


def test_worker_snapshot_property_is_read_only_and_does_no_io() -> None:
    class NoIO:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError("Snapshot must never inspect the worker")

    owned = OwnedWorker("b" * 64, cast(Any, NoIO()))
    assert owned.diagnostic_snapshot.phase is Phase.IDLE
    with pytest.raises(AttributeError):
        cast(Any, owned).diagnostic_snapshot = "private replacement"


def test_tracker_rejects_payload_strings_as_enums() -> None:
    tracker = DiagnosticTracker()
    with pytest.raises(TypeError):
        tracker.phase(cast(Any, "private payload"))
    with pytest.raises(TypeError):
        tracker.fail(cast(Any, "private payload"), Origin.PIPE)
    with pytest.raises(ValueError):
        tracker.count("private payload")
    assert "private" not in repr(tracker.snapshot)

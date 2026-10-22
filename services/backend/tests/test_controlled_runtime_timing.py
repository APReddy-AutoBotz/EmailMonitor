"""Bounded timing observations never become authority or raw-duration telemetry."""

import base64
import hashlib
import math
import socket
from types import SimpleNamespace
from typing import Any, cast

import pytest
from emailmonitor.runtime import controlled_channel, controlled_launcher
from emailmonitor.runtime.controlled_channel import ControlledChannel
from emailmonitor.runtime.controlled_diagnostics import (
    CallbackKind,
    DiagnosticTracker,
    ElapsedBucket,
    Failure,
    Origin,
    bucket_elapsed,
)
from emailmonitor.runtime.controlled_launcher import _Relay
from test_controlled_runtime_channel import BODY, Resources, boundary


@pytest.mark.parametrize(
    "limit,below,at",
    [
        (0.001, ElapsedBucket.LT_1MS, ElapsedBucket.LT_10MS),
        (0.01, ElapsedBucket.LT_10MS, ElapsedBucket.LT_100MS),
        (0.1, ElapsedBucket.LT_100MS, ElapsedBucket.LT_1S),
        (1.0, ElapsedBucket.LT_1S, ElapsedBucket.LT_5S),
        (5.0, ElapsedBucket.LT_5S, ElapsedBucket.LT_20S),
        (20.0, ElapsedBucket.LT_20S, ElapsedBucket.GE_20S),
    ],
)
def test_bucket_exact_boundaries(limit: float, below: ElapsedBucket, at: ElapsedBucket) -> None:
    assert bucket_elapsed(math.nextafter(limit, 0)) is below
    assert bucket_elapsed(limit) is at
    assert bucket_elapsed(0) is ElapsedBucket.LT_1MS


@pytest.mark.parametrize("value", [True, False, -1, math.nan, math.inf, -math.inf, "secret", None])
def test_bucket_refuses_nonfinite_negative_or_untyped_input(value: Any) -> None:
    with pytest.raises(ValueError, match="^Finite nonnegative elapsed time required$"):
        bucket_elapsed(value)


def completed(tracker: DiagnosticTracker) -> None:
    tracker.completed(
        CallbackKind.CURRENT, ElapsedBucket.LT_1MS, ElapsedBucket.LT_100MS, ElapsedBucket.LT_20S
    )


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("invalid", ["private raw timing", None, True])
def test_completed_fields_reject_invalid_atomically(index: int, invalid: Any) -> None:
    tracker = DiagnosticTracker()
    completed(tracker)
    first = tracker.snapshot
    args: list[Any] = [
        CallbackKind.RESOURCE_ACQUIRE,
        ElapsedBucket.LT_10MS,
        ElapsedBucket.LT_1S,
        ElapsedBucket.LT_5S,
    ]
    args[index] = invalid
    with pytest.raises(TypeError):
        tracker.completed(*args)
    assert tracker.snapshot is first
    assert "private" not in repr(first)


def test_completed_unknown_refused_and_first_failure_freezes_all_buckets() -> None:
    tracker = DiagnosticTracker()
    completed(tracker)
    for index in range(4):
        args: list[Any] = [
            CallbackKind.CURRENT,
            ElapsedBucket.LT_1MS,
            ElapsedBucket.LT_100MS,
            ElapsedBucket.LT_20S,
        ]
        args[index] = CallbackKind.NONE if index == 0 else ElapsedBucket.UNKNOWN
        with pytest.raises(TypeError):
            tracker.completed(*args)
    tracker.fail(Failure.TIMEOUT, Origin.PIPE)
    first = tracker.snapshot
    tracker.completed(
        CallbackKind.RESOURCE_FINISH,
        ElapsedBucket.GE_20S,
        ElapsedBucket.GE_20S,
        ElapsedBucket.LT_1MS,
    )
    assert tracker.snapshot is first
    assert first.last_completed_kind is CallbackKind.CURRENT


@pytest.mark.parametrize("field", ["elapsed_bucket", "initial_acquire_remaining_bucket"])
@pytest.mark.parametrize("invalid", ["unknown", "secret", 0, True, None, ElapsedBucket.LT_1MS])
def test_relay_rejects_malformed_timing_without_replacing_last_completed(
    field: str,
    invalid: Any,
) -> None:
    tracker = DiagnosticTracker()
    completed(tracker)
    prior = tracker.snapshot

    class Pipe:
        def send(self, value: Any, deadline: float) -> None:
            pass

        def receive(self, deadline: float) -> dict[str, Any]:
            return {
                "kind": "callback",
                "id": "fixed",
                "sequence": 0,
                "ok": True,
                "elapsed_bucket": "lt_1ms",
                "initial_acquire_remaining_bucket": "lt_20s",
                **{field: invalid},
            }

    relay = _Relay(cast(Any, Pipe()), "fixed", boundary().binding, tracker)
    with pytest.raises(RuntimeError, match="^Controlled callback failed$"):
        relay.current()
    after = tracker.snapshot
    assert after.failure is Failure.FRAMING
    assert after.callback_validated == 0
    assert (
        after.last_completed_kind,
        after.worker_elapsed_bucket,
        after.supervisor_roundtrip_bucket,
        after.initial_acquire_remaining_bucket,
    ) == (
        prior.last_completed_kind,
        prior.worker_elapsed_bucket,
        prior.supervisor_roundtrip_bucket,
        prior.initial_acquire_remaining_bucket,
    )
    assert "secret" not in repr(after)


def test_relay_measures_roundtrip_and_timeout_retains_last_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = DiagnosticTracker()
    bound = boundary()
    ticks = iter([10.0, 10.5, 11.0])
    monkeypatch.setattr(controlled_launcher, "time", SimpleNamespace(monotonic=lambda: next(ticks)))

    class Pipe:
        timeout = False

        def send(self, value: Any, deadline: float) -> None:
            assert deadline == bound.binding.deadline

        def receive(self, deadline: float) -> dict[str, Any]:
            if self.timeout:
                tracker.fail(Failure.TIMEOUT, Origin.PIPE)
                raise RuntimeError("Controlled pipe failed")
            return {
                "kind": "callback",
                "id": "fixed",
                "sequence": 0,
                "ok": True,
                "elapsed_bucket": "lt_10ms",
                "initial_acquire_remaining_bucket": "lt_5s",
            }

    pipe = Pipe()
    relay = _Relay(cast(Any, pipe), "fixed", bound.binding, tracker)
    relay.current()
    assert tracker.snapshot.supervisor_roundtrip_bucket is ElapsedBucket.LT_1S
    pipe.timeout = True
    with pytest.raises(RuntimeError):
        relay.callback("resource_acquire", {})
    assert tracker.snapshot.last_completed_kind is CallbackKind.CURRENT
    assert tracker.snapshot.worker_elapsed_bucket is ElapsedBucket.LT_10MS
    assert tracker.snapshot.callback_sent == 2
    assert tracker.snapshot.callback_validated == 1


def test_worker_scripted_elapsed_and_initial_budget_repeat_without_deadline_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound = boundary()
    start = bound.binding.deadline - 10
    ticks = iter(
        [start, start, start + 1, start + 1.005, start + 3, start + 3.5, start + 5, start + 7]
    )
    monkeypatch.setattr(controlled_channel, "time", SimpleNamespace(monotonic=lambda: next(ticks)))

    class Pipe:
        poisoned = False
        sent: list[dict[str, Any]] = []
        sequence = 0

        def send(self, value: dict[str, Any], deadline: float) -> None:
            assert deadline == bound.binding.deadline
            self.sent.append(value)

        def receive(self, deadline: float) -> dict[str, Any]:
            assert deadline == bound.binding.deadline
            identifier = self.sent[0]["id"]
            sequence = self.sequence
            self.sequence += 1
            if sequence == 3:
                return {
                    "kind": "acquired",
                    "id": identifier,
                    "body": base64.b64encode(BODY).decode(),
                    "digest": hashlib.sha256(BODY).hexdigest(),
                }
            return {
                "kind": ("current", "resource_acquire", "resource_finish")[sequence],
                "id": identifier,
                "sequence": sequence,
                "binding": bound.binding.model_dump(mode="json"),
                "arguments": (
                    {},
                    {
                        "url": bound.request.url,
                        "operation": bound.request.operation.value,
                        "deadline": bound.binding.deadline,
                    },
                    {"status": 200, "retry_after": ""},
                )[sequence],
            }

    left, right = socket.socketpair()
    channel = ControlledChannel(left)
    original = channel.pipe
    pipe = Pipe()
    channel.pipe = cast(Any, pipe)
    resources = Resources()
    try:
        assert channel.acquire(bound, resources=resources).body == BODY
        replies = pipe.sent[1:]
        assert [r["elapsed_bucket"] for r in replies] == ["lt_10ms", "lt_1s", "lt_5s"]
        assert [r["initial_acquire_remaining_bucket"] for r in replies] == ["lt_20s"] * 3
        assert resources.events == ["acquire", (200, "")]
        with pytest.raises(StopIteration):
            next(ticks)
    finally:
        original.close()
        right.close()

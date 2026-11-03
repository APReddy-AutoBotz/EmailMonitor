"""Diagnostic observation cannot alter admission results or lose cleanup ownership."""

import json
import time
from typing import Any

import operator_browser_timing as module
import pytest
from emailmonitor.fetching.fixture import HOSTS
from emailmonitor.fetching.safety import classify_url
from emailmonitor.sources.policy import Operation

URL = classify_url("https://synthetic.publisher.example/tooltip.html", HOSTS)


class Resources:
    def __init__(self) -> None:
        self.tickets: list[object] = []
        self.finished: list[tuple[object, int | None, str]] = []

    def acquire(self, *args: object) -> object:
        ticket = object()
        self.tickets.append(ticket)
        return ticket

    def finish(self, ticket: object, status: int | None, retry_after: str) -> None:
        self.finished.append((ticket, status, retry_after))


def test_two_admissions_and_receipts_keep_distinct_clock_intervals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter([10.0, 10.1, 15.2, 15.3])
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    delegate, timing = Resources(), module.BrowserTiming()
    rows = iter([{"attempts": 1, "admitted": 100.0}, {"attempts": 2, "admitted": 105.1}])
    observed = timing.resources(delegate, lambda ticket, deadline: next(rows))
    for _ in range(2):
        ticket = observed.acquire(URL, Operation.BROWSER, 20.0)
        assert ticket is delegate.tickets[-1]
        observed.finish(ticket, 200, "")
    receipt = timing.receipt([{"received_monotonic": 11.0}, {"received_monotonic": 15.84}])
    assert receipt["complete"] is True
    assert receipt["sql_admission_gap"] == pytest.approx(5.1)
    assert receipt["host_capture_gap"] == pytest.approx(5.2)
    assert receipt["fixture_receipt_gap"] == pytest.approx(4.84)
    assert receipt["capture_durations"] == pytest.approx([0.1, 0.1])
    assert delegate.finished == [(ticket, 200, "") for ticket in delegate.tickets]
    assert len(json.dumps(receipt)) < 1024


@pytest.mark.parametrize("failure", ["query", "missing", "order", "nonfinite", "deadline"])
def test_observation_failure_preserves_acquired_ticket_and_finish(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setattr(time, "monotonic", lambda: 10.0)
    delegate, timing = Resources(), module.BrowserTiming()

    def read(ticket: object, deadline: float) -> dict[str, Any]:
        if failure == "query":
            raise RuntimeError("Synthetic observation failed")
        if failure == "missing":
            return {}
        return {
            "attempts": 2 if failure == "order" else 1,
            "admitted": float("nan") if failure == "nonfinite" else 100.0,
        }

    observed = timing.resources(delegate, read)
    ticket = observed.acquire(URL, Operation.BROWSER, 10.0 if failure == "deadline" else 20.0)
    assert ticket is delegate.tickets[0]
    observed.finish(ticket, None, "")
    assert delegate.finished == [(ticket, None, "")]
    assert timing.failed and timing.receipt([])["complete"] is False


@pytest.mark.parametrize("stage", ["acquire", "finish"])
def test_delegate_errors_are_not_swallowed(stage: str) -> None:
    class Failing(Resources):
        def acquire(self, *args: object) -> object:
            if stage == "acquire":
                raise RuntimeError("delegate acquire")
            return super().acquire(*args)

        def finish(self, *args: Any) -> None:
            raise RuntimeError("delegate finish")

    timing = module.BrowserTiming()
    observed = timing.resources(Failing(), lambda ticket, deadline: {})
    with pytest.raises(RuntimeError, match="delegate " + stage):
        ticket = observed.acquire(URL, Operation.BROWSER, 20.0)
        observed.finish(ticket, None, "")


@pytest.mark.parametrize("count", [0, 1, 3, 10])
def test_missing_extra_or_duplicate_observations_refuse_complete_receipt(count: int) -> None:
    timing, delegate = module.BrowserTiming(), Resources()
    attempts = iter(range(1, count + 1))
    observed = timing.resources(
        delegate, lambda ticket, deadline: {"attempts": next(attempts), "admitted": 100.0}
    )
    for _ in range(count):
        observed.acquire(URL, Operation.BROWSER, float("inf"))
    assert len(timing.records) <= 2
    assert timing.receipt([{"received_monotonic": 1.0}] * 2)["complete"] is False


def test_tenant_context_entry_consumes_shared_observation_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager
    from types import SimpleNamespace
    from typing import cast
    from uuid import uuid4

    from emailmonitor.administration.source import SourceLease
    from emailmonitor.progress.service import Progress

    clock = [1.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])

    @contextmanager
    def tenant(*args: object) -> Any:
        clock[0] = 11.0
        yield SimpleNamespace(execute=lambda *args: pytest.fail("query after expiry")), None

    progress = cast(
        Progress, SimpleNamespace(database=SimpleNamespace(tenant=tenant), token="test")
    )
    org = uuid4()
    with pytest.raises(ValueError, match="deadline elapsed"):
        module.read_admission_timing(
            progress, org, uuid4(), 1, SourceLease(uuid4(), uuid4(), org), 10.0
        )

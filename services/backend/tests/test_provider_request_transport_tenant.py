"""Test-only client-socket A/B; identical real SQL authority checks, no speedup gate.

This measures the existing disposable PostgreSQL fixture, not installed-container
transport. No production connection hook, query cache or authority bypass exists.
"""

import json
import math
import socket
import ssl
import time
from typing import Any

import pg8000.legacy  # type: ignore[import-untyped]
import pytest
from emailmonitor.progress.binding import bound
from emailmonitor.progress.provider import ProviderJourney
from emailmonitor.progress.service import Progress
from emailmonitor.runtime.database import ServiceDatabase
from sqlalchemy import event
from test_durable_jobs import SETTINGS
from test_progress_tenant import claim
from test_provider_journey_tenant import NoDispatch
from test_provider_request_transaction_tenant import provider_service_case as provider_service_case
from test_service_authority_tenant import ServiceCase
from test_service_authority_tenant import _service_ci_guard as _service_ci_guard
from test_service_authority_tenant import service_case as service_case
from test_tenant_foundation import scenario as scenario


def require_driver_connection(value: object) -> None:
    # The pinned SQLAlchemy dialect imports top-level pg8000, whose Connection
    # export is legacy.Connection, not the distinct pg8000.dbapi.Connection.
    if type(value) is not pg8000.legacy.Connection:
        raise AssertionError("Exact dialect-selected pg8000 connection required")


def bounded_ms(seconds: float) -> tuple[int, bool]:
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Finite nonnegative measurement required")
    return min(20000, round(seconds * 1000)), seconds >= 20


class CursorMeasurement:
    """Only counts and elapsed totals; SQL, parameters and results are ignored."""

    def __init__(self, deadline: float) -> None:
        self.deadline = deadline
        self.started: float | None = None
        self.count = 0
        self.seconds = 0.0

    def before(self, *_ignored: Any) -> None:
        assert time.monotonic() < self.deadline, "SQL A/B measurement budget exhausted"
        assert self.started is None
        assert self.count < 128, "SQL A/B statement bound exceeded"
        self.started = time.monotonic()
        self.count += 1

    def after(self, *_ignored: Any) -> None:
        assert self.started is not None
        self.seconds += time.monotonic() - self.started
        self.started = None

    def receipt(self, elapsed: float) -> dict[str, int | bool]:
        assert self.started is None
        wall_ms, wall_capped = bounded_ms(elapsed)
        cursor_ms, cursor_capped = bounded_ms(self.seconds)
        return {
            "request_ms": wall_ms,
            "request_capped": wall_capped,
            "cursor_ms": cursor_ms,
            "cursor_capped": cursor_capped,
            "cursor_count": self.count,
        }


@pytest.mark.parametrize("route", ["discover", "article"])
def test_provider_current_socket_option_ab(
    provider_service_case: ServiceCase, route: str, capsys: pytest.CaptureFixture[str]
) -> None:
    case = provider_service_case
    org, job = case.scope.organization, case.scope.resource
    work = claim(Progress(case.database, case.scope, SETTINGS), org, job)
    assert work.kind == route
    started = time.monotonic()
    deadline = started + 20
    baseline: object = None
    peer_identity: object = None
    physical: list[object] = []
    rows: list[dict[str, object]] = []
    expected_counts: list[int] = []
    with bound(work.lease):
        for arm, enabled in enumerate((0, 1, 1, 0)):
            assert time.monotonic() < deadline, "SQL A/B measurement budget exhausted"
            database = ServiceDatabase(case.url, case.database.process)
            checkout = None
            try:
                with database.engine.connect() as connection:
                    assert not connection.in_transaction()
                    raw: Any = connection.connection.dbapi_connection
                    require_driver_connection(raw)
                    assert all(raw is not earlier for earlier in physical)
                    physical.append(raw)
                    transport = raw._usock
                    assert type(transport) in (socket.socket, ssl.SSLSocket)
                    assert transport.family in (socket.AF_INET, socket.AF_INET6)
                    assert (
                        transport.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE)
                        == socket.SOCK_STREAM
                    )
                    identity = (transport.getpeername(), type(transport))
                    if peer_identity is None:
                        peer_identity = identity
                    assert identity == peer_identity
                    transport.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, enabled)
                    assert transport.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) == enabled

                def same_connection(
                    dbapi_connection: Any,
                    *_ignored: Any,
                    expected_raw: Any = raw,
                    expected_transport: Any = transport,
                    expected_enabled: int = enabled,
                ) -> None:
                    assert dbapi_connection is expected_raw, "SQL A/B physical connection changed"
                    assert expected_raw._usock is expected_transport
                    assert (
                        expected_transport.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
                        == expected_enabled
                    )

                checkout = same_connection
                event.listen(database.engine, "checkout", checkout)
                journey = ProviderJourney(Progress(database, case.scope, SETTINGS), NoDispatch())
                for position in range(2):
                    assert time.monotonic() < deadline, "SQL A/B measurement budget exhausted"
                    measured = CursorMeasurement(deadline)
                    event.listen(database.engine, "before_cursor_execute", measured.before)
                    event.listen(database.engine, "after_cursor_execute", measured.after)
                    try:
                        request_started = time.monotonic()
                        result = journey._request(work)
                        elapsed = time.monotonic() - request_started
                    finally:
                        try:
                            event.remove(database.engine, "before_cursor_execute", measured.before)
                        finally:
                            event.remove(database.engine, "after_cursor_execute", measured.after)
                    assert time.monotonic() < deadline, "SQL A/B measurement budget exhausted"
                    if baseline is None:
                        baseline = result
                    if result != baseline:
                        raise AssertionError("SQL A/B authorized result mismatch")
                    if arm == 0:
                        expected_counts.append(measured.count)
                    assert measured.count == expected_counts[position]
                    rows.append(
                        {
                            "arm": arm,
                            "nodelay": bool(enabled),
                            "position": position,
                            **measured.receipt(elapsed),
                        }
                    )
            finally:
                try:
                    if checkout is not None:
                        event.remove(database.engine, "checkout", checkout)
                finally:
                    database.engine.dispose()
            assert time.monotonic() < deadline, "SQL A/B measurement budget exhausted"
    total_ms, capped = bounded_ms(time.monotonic() - started)
    assert not capped and len(rows) == 8
    # Explicit test receipt even when the application suite otherwise captures stdout.
    with capsys.disabled():
        print(
            json.dumps(
                {
                    "proof": "PROVIDER_CURRENT_SOCKET_AB",
                    "route": route,
                    "total_ms": total_ms,
                    "total_capped": capped,
                    "samples": rows,
                    "cleanup": True,
                    "performance_claim": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )

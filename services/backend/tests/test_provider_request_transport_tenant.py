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
from sqlalchemy import event, text
from sqlalchemy.dialects.postgresql.pg8000 import PGDialect_pg8000
from test_durable_jobs import SETTINGS
from test_progress_tenant import claim
from test_provider_journey_tenant import NoDispatch
from test_provider_request_transaction_tenant import provider_service_case as provider_service_case
from test_service_authority_tenant import ServiceCase
from test_service_authority_tenant import _service_ci_guard as _service_ci_guard
from test_service_authority_tenant import service_case as service_case
from test_tenant_foundation import scenario as scenario

# Trusted authored templates only; emitted diagnostics contain these labels, never
# SQL or parameters. Compilation is local and opens no database connection.
STATEMENT_TEMPLATES = {
    "timeout_settings": (
        "SELECT set_config('lock_timeout','2000ms',true), "
        "set_config('statement_timeout','5000ms',true)"
    ),
    "service_begin": (
        "SELECT emailmonitor.service_begin(:org,:resource,:purpose,:generation,:kind,:principal)"
    ),
    "work_binding": """SELECT set_config('emailmonitor.execution_job',:job,true),
set_config('emailmonitor.execution_item',:item,true),
set_config('emailmonitor.execution_token',:token,true),
set_config('emailmonitor.execution_generation',:generation,true),
set_config('emailmonitor.execution_deletion',:deletion,true)""",
    "fixture_binding": """SELECT set_config('emailmonitor.fixture_job',:job,true),
set_config('emailmonitor.fixture_url',:url,true),set_config('emailmonitor.fixture_reference',:reference,true),
set_config('emailmonitor.fixture_nonce',:nonce,true)""",
    "job_lock": """SELECT j.*, o.deletion_generation FROM emailmonitor.work_job_lock(:org,:job) j
JOIN emailmonitor.organizations o ON o.id=j.organization_id""",
    "job_permission": "SELECT emailmonitor.job_permission_fence(:org,:job)",
    "discovery_read": """SELECT * FROM emailmonitor.discovery
WHERE organization_id=:org AND job_id=:job FOR UPDATE""",
    "execution_allowed": "SELECT emailmonitor.execution_write_allowed(:org,:job)",
    "execution_match": """SELECT emailmonitor.execution_write_allowed(:org,:job) AND EXISTS(
SELECT 1 FROM emailmonitor.jobs j WHERE j.organization_id=:org AND j.id=:job AND
(j.state='draft' OR EXISTS(SELECT 1 FROM emailmonitor.execution_items i WHERE
 i.organization_id=j.organization_id AND i.job_id=j.id AND i.work_kind=:kind
 AND i.input_url=:url AND i.id::text=current_setting('emailmonitor.execution_item',true))))""",
    "source_fence": "SELECT emailmonitor.discovery_source_fence(:org,:job,:version)",
    "policy_read": """SELECT p.*,s.enabled,s.support FROM emailmonitor.source_policies p
JOIN emailmonitor.source_policy_heads h USING(organization_id,source_id)
JOIN emailmonitor.source_catalog s USING(source_id)
WHERE p.organization_id=:org AND p.source_id=:source AND p.version=h.current_version""",
    "service_end": "SELECT emailmonitor.service_end(:org,:resource,:purpose,:kind)",
}
CATEGORIES = (*STATEMENT_TEMPLATES, "UNKNOWN")
DIALECT_FACTORY: Any = PGDialect_pg8000
STATEMENT_CATEGORIES = {
    " ".join(
        str(text(template).compile(dialect=DIALECT_FACTORY(paramstyle="format"))).split()
    ): label
    for label, template in STATEMENT_TEMPLATES.items()
}


def statement_category(statement: object) -> str:
    if type(statement) is not str or len(statement) > 4096:
        return "UNKNOWN"
    return STATEMENT_CATEGORIES.get(" ".join(statement.split()), "UNKNOWN")


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
    """Client cursor-execute spans, including driver/network/server time.

    Only exact trusted SQL shapes are categorized; parameters/results are ignored.
    Checkout, commit and Python work outside execute are not category timings.
    """

    def __init__(self, deadline: float) -> None:
        self.deadline = deadline
        self.started: float | None = None
        self.count = 0
        self.seconds = 0.0
        self.category: str | None = None
        self.category_counts = dict.fromkeys(CATEGORIES, 0)
        self.category_seconds = dict.fromkeys(CATEGORIES, 0.0)

    def before(
        self, _connection: Any = None, _cursor: Any = None, statement: object = None, *_ignored: Any
    ) -> None:
        assert time.monotonic() < self.deadline, "SQL A/B measurement budget exhausted"
        assert self.started is None
        assert self.count < 128, "SQL A/B statement bound exceeded"
        self.category = statement_category(statement)
        self.started = time.monotonic()
        self.count += 1

    def after(self, *_ignored: Any) -> None:
        assert self.started is not None
        elapsed = time.monotonic() - self.started
        self.seconds += elapsed
        assert self.category in CATEGORIES
        self.category_counts[self.category] += 1
        self.category_seconds[self.category] += elapsed
        self.started = None
        self.category = None

    def receipt(self, elapsed: float) -> dict[str, object]:
        assert self.started is None
        wall_ms, wall_capped = bounded_ms(elapsed)
        cursor_ms, cursor_capped = bounded_ms(self.seconds)
        assert sum(self.category_counts.values()) == self.count
        categories: list[dict[str, object]] = []
        for category in CATEGORIES:
            milliseconds, capped = bounded_ms(self.category_seconds[category])
            categories.append(
                {
                    "category": category,
                    "count": self.category_counts[category],
                    "cursor_ms": milliseconds,
                    "cursor_capped": capped,
                }
            )
        return {
            "request_ms": wall_ms,
            "request_capped": wall_capped,
            "cursor_ms": cursor_ms,
            "cursor_capped": cursor_capped,
            "cursor_count": self.count,
            "categories": categories,
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
    expected_categories: list[dict[str, int]] = []
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
                        expected_categories.append(dict(measured.category_counts))
                    assert measured.count == expected_counts[position]
                    assert measured.category_counts == expected_categories[position]
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

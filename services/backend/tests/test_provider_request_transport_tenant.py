"""Bounded disposable query plans; no raw plans or production changes.

Worker fence plans measure actual service calls. The separately labelled owner
leaf-body surrogate measures standalone planning/execution, not nested function
planning or cache behavior. The 20-second budget is cooperative; existing SQL
caps remain in force. Historical A/B pure helpers are retained for regression.
"""

import json
import math
import re
import time
from pathlib import Path
from typing import Any

import pg8000.legacy  # type: ignore[import-untyped]
import pytest
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import bound
from emailmonitor.progress.provider import ProviderJourney
from emailmonitor.progress.service import Progress
from sqlalchemy import text
from sqlalchemy.dialects.postgresql.pg8000 import PGDialect_pg8000
from sqlalchemy.exc import SQLAlchemyError
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


def jit_setting(value: object) -> bool:
    if type(value) is not str or value not in ("on", "off"):
        raise AssertionError("SQL A/B JIT setting invalid")
    return value == "on"


def configure_jit(connection: Any, enabled: bool, deadline: float) -> tuple[bool, bool]:
    """Only this disposable engine retains the session setting until disposal."""
    if type(enabled) is not bool or connection.in_transaction():
        raise AssertionError("SQL A/B JIT setup scope invalid")

    def execute(sql: str) -> Any:
        assert time.monotonic() < deadline, "SQL A/B measurement budget exhausted"
        return connection.execute(text(sql))

    execute(STATEMENT_TEMPLATES["timeout_settings"])
    baseline = jit_setting(execute("SHOW jit").scalar_one())
    # pg_jit_available() also requires jit=on. Probe identically before each arm,
    # then set the requested value before any measured authority transaction.
    execute("SET SESSION jit = on")
    available = execute("SELECT pg_catalog.pg_jit_available()").scalar_one()
    if type(available) is not bool:
        raise AssertionError("SQL A/B JIT availability invalid")
    execute("SET SESSION jit = on" if enabled else "SET SESSION jit = off")
    effective = jit_setting(execute("SHOW jit").scalar_one())
    if effective is not enabled:
        raise AssertionError("SQL A/B JIT setting mismatch")
    connection.commit()
    assert not connection.in_transaction()
    assert time.monotonic() < deadline, "SQL A/B measurement budget exhausted"
    return baseline, available


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


# This source is authored fixture/migration text, never database-supplied SQL.
LEAF_HEADER = """CREATE FUNCTION emailmonitor.service_delegation_current(p_org uuid,p_id uuid)
 RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER
 SET search_path=pg_catalog,emailmonitor AS $$"""


def leaf_body(source: str) -> str:
    if type(source) is not str or source.count(LEAF_HEADER) != 1:
        raise AssertionError("Fixed diagnostic function source required")
    remaining = source.split(LEAF_HEADER, 1)[1]
    if "$$;" not in remaining:
        raise AssertionError("Fixed diagnostic function source required")
    body = remaining.split("$$;", 1)[0]
    if not body.lstrip().startswith("SELECT ") or ";" in body or len(body) > 12000:
        raise AssertionError("Fixed diagnostic function source required")
    return body


def leaf_query(body: str) -> str:
    return re.sub(r"\bp_(org|id)\b", lambda m: ":org" if m[1] == "org" else ":grant", body)


LEAF_METADATA = """SELECT p.prosrc, l.lanname, p.provolatile, p.prosecdef,
 p.proconfig, r.rolname,
 p.proacl=ARRAY['emailmonitor_owner=X/emailmonitor_owner'::aclitem],
 p.prorettype='boolean'::regtype, p.proretset, p.proargnames
 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
 JOIN pg_roles r ON r.oid=p.proowner
 WHERE p.oid='emailmonitor.service_delegation_current(uuid,uuid)'::regprocedure"""


def validate_leaf_metadata(row: object, body: str) -> None:
    expected = (
        body,
        "sql",
        "v",
        True,
        ["search_path=pg_catalog, emailmonitor"],
        "emailmonitor_owner",
        True,
        True,
        False,
        ["p_org", "p_id"],
    )
    # SQLAlchemy Row is converted by the caller; reject unexpected result shapes
    # without formatting any installed source/security metadata.
    if type(row) is not tuple or len(row) != len(expected):
        raise AssertionError("Diagnostic function metadata mismatch")
    if any(
        type(actual) is not type(wanted) or actual != wanted
        for actual, wanted in zip(row, expected, strict=True)
    ):
        raise AssertionError("Diagnostic function metadata mismatch")


def plan_metrics(value: object) -> dict[str, object]:
    """Closed numeric summary; traverse bounded JSON without rendering strings."""
    items = 0
    characters = 0

    def bounded_json(part: object, depth: int) -> None:
        nonlocal items, characters
        items += 1
        if depth > 64 or items > 8192:
            raise AssertionError("Diagnostic plan bounds exceeded")
        if type(part) is dict:
            for key, child in part.items():
                if type(key) is not str:
                    raise AssertionError("Diagnostic plan shape invalid")
                characters += len(key)
                bounded_json(child, depth + 1)
        elif type(part) is list:
            for child in part:
                bounded_json(child, depth + 1)
        elif type(part) is str:
            characters += len(part)
        elif part is not None and type(part) not in (int, float, bool):
            raise AssertionError("Diagnostic plan shape invalid")
        if characters > 1048576:
            raise AssertionError("Diagnostic plan bounds exceeded")

    bounded_json(value, 0)
    if type(value) is not list or len(value) != 1 or type(value[0]) is not dict:
        raise AssertionError("Diagnostic plan shape invalid")
    document = value[0]
    root = document.get("Plan")
    if type(root) is not dict:
        raise AssertionError("Diagnostic plan shape invalid")
    capped = False

    def numeric(value: Any, ceiling: int, rounded: bool = False) -> int:
        nonlocal capped
        if (
            type(value) not in (int, float)
            or (type(value) is float and not math.isfinite(value))
            or value < 0
        ):
            raise AssertionError("Diagnostic plan metric invalid")
        if not rounded and int(value) != value:
            raise AssertionError("Diagnostic plan metric invalid")
        capped |= value >= ceiling
        return int(min(ceiling, round(value)))

    nodes = 0

    def count_nodes(node: object, depth: int) -> None:
        nonlocal nodes
        if type(node) is not dict or depth > 32:
            raise AssertionError("Diagnostic plan tree invalid")
        nodes += 1
        if nodes > 512:
            raise AssertionError("Diagnostic plan bounds exceeded")
        children = node.get("Plans", [])
        if type(children) is not list:
            raise AssertionError("Diagnostic plan tree invalid")
        for child in children:
            count_nodes(child, depth + 1)

    count_nodes(root, 0)
    jit = document.get("JIT", {})
    if type(jit) is not dict:
        raise AssertionError("Diagnostic plan shape invalid")
    result = {
        "planning_ms": numeric(document.get("Planning Time"), 20000, True),
        "execution_ms": numeric(document.get("Execution Time"), 20000, True),
        "nodes": nodes,
        "root_rows": numeric(root.get("Actual Rows"), 1000000),
        "root_loops": numeric(root.get("Actual Loops"), 1000000),
        "root_shared_hits": numeric(root.get("Shared Hit Blocks", 0), 1000000),
        "root_shared_reads": numeric(root.get("Shared Read Blocks", 0), 1000000),
        "outer_jit_present": "JIT" in document,
        "outer_jit_functions": numeric(jit.get("Functions", 0), 1000000),
    }
    return {**result, "metrics_capped": capped}


def plan_budget(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise AssertionError("SQL plan measurement budget exhausted")


def explain(
    connection: Any, sql: str, params: dict[str, object], deadline: float
) -> dict[str, object]:
    plan_budget(deadline)
    try:
        raw = connection.execute(
            text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON, TIMING OFF) " + sql), params
        ).scalar_one()
    except SQLAlchemyError:
        raise AssertionError("Diagnostic plan execution failed") from None
    result = plan_metrics(raw)
    plan_budget(deadline)
    return result


def owner_leaf_plans(
    owner: Any, body: str, org: object, grant: object, deadline: float
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    transaction = owner.begin()
    try:
        plan_budget(deadline)
        owner.execute(text(STATEMENT_TEMPLATES["timeout_settings"]))
        installed = tuple(owner.execute(text(LEAF_METADATA)).one())
        validate_leaf_metadata(installed, body)
        owner.execute(text("SET LOCAL ROLE emailmonitor_owner"))
        owner.execute(text("SET LOCAL search_path=pg_catalog,emailmonitor"))
        for position in range(2):
            metrics = explain(owner, leaf_query(body), {"org": org, "grant": grant}, deadline)
            samples.append({"slice": "owner_leaf_surrogate", "position": position, **metrics})
    except SQLAlchemyError:
        raise AssertionError("Diagnostic owner setup failed") from None
    finally:
        transaction.rollback()
    return samples


@pytest.mark.parametrize("route", ["discover", "article"])
def test_provider_current_fixed_plans(
    provider_service_case: ServiceCase, route: str, capsys: pytest.CaptureFixture[str]
) -> None:
    case = provider_service_case
    org, job = case.scope.organization, case.scope.resource
    work = claim(Progress(case.database, case.scope, SETTINGS), org, job)
    assert work.kind == route
    deadline = time.monotonic() + 20
    samples: list[dict[str, object]] = []
    body = leaf_body(
        (Path(__file__).parents[1] / "migrations/versions/0014_service_authority.sql").read_text()
    )
    with bound(work.lease):
        journey = ProviderJourney(Progress(case.database, case.scope, SETTINGS), NoDispatch())
        _, row, _ = journey._request(work)
        params: dict[str, object] = {"org": org, "job": job, "version": row["policy_version"]}
        with case.database.tenant(case.scope, org, Capability.ACQUIRE_SOURCE) as (connection, _):
            # Roll back only diagnostic fence acquisitions; service_begin/end
            # retain their normal transaction and audit behavior.
            savepoint = connection.begin_nested()
            try:
                for position in range(2):
                    for category in ("job_lock", "source_fence"):
                        metrics = explain(
                            connection, STATEMENT_TEMPLATES[category], params, deadline
                        )
                        samples.append({"slice": category, "position": position, **metrics})
            finally:
                savepoint.rollback()
        # Separate existing disposable administrator connection only. This is a
        # labelled leaf surrogate, never a worker authorization or acceptance.
        with case.admin.connect() as owner:
            samples.extend(owner_leaf_plans(owner, body, org, case.grant, deadline))
    plan_budget(deadline)
    assert len(samples) == 6
    with capsys.disabled():
        print(
            json.dumps(
                {
                    "proof": "PROVIDER_CURRENT_FIXED_PLANS",
                    "route": route,
                    "samples": samples,
                    "cleanup": True,
                    "leaf_is_standalone_surrogate": True,
                    "nested_planning_claim": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )

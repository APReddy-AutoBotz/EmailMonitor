"""Pure bounded receipt arithmetic; no PostgreSQL or socket operations."""

import time
from typing import Any

import pg8000.dbapi  # type: ignore[import-untyped]
import pg8000.legacy  # type: ignore[import-untyped]
import pytest
import test_provider_request_transport_tenant as probe


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, (0, False)),
        (0.0014, (1, False)),
        (1.5, (1500, False)),
        (20, (20000, True)),
        (2000, (20000, True)),
    ],
)
def test_rounded_saturated_milliseconds(seconds: float, expected: tuple[int, bool]) -> None:
    assert probe.bounded_ms(seconds) == expected


@pytest.mark.parametrize("value", [True, -1, float("inf"), float("nan"), "private", object()])
def test_invalid_measurements_rejected_without_echo(value: Any) -> None:
    with pytest.raises(ValueError, match="^Finite nonnegative measurement required$"):
        probe.bounded_ms(value)


def test_cursor_observer_ignores_hostile_sql_and_values(monkeypatch: pytest.MonkeyPatch) -> None:
    class Hostile:
        def __str__(self) -> str:
            raise AssertionError("Must not inspect query values")

        __repr__ = __str__

    ticks = iter([1.0, 1.0, 1.125])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    measurement = probe.CursorMeasurement(10)
    measurement.before(Hostile(), Hostile())
    measurement.after(Hostile())
    receipt = measurement.receipt(0.25)
    categories = receipt.pop("categories")
    assert isinstance(categories, list)
    assert len(categories) == 13
    assert categories[-1] == {
        "category": "UNKNOWN",
        "count": 1,
        "cursor_ms": 125,
        "cursor_capped": False,
    }
    assert receipt == {
        "request_ms": 250,
        "request_capped": False,
        "cursor_ms": 125,
        "cursor_capped": False,
        "cursor_count": 1,
    }


@pytest.mark.parametrize("expired", [False, True])
def test_cursor_measurement_refuses_exhausted_budget(
    monkeypatch: pytest.MonkeyPatch, expired: bool
) -> None:
    monkeypatch.setattr(time, "monotonic", lambda: 10.0)
    measurement = probe.CursorMeasurement(10.0 if expired else 20.0)
    if not expired:
        measurement.count = 128
    with pytest.raises(AssertionError, match="SQL A/B"):
        measurement.before()
    assert measurement.started is None


def test_exact_connection_matches_installed_sqlalchemy_dialect() -> None:
    from sqlalchemy.dialects.postgresql.pg8000 import PGDialect_pg8000

    selected = PGDialect_pg8000.import_dbapi()  # type: ignore[no-untyped-call]
    assert selected.Connection is pg8000.legacy.Connection
    assert selected.Connection is not pg8000.dbapi.Connection
    # Allocate without connecting: no sockets, authentication or database needed.
    probe.require_driver_connection(object.__new__(selected.Connection))


def test_connection_guard_rejects_other_driver_classes_and_subclasses() -> None:

    class Derived(pg8000.legacy.Connection):  # type: ignore[misc]
        pass

    for value in (object(), object.__new__(pg8000.dbapi.Connection), object.__new__(Derived)):
        with pytest.raises(
            AssertionError, match="^Exact dialect-selected pg8000 connection required$"
        ):
            probe.require_driver_connection(value)


@pytest.mark.parametrize("statement", [None, True, 5, "SELECT private", "x" * 4097])
def test_unrecognized_statement_has_only_closed_unknown_category(statement: object) -> None:
    assert probe.statement_category(statement) == "UNKNOWN"


def test_statement_classifier_never_stringifies_hostile_values() -> None:
    class Hostile:
        def __str__(self) -> str:
            raise AssertionError("No statement stringify")

        __repr__ = __str__

    class StringSubclass(str):
        def split(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("Only exact strings may be normalized")

    assert probe.statement_category(Hostile()) == "UNKNOWN"
    assert probe.statement_category(StringSubclass("SELECT private")) == "UNKNOWN"


def test_known_production_sql_shapes_match_fixed_categories() -> None:
    import ast
    import inspect

    from emailmonitor.administration.binding import apply as fixture_apply
    from emailmonitor.discovery.service import Discovery
    from emailmonitor.jobs.ledger import Ledger
    from emailmonitor.progress.binding import allowed, apply, matches
    from emailmonitor.runtime.database import ServiceDatabase
    from emailmonitor.sources.access import current_policy
    from sqlalchemy import text

    found: set[str] = set()
    for method in (
        ServiceDatabase.tenant,
        fixture_apply,
        Discovery._row,
        Discovery._authorize,
        Ledger._lock,
        allowed,
        apply,
        matches,
        current_policy,
    ):
        source = inspect.getsource(method)
        tree = ast.parse("if True:\n" + source if source.startswith(" ") else source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "text"
            ):
                assert isinstance(node.args[0], ast.Constant)
                assert type(node.args[0].value) is str
                raw = str(
                    text(node.args[0].value).compile(
                        dialect=probe.DIALECT_FACTORY(paramstyle="format")
                    )
                )
                category = probe.statement_category(raw)
                assert category != "UNKNOWN"
                assert probe.statement_category(" \n" + raw.replace(" ", "  ") + "\n") == category
                found.add(category)
    assert found == set(probe.CATEGORIES) - {"UNKNOWN"}


@pytest.mark.parametrize("article", [False, True])
def test_category_totals_reconcile_for_fixed_request_sequence(
    monkeypatch: pytest.MonkeyPatch, article: bool
) -> None:
    import itertools

    from sqlalchemy import text

    sequence = [
        "timeout_settings",
        "service_begin",
        "work_binding",
        "fixture_binding",
        "timeout_settings",
        "job_lock",
        "job_permission",
        "discovery_read",
    ]
    if not article:
        sequence.append("execution_allowed")
    sequence += [
        "execution_match",
        "source_fence",
        "policy_read",
        "source_fence",
        "policy_read",
        "service_end",
    ]
    ticks = itertools.count()
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks) / 1000)
    measured = probe.CursorMeasurement(20)
    for category in sequence:
        sql = str(
            text(probe.STATEMENT_TEMPLATES[category]).compile(
                dialect=probe.DIALECT_FACTORY(paramstyle="format")
            )
        )
        measured.before(None, None, sql, object())
        measured.after()
    receipt = measured.receipt(0.1)
    categories = receipt["categories"]
    assert isinstance(categories, list)
    assert (
        sum(row["count"] for row in categories)
        == receipt["cursor_count"]
        == (14 if article else 15)
    )
    assert {row["category"] for row in categories} == set(probe.CATEGORIES)
    assert all(
        set(row) == {"category", "count", "cursor_ms", "cursor_capped"} for row in categories
    )
    assert measured.category_counts["UNKNOWN"] == 0


@pytest.mark.parametrize("value", [None, True, 1, "private", "ON", object()])
def test_jit_setting_rejects_unknown_values_without_echo(value: object) -> None:
    with pytest.raises(AssertionError, match="^SQL A/B JIT setting invalid$"):
        probe.jit_setting(value)


class SetupConnection:
    def __init__(self, replies: list[object]) -> None:
        self.replies = iter(replies)
        self.sql: list[str] = []
        self.active = False
        self.committed = False

    def in_transaction(self) -> bool:
        return self.active

    def execute(self, statement: Any) -> "SetupConnection":
        self.active = True
        self.sql.append(str(statement))
        return self

    def scalar_one(self) -> object:
        return next(self.replies)

    def commit(self) -> None:
        self.active = False
        self.committed = True


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("available", [False, True])
def test_jit_setup_probes_with_on_then_commits_requested_arm(
    enabled: bool, available: bool
) -> None:
    connection = SetupConnection(["off", available, "on" if enabled else "off"])
    assert probe.configure_jit(connection, enabled, time.monotonic() + 20) == (False, available)
    assert connection.sql == [
        probe.STATEMENT_TEMPLATES["timeout_settings"],
        "SHOW jit",
        "SET SESSION jit = on",
        "SELECT pg_catalog.pg_jit_available()",
        "SET SESSION jit = on" if enabled else "SET SESSION jit = off",
        "SHOW jit",
    ]
    assert connection.committed and not connection.in_transaction()


@pytest.mark.parametrize(
    "replies,error",
    [
        (["private"], "setting invalid"),
        (["on", 1], "availability invalid"),
        (["on", True, "private"], "setting invalid"),
        (["on", True, "on"], "setting mismatch"),
    ],
)
def test_invalid_jit_setup_cannot_commit(replies: list[object], error: str) -> None:
    connection = SetupConnection(replies)
    with pytest.raises(AssertionError, match=f"^SQL A/B JIT {error}$"):
        probe.configure_jit(connection, False, time.monotonic() + 20)
    assert not connection.committed


def test_jit_setup_budget_and_active_transaction_guards() -> None:
    connection = SetupConnection([])
    with pytest.raises(AssertionError, match="measurement budget exhausted"):
        probe.configure_jit(connection, False, time.monotonic() - 1)
    assert connection.sql == []
    connection.active = True
    with pytest.raises(AssertionError, match="setup scope invalid"):
        probe.configure_jit(connection, False, time.monotonic() + 20)
    assert connection.sql == []


def test_jit_setup_commit_failure_prevents_return() -> None:
    class CommitFailure(SetupConnection):
        def commit(self) -> None:
            raise RuntimeError("synthetic commit failure")

    connection = CommitFailure(["on", True, "off"])
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        probe.configure_jit(connection, False, time.monotonic() + 20)
    assert not connection.committed


def test_jit_setting_does_not_inspect_hostile_values() -> None:
    class Hostile:
        def __str__(self) -> str:
            raise AssertionError("No raw values")

        __repr__ = __str__

    class HostileString(str):
        def __eq__(self, other: object) -> bool:
            raise AssertionError("No subclass comparison")

    for value in (Hostile(), HostileString("on")):
        with pytest.raises(AssertionError, match="^SQL A/B JIT setting invalid$"):
            probe.jit_setting(value)


def test_jit_setup_stops_between_statements_when_budget_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticks = iter([1.0, 21.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    connection = SetupConnection([])
    with pytest.raises(AssertionError, match="measurement budget exhausted"):
        probe.configure_jit(connection, False, 20)
    assert connection.sql == [probe.STATEMENT_TEMPLATES["timeout_settings"]]
    assert not connection.committed


def sample_plan() -> list[dict[str, Any]]:
    return [
        {
            "Planning Time": 12.4,
            "Execution Time": 3.6,
            "Plan": {
                "Node Type": "Result",
                "Actual Rows": 1,
                "Actual Loops": 1,
                "Shared Hit Blocks": 7,
                "Shared Read Blocks": 0,
                "Filter": "private synthetic value",
            },
        }
    ]


def test_plan_summary_has_only_closed_numeric_metrics() -> None:
    receipt = probe.plan_metrics(sample_plan())
    assert receipt == {
        "planning_ms": 12,
        "execution_ms": 4,
        "nodes": 1,
        "root_rows": 1,
        "root_loops": 1,
        "root_shared_hits": 7,
        "root_shared_reads": 0,
        "outer_jit_present": False,
        "outer_jit_functions": 0,
        "metrics_capped": False,
    }
    assert "private" not in str(receipt)


@pytest.mark.parametrize("bad", [True, None, "private", -1, float("inf"), float("nan")])
def test_plan_summary_rejects_invalid_numbers_without_echo(bad: object) -> None:
    plan = sample_plan()
    plan[0]["Planning Time"] = bad
    with pytest.raises(AssertionError, match="^Diagnostic plan metric invalid$"):
        probe.plan_metrics(plan)


def test_plan_summary_saturates_counts_and_time_and_counts_nodes() -> None:
    plan = sample_plan()
    plan[0]["Planning Time"] = 25000
    plan[0]["Plan"]["Shared Hit Blocks"] = 10**1000
    plan[0]["Plan"]["Plans"] = [{"Node Type": "Result"}]
    plan[0]["JIT"] = {"Functions": 4}
    receipt = probe.plan_metrics(plan)
    assert receipt["planning_ms"] == 20000
    assert receipt["root_shared_hits"] == 1000000
    assert receipt["nodes"] == 2
    assert receipt["outer_jit_functions"] == 4
    assert receipt["metrics_capped"] is True


def test_plan_summary_rejects_hostile_and_oversized_json_without_stringify() -> None:
    class Hostile:
        def __str__(self) -> str:
            raise AssertionError("No raw plan stringify")

        __repr__ = __str__

    for value in (Hostile(), [{"Plan": Hostile()}], ["x" * 1048577], [None] * 8193):
        with pytest.raises(
            AssertionError, match="^Diagnostic plan (shape invalid|bounds exceeded)$"
        ):
            probe.plan_metrics(value)
    plan = sample_plan()
    plan[0]["Plan"]["Plans"] = [{}] * 513
    with pytest.raises(AssertionError, match="^Diagnostic plan bounds exceeded$"):
        probe.plan_metrics(plan)
    plan = sample_plan()
    child = plan[0]["Plan"]
    for _ in range(35):
        child["Plans"] = [{}]
        child = child["Plans"][0]
    with pytest.raises(AssertionError, match="^Diagnostic plan bounds exceeded$"):
        probe.plan_metrics(plan)


def test_fixed_leaf_extraction_parameterization_and_metadata() -> None:
    from pathlib import Path

    source = (
        Path(probe.__file__).parents[1] / "migrations/versions/0014_service_authority.sql"
    ).read_text()
    body = probe.leaf_body(source)
    query = probe.leaf_query(body)
    assert "p_org" not in query and "p_id" not in query
    assert ":org" in query and ":grant" in query
    assert "clock_timestamp()" in query
    assert "session_user" not in body
    row = (
        "\nBEGIN\n RETURN (" + body + ");\nEND;\n",
        "plpgsql",
        "v",
        True,
        ["search_path=pg_catalog, emailmonitor"],
        "emailmonitor_owner",
        True,
        True,
        False,
        ["p_org", "p_id"],
    )
    probe.validate_leaf_metadata(row, body)
    for index, wrong in enumerate(
        ("private", "sql", "s", False, [], "private", False, False, True, [])
    ):
        changed = list(row)
        changed[index] = wrong
        with pytest.raises(AssertionError, match="^Diagnostic function metadata mismatch$"):
            probe.validate_leaf_metadata(tuple(changed), body)
    for changed_source in ("", source + source, source.replace("$$;", "", 1)):
        # Removal elsewhere does not alter this function; only its exact slice
        # matters. Missing/duplicate declaration always fails closed.
        if changed_source.count(probe.LEAF_HEADER) != 1:
            with pytest.raises(AssertionError, match="^Fixed diagnostic function source required$"):
                probe.leaf_body(changed_source)


def test_explain_failure_is_sanitized_and_budget_precedes_execution() -> None:
    from sqlalchemy.exc import SQLAlchemyError

    class Broken:
        def execute(self, *_args: object) -> None:
            raise SQLAlchemyError("private SQL and parameters")

    with pytest.raises(AssertionError, match="^Diagnostic plan execution failed$") as error:
        probe.explain(Broken(), "SELECT 1", {}, time.monotonic() + 20)
    assert error.value.__suppress_context__
    with pytest.raises(AssertionError, match="^SQL plan measurement budget exhausted$"):
        probe.explain(Broken(), "SELECT 1", {}, time.monotonic() - 1)


@pytest.mark.parametrize("failure", ["none", "metadata", "setup", "explain", "sanitizer"])
def test_owner_leaf_transaction_always_rolls_back(failure: str) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    class Owner:
        def __init__(self) -> None:
            self.calls = 0
            self.rolled_back = False

        def begin(self) -> "Owner":
            return self

        def execute(self, *_args: object) -> "Owner":
            self.calls += 1
            if (failure == "setup" and self.calls == 3) or (
                failure == "explain" and self.calls == 5
            ):
                raise SQLAlchemyError("private diagnostic input")
            return self

        def one(self) -> tuple[object, ...]:
            return (
                "private" if failure == "metadata" else "\nBEGIN\n RETURN (SELECT true);\nEND;\n",
                "plpgsql",
                "v",
                True,
                ["search_path=pg_catalog, emailmonitor"],
                "emailmonitor_owner",
                True,
                True,
                False,
                ["p_org", "p_id"],
            )

        def scalar_one(self) -> object:
            return [{"Plan": None}] if failure == "sanitizer" else sample_plan()

        def rollback(self) -> None:
            self.rolled_back = True

    owner = Owner()
    if failure == "none":
        rows = probe.owner_leaf_plans(
            owner, "SELECT true", object(), object(), time.monotonic() + 20
        )
        assert len(rows) == 2
    else:
        with pytest.raises(AssertionError, match="^Diagnostic "):
            probe.owner_leaf_plans(owner, "SELECT true", object(), object(), time.monotonic() + 20)
    assert owner.rolled_back
    if failure == "metadata":
        assert owner.calls == 2  # No role switch or authored body execution.

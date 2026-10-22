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
    assert measurement.receipt(0.25) == {
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

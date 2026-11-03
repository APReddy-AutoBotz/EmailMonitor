"""Observer failures and untrusted notices cannot affect results or disclose values."""

from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest
from emailmonitor.jobs.entitlement_diagnostics import (
    LIMIT,
    PREFIX,
    STATEMENT,
    EntitlementDiagnostics,
    snapshot,
)
from entitlement_sql_diagnostic import instrument
from sqlalchemy import text


def context() -> SimpleNamespace:
    return SimpleNamespace(compiled=SimpleNamespace(statement=text(STATEMENT)))


@pytest.mark.parametrize("reason", ["allowed", "authority_denied", "lock_refused"])
def test_only_this_invocations_fixed_notice_crosses_boundary(reason: str) -> None:
    old = {b"M": (PREFIX + "lock_refused").encode()}
    private = {b"M": b"private token/tenant value", b"D": b"secret detail"}
    notices = deque([old, private], maxlen=100)
    connection = SimpleNamespace(
        connection=SimpleNamespace(driver_connection=SimpleNamespace(notices=notices))
    )
    output: list[str] = []
    observer, current = EntitlementDiagnostics(output.append), context()
    observer.before(connection, None, None, None, current, False)
    notices.append({b"M": (PREFIX + reason).encode(), b"W": b"unprinted context"})
    observer.after(connection, None, None, None, current, False)
    assert output == [PREFIX + reason + "\n"]
    assert list(notices)[:2] == [old, private]  # no cursor/notice consumption
    assert snapshot("".join(output).encode())["last_reason"] == reason


@pytest.mark.parametrize("mode", ["missing", "multiple", "old_only", "bad_notice"])
def test_ambiguous_or_missing_capture_is_not_attributed(mode: str) -> None:
    notices: deque[object] = deque([{b"M": (PREFIX + "allowed").encode()}], maxlen=100)
    connection = SimpleNamespace(
        connection=SimpleNamespace(driver_connection=SimpleNamespace(notices=notices))
    )
    output: list[str] = []
    observer, current = EntitlementDiagnostics(output.append), context()
    if mode != "missing":
        observer.before(connection, None, None, None, current, False)
    if mode == "multiple":
        notices.extend([{b"M": (PREFIX + x).encode()} for x in ("allowed", "lock_refused")])
    elif mode == "bad_notice":
        notices.append({b"M": object()})
    observer.after(connection, None, None, None, current, False)
    assert output == [PREFIX + "unavailable\n"]
    assert snapshot(output[0].encode())["complete"] is False


def test_writer_failure_and_unrelated_statements_do_not_escape() -> None:
    def fail(_: str) -> None:
        raise RuntimeError("private writer failure")

    observer = EntitlementDiagnostics(fail)
    observer.after(object(), None, None, None, context(), False)
    unrelated = SimpleNamespace(compiled=SimpleNamespace(statement=text("SELECT 1")))
    observer.before(object(), None, None, None, unrelated, False)
    observer.after(object(), None, None, None, unrelated, False)


def test_output_is_bounded_and_truncation_is_not_complete_evidence() -> None:
    output: list[str] = []
    observer = EntitlementDiagnostics(output.append)
    for _ in range(LIMIT + 10):
        observer.after(object(), None, None, None, context(), False)
    assert len(output) == LIMIT
    assert snapshot((PREFIX + "allowed\n").encode(), truncated=True)["complete"] is False
    assert "private" not in str(snapshot(b"private data\n"))


def test_instrumentation_requires_exact_source_and_keeps_refusals() -> None:
    path = (
        Path(__file__).resolve().parents[3]
        / "services/backend/migrations/versions/0014_service_authority.sql"
    )
    source = path.read_text()
    start = source.index("CREATE OR REPLACE FUNCTION emailmonitor.network_entitlement_allowed(")
    start = source.index(" AS $$", start) + 6
    body = source[start : source.index("$$;", start)]
    changed = instrument(body)
    assert changed.count("RETURN false;") == body.count("RETURN false;") == 6
    assert changed.count("FOR SHARE NOWAIT") == body.count("FOR SHARE NOWAIT") == 2
    assert "EXCEPTION WHEN lock_not_available THEN" in changed
    assert "RETURN diagnostic_allowed;" in changed
    with pytest.raises(RuntimeError, match="Exact owned"):
        instrument(body + " ")


def test_malformed_owned_notice_cannot_be_silent_complete_evidence() -> None:
    raw = (PREFIX + "allowed\n" + PREFIX + "private untrusted reason\n").encode()
    value = snapshot(raw)
    assert value["complete"] is False
    assert "private" not in str(value)

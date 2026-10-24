"""Value-free notices for the existing opt-in synthetic UI worker only."""

import sys
from collections.abc import Callable
from typing import Any

from sqlalchemy import Engine, event
from sqlalchemy.sql.elements import TextClause

PREFIX = "EM_UI_ENTITLEMENT_V1 "
REASONS = ("allowed", "authority_denied", "lock_refused", "unavailable")
MESSAGES = {(PREFIX + value).encode(): value for value in REASONS[:3]}
STATEMENT = "SELECT emailmonitor.network_entitlement_allowed(:org,:operation,:job)"
LIMIT = 512


def write(value: str) -> None:
    if sys.__stderr__ is not None:
        sys.__stderr__.write(value)
        sys.__stderr__.flush()


def target(context: Any) -> bool:
    try:
        value = getattr(getattr(context, "compiled", None), "statement", None)
        return isinstance(value, TextClause) and value.text == STATEMENT
    except Exception:
        return False


class EntitlementDiagnostics:
    def __init__(self, writer: Callable[[str], None] = write) -> None:
        self.writer = writer
        self.emitted = 0

    def before(
        self,
        connection: Any,
        cursor: Any,
        statement: Any,
        parameters: Any,
        context: Any,
        executemany: Any,
    ) -> None:
        try:
            if target(context):
                context.em_entitlement_notices = None
                context.em_entitlement_notices = tuple(
                    connection.connection.driver_connection.notices
                )
        except Exception:
            pass

    def after(
        self,
        connection: Any,
        cursor: Any,
        statement: Any,
        parameters: Any,
        context: Any,
        executemany: Any,
    ) -> None:
        if self.emitted >= LIMIT or not target(context):
            return
        reason = "unavailable"
        try:
            previous = getattr(context, "em_entitlement_notices", None)
            if previous is None:
                raise ValueError("Missing notice boundary")
            notices = connection.connection.driver_connection.notices
            reasons = [
                MESSAGES[notice[b"M"]]
                for notice in notices
                if not any(notice is old for old in previous)
                and type(notice) is dict
                and type(notice.get(b"M")) is bytes
                and notice[b"M"] in MESSAGES
            ]
            reason = reasons[0] if len(reasons) == 1 else "unavailable"
        except Exception:
            pass
        try:
            self.emitted += 1
            self.writer(PREFIX + reason + "\n")
        except Exception:
            # Observation never consumes results, executes SQL, or replaces errors.
            pass

    def connect(self, engine: Engine) -> None:
        event.listen(engine, "before_cursor_execute", self.before)
        event.listen(engine, "after_cursor_execute", self.after)


def snapshot(raw: bytes, *, truncated: bool = False) -> dict[str, object]:
    counts = dict.fromkeys(REASONS, 0)
    last: str | None = None
    invalid = len(raw) > 65536
    for line in raw.splitlines():
        if line.startswith(PREFIX.encode()) and line not in {
            (PREFIX + reason).encode() for reason in REASONS
        }:
            invalid = True
        for reason in REASONS:
            if line == (PREFIX + reason).encode():
                counts[reason] += 1
                last = reason
    return {
        "counts": counts,
        "last_reason": last,
        "complete": not truncated
        and not invalid
        and 0 < sum(counts.values()) < LIMIT
        and counts["unavailable"] == 0,
    }

"""Constant-size supervisor observations; never worker-supplied diagnostics or payloads."""

from dataclasses import dataclass, replace
from enum import StrEnum


class Phase(StrEnum):
    IDLE = "idle"
    STARTUP = "startup"
    REQUEST_READ = "request_read"
    REQUEST_VALIDATE = "request_validate"
    ACQUIRE_PROVIDER = "acquire_provider"
    CALLBACK_SEND = "callback_send"
    CALLBACK_WAIT = "callback_wait"
    CALLBACK_RETURN = "callback_return"
    PARSE = "parse"
    RESULT_WRITE = "result_write"


class Origin(StrEnum):
    NONE = "none"
    PIPE = "pipe"
    LAUNCHER = "launcher"
    CALLBACK = "callback"
    PROVIDER = "provider"
    PARSER = "parser"
    WORKER = "worker"


class Failure(StrEnum):
    NONE = "none"
    TIMEOUT = "timeout"
    EOF = "eof"
    FRAMING = "framing"
    READ = "read"
    WRITE = "write"
    ALREADY_POISONED = "already_poisoned"
    STDERR_LIMIT = "stderr_limit"
    REFUSED = "refused"
    WORKER_EXIT = "worker_exit"


class CallbackKind(StrEnum):
    NONE = "none"
    CURRENT = "current"
    RESOURCE_ACQUIRE = "resource_acquire"
    RESOURCE_FINISH = "resource_finish"


@dataclass(frozen=True, slots=True)
class DiagnosticSnapshot:
    phase: Phase = Phase.IDLE
    origin: Origin = Origin.NONE
    failure: Failure = Failure.NONE
    callback_kind: CallbackKind = CallbackKind.NONE
    callback_sent: int = 0
    callback_received: int = 0
    callback_validated: int = 0


class DiagnosticTracker:
    """Single owner replaces frozen snapshots; readers never acquire a lock or perform I/O."""

    def __init__(self) -> None:
        self._snapshot = DiagnosticSnapshot()
        self._first_failure: dict[str, DiagnosticSnapshot] = {}

    @property
    def snapshot(self) -> DiagnosticSnapshot:
        return self._first_failure.get("first", self._snapshot)

    def phase(self, phase: Phase, kind: CallbackKind | None = None) -> None:
        if type(phase) is not Phase or (kind is not None and type(kind) is not CallbackKind):
            raise TypeError("Fixed diagnostic enum required")
        if self.snapshot.failure is Failure.NONE:
            self._snapshot = replace(
                self._snapshot,
                phase=phase,
                callback_kind=self._snapshot.callback_kind if kind is None else kind,
            )

    def count(self, event: str) -> None:
        if event not in ("sent", "received", "validated"):
            raise ValueError("Fixed callback counter required")
        if self.snapshot.failure is Failure.NONE:
            field = "callback_" + event
            self._snapshot = replace(
                self._snapshot, **{field: min(128, getattr(self._snapshot, field) + 1)}
            )

    def fail(self, failure: Failure, origin: Origin) -> None:
        if (
            type(failure) is not Failure
            or type(origin) is not Origin
            or failure is Failure.NONE
            or origin is Origin.NONE
        ):
            raise TypeError("Fixed failure enum required")
        if self.snapshot.failure is Failure.NONE:
            # setdefault retains one first failure even if owner cleanup races
            # with the channel's failure report; no lock or I/O enters callbacks.
            self._first_failure.setdefault(
                "first", replace(self._snapshot, failure=failure, origin=origin)
            )

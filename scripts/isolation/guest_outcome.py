"""Fixed future guest outcome metadata; no logs, payloads or control changes."""

import os
from collections.abc import Callable
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

from operator_ui_protocol import STAGES, DiagnosticFrame
from pydantic import TypeAdapter

HOST = frozenset(
    {
        "guard",
        "build",
        "create",
        "initial_validation",
        "conversation",
        "final_validation",
        "cleanup_container",
        "cleanup_image",
        "complete",
    }
)


class Trace:
    def __init__(self) -> None:
        self.stage = "guard"
        self.failure: str | None = None
        self.phase = "unavailable"
        self.reason = "unknown"
        self.error = "none"
        self.cleanup: set[str] = set()

    def label(self) -> str:
        stage = self.failure if self.failure is not None else self.stage
        if stage not in HOST or self.phase not in (*STAGES, "unavailable"):
            raise ValueError("Closed guest stages required")
        annotation = DiagnosticFrame.model_fields["reason"].annotation
        if annotation is None:
            raise ValueError("Closed guest reason annotation required")
        TypeAdapter(annotation).validate_python(self.reason, strict=True)
        if self.error not in {
            "none",
            "TimeoutError",
            "RuntimeError",
            "Error",
            "AssertionError",
            "ValueError",
            "UnexpectedError",
        }:
            raise ValueError("Closed guest error required")
        if not self.cleanup <= {"container", "image"}:
            raise ValueError("Exact owned cleanup kinds required")
        cleanup = "both" if len(self.cleanup) == 2 else next(iter(self.cleanup), "none")
        return (
            f"{stage}-phase_{self.phase}-error_{self.error}-reason_{self.reason}-cleanup_{cleanup}"
        )


_current: ContextVar[Trace | None] = ContextVar("owned_guest_outcome", default=None)
_first_failure: tuple[str, str] | None = None


def guest_stage(stage: str) -> None:
    if stage not in HOST:
        raise ValueError("Closed host stage required")
    trace = _current.get()
    if trace is not None:
        trace.stage = stage


def guest_failure(cleanup: str | None = None) -> None:
    trace = _current.get()
    if trace is not None:
        if trace.failure is None:
            trace.failure = trace.stage
        if cleanup is not None:
            if cleanup not in {"container", "image"}:
                raise ValueError("Exact owned cleanup kind required")
            trace.cleanup.add(cleanup)


def guest_frame(frame: DiagnosticFrame) -> None:
    trace = _current.get()
    if trace is not None:
        # Revalidate even constructed/mutated models; export only closed enums.
        fixed = DiagnosticFrame.model_validate(frame.model_dump())
        trace.phase = fixed.stage
        if fixed.kind == "failure":
            trace.reason, trace.error = fixed.reason, fixed.error or "none"


def observed_guest[**P, T](function: Callable[P, T]) -> Callable[P, T]:
    @wraps(function)
    def observed(*args: P.args, **kwargs: P.kwargs) -> T:
        global _first_failure
        trace = Trace()
        token = _current.set(trace)
        primary: BaseException | None = None
        try:
            return function(*args, **kwargs)
        except BaseException as error:
            primary = error
            guest_failure()
            raise
        finally:
            _current.reset(token)
            if os.environ.get("EM_GUEST_OUTCOME_REPORT") == "true":
                try:
                    target = os.environ["GITHUB_OUTPUT"]
                    label = trace.label()
                    if _first_failure is not None and _first_failure[0] == target:
                        label = _first_failure[1]
                    elif trace.failure is not None:
                        _first_failure = (target, label)
                    with Path(target).open("a", encoding="ascii") as output:
                        output.write("guest_outcome=" + label + "\n")
                except Exception:
                    if primary is None:
                        raise
                    primary.add_note("Fixed guest outcome reporting unavailable")

    return observed

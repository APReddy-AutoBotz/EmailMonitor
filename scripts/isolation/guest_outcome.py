"""Fixed future guest outcome metadata; no logs, payloads or control changes."""

import os
from collections.abc import Callable
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import get_args

from operator_ui_protocol import (
    OUTCOME_PHASES,
    STAGES,
    DiagnosticFrame,
    FocusExhaustion,
    InstalledLoginPhase,
    KeyboardAttemptTrace,
)
from pydantic import TypeAdapter

HOST = frozenset(
    {
        "guard",
        "build",
        "create",
        "initial_validation",
        "conversation",
        "conversation_result",
        "conversation_exit",
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
        self.login = "none"
        self.outcome = "none"
        self.focus: FocusExhaustion | str | None = None
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
        if self.login not in ("none", *get_args(InstalledLoginPhase)):
            raise ValueError("Closed installed login phase required")
        if self.outcome not in ("none", *OUTCOME_PHASES):
            raise ValueError("Closed outcome phase required")
        focus = "none"
        attempt = ""
        if isinstance(self.focus, FocusExhaustion):
            value = FocusExhaustion.model_validate(self.focus.model_dump())
            flags = "".join(
                "1" if flag is True else "0" if flag is False else "u"
                for flag in (
                    value.target_focused,
                    value.document_focused,
                    value.modal_open,
                    value.target_disabled,
                    value.target_in_dialog,
                    value.active_in_target_dialog,
                    value.target_inert,
                    value.target_tab_stop,
                )
            )
            focus = (
                f"{value.active_kind}.{value.target_kind or 'none'}."
                f"{value.active_control or 'none'}.{flags}"
            )
            if isinstance(value.attempt_trace, KeyboardAttemptTrace):
                observed = value.attempt_trace
                # Summarize existing passive observations, never export event arrays.
                # A truncated trace cannot establish absence after its capture cap.
                parts = [f"tabs{observed.tabs}", f"truncated{int(observed.truncated)}"]
                for kind, label in (
                    ("heading_focus", "heading"),
                    ("target_detached", "detached"),
                    ("target_replaced", "replaced"),
                ):
                    events = [event for event in observed.events if event.kind == kind]
                    first = str(events[0].tab) if events else "none"
                    parts.append(f"{label}{len(events)}at{first}")
                attempt = "-attempt_" + ".".join(parts)
            elif value.attempt_trace == "unavailable":
                attempt = "-attempt_unavailable"
        elif self.focus == "unavailable":
            focus = "unavailable"
        elif self.focus is not None:
            raise ValueError("Closed focus categories required")
        cleanup = "both" if len(self.cleanup) == 2 else next(iter(self.cleanup), "none")
        return (
            f"{stage}-phase_{self.phase}-error_{self.error}-reason_{self.reason}-cleanup_{cleanup}"
            f"-login_{self.login}"
            f"-outcome_{self.outcome}-focus_{focus}{attempt}"
        )


_current: ContextVar[Trace | None] = ContextVar("owned_guest_outcome", default=None)
_first_failure: tuple[str, str] | None = None
_case_trace: Trace | None = None


def reset_case_trace() -> None:
    global _case_trace
    _case_trace = None


def case_categories() -> tuple[str, str]:
    if _case_trace is None:
        return "unavailable", "unavailable"
    _case_trace.label()  # Revalidate, including mutated nested models.
    return _case_trace.failure or _case_trace.stage, _case_trace.phase


def case_failure_details() -> tuple[str, str]:
    """Return only the existing validated fixed guest failure categories."""
    if _case_trace is None:
        return "unavailable", "unavailable"
    _case_trace.label()
    return _case_trace.error, _case_trace.reason


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
            trace.login = fixed.installed_login_phase or "none"
            trace.outcome = fixed.outcome_phase or "none"
            trace.focus = fixed.focus_exhaustion


def observed_guest[**P, T](function: Callable[P, T]) -> Callable[P, T]:
    @wraps(function)
    def observed(*args: P.args, **kwargs: P.kwargs) -> T:
        global _first_failure, _case_trace
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
            if (
                os.environ.get("EM_GUEST_OUTCOME_REPORT") == "true"
                or os.environ.get("EM_XML_CASE_OUTCOME_REPORT") == "true"
            ):
                try:
                    label = trace.label()
                    if os.environ.get("EM_XML_CASE_OUTCOME_REPORT") == "true":
                        if _case_trace is None or _case_trace.failure is None:
                            _case_trace = trace
                    if os.environ.get("EM_GUEST_OUTCOME_REPORT") == "true":
                        target = os.environ["GITHUB_OUTPUT"]
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

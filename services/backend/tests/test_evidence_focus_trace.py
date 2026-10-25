"""Close diagnostics preserve the actual focus decision and exclude private payloads."""

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from operator_ui_protocol import DiagnosticFrame, EvidenceFocusTrace
from playwright.async_api import JSHandle, Page
from pydantic import ValidationError

STATE = {
    "event": "assertion",
    "dialog_connected": False,
    "dialog_open": False,
    "close_seen": True,
    "opener_connected": True,
    "contacts_present": True,
    "active_kind": "opener",
}
TRACE = {"states": [STATE], "truncated": False}


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("snapshot", [TRACE, None, {"private": "must not escape"}])
def test_diagnostic_never_changes_current_opener_focus_decision(
    restored: bool,
    snapshot: object,
) -> None:
    from operator_ui_acceptance import check_evidence_focus

    target = SimpleNamespace(
        evaluate=AsyncMock(return_value={"restored": restored, "trace": snapshot})
    )
    page = SimpleNamespace(get_by_role=lambda *args, **kwargs: SimpleNamespace(first=target))
    trace = SimpleNamespace(dispose=AsyncMock())
    actual, evidence = asyncio.run(check_evidence_focus(cast(Page, page), cast(JSHandle, trace)))
    assert actual is restored
    assert (
        isinstance(evidence, EvidenceFocusTrace) if snapshot == TRACE else evidence == "unavailable"
    )
    assert target.evaluate.await_count == 1
    trace.dispose.assert_awaited_once()
    assert "node === document.activeElement" in target.evaluate.await_args.args[0]


def test_original_focus_read_failure_is_not_retried_or_hidden() -> None:
    from operator_ui_acceptance import check_evidence_focus

    target = SimpleNamespace(evaluate=AsyncMock(side_effect=RuntimeError("original failure")))
    page = SimpleNamespace(get_by_role=lambda *args, **kwargs: SimpleNamespace(first=target))
    trace = SimpleNamespace(dispose=AsyncMock())
    with pytest.raises(RuntimeError, match="original failure"):
        asyncio.run(check_evidence_focus(cast(Page, page), cast(JSHandle, trace)))
    assert target.evaluate.await_count == 1
    trace.dispose.assert_awaited_once()


@pytest.mark.parametrize("phase", ["escape_close", "button_close"])
@pytest.mark.parametrize(
    "patch",
    [
        {"stage": "url_worker"},
        {"reason": "unknown"},
        {"error": "TimeoutError"},
        {"kind": "stage", "error": None},
        {"evidence_phase": "open"},
        {"evidence_focus_trace": {"states": [STATE] * 9, "truncated": False}},
        {
            "evidence_focus_trace": {
                "states": [{**STATE, "active_kind": "private-value"}],
                "truncated": False,
            }
        },
        {
            "evidence_focus_trace": {
                "states": [{**STATE, "text": "private-value"}],
                "truncated": False,
            }
        },
        {"evidence_focus_trace": {"states": [{**STATE, "close_seen": "true"}], "truncated": False}},
    ],
)
def test_trace_is_bounded_strict_and_confined_to_exact_failure(
    phase: str, patch: dict[str, object]
) -> None:
    frame = {
        "kind": "failure",
        "stage": "evidence_review",
        "reason": "dialog_focus_restore",
        "error": "RuntimeError",
        "evidence_phase": phase,
        "evidence_focus_trace": TRACE,
    }
    assert DiagnosticFrame.model_validate(frame).evidence_focus_trace is not None
    with pytest.raises(ValidationError):
        DiagnosticFrame.model_validate({**frame, **patch})

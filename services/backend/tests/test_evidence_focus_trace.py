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


@pytest.mark.parametrize("final_focus", ["opener", "body"])
def test_recorded_native_hidden_precedes_close_completion_and_focus(final_focus: str) -> None:
    """Replay the observed browser order; detached readiness must not excuse wrong focus."""
    from operator_ui_acceptance import check_evidence_focus, wait_evidence_closed

    class Replay:
        # Fixed categories from the actual Escape and button-close browser traces.
        states = [
            (True, True, "dialog"),
            (True, False, "dialog"),
            (True, False, final_focus),
            (False, False, final_focus),
        ]
        index = 0
        waits: list[tuple[str, str]] = []

        def locator(self, selector: str) -> object:
            assert selector == 'dialog[aria-labelledby="evidence-title"]'

            async def wait_for(*, state: str) -> None:
                self.waits.append((selector, state))
                assert state == "detached"
                while self.states[self.index][0]:
                    self.index += 1
                    await asyncio.sleep(0)

            return SimpleNamespace(wait_for=wait_for)

        def get_by_role(self, role: str, *, name: str, exact: bool) -> object:
            assert (role, name, exact) == ("button", "Evidence and review", True)

            async def evaluate(*args: object) -> object:
                return {"restored": self.states[self.index][2] == "opener", "trace": None}

            return SimpleNamespace(first=SimpleNamespace(evaluate=evaluate))

    replay = Replay()
    replay.index = 1  # Native hidden readiness can return here, before the close handler.
    assert asyncio.run(check_evidence_focus(cast(Page, replay), None))[0] is False
    asyncio.run(wait_evidence_closed(cast(Page, replay)))
    assert asyncio.run(check_evidence_focus(cast(Page, replay), None))[0] is (
        final_focus == "opener"
    )
    assert replay.index == 3 and len(replay.waits) == 1


def test_missing_close_completion_keeps_original_timeout_failure() -> None:
    from operator_ui_acceptance import wait_evidence_closed

    wait = AsyncMock(side_effect=TimeoutError("unchanged page deadline"))
    page = SimpleNamespace(locator=lambda _: SimpleNamespace(wait_for=wait))
    with pytest.raises(TimeoutError, match="unchanged page deadline"):
        asyncio.run(wait_evidence_closed(cast(Page, page)))
    wait.assert_awaited_once_with(state="detached")


@pytest.mark.parametrize(
    "message,reason",
    [
        ("Control not reachable by keyboard", "keyboard_focus"),
        ("Control not reachable by keyboard: private", "unknown"),
        ("private exception content", "unknown"),
    ],
)
def test_installed_keyboard_failure_preserves_only_exact_fixed_category(
    message: str, reason: str
) -> None:
    from installed_operator_redirects import InstalledDiagnostics
    from operator_ui_protocol import failure_reason

    error = RuntimeError(message)
    fixed = InstalledDiagnostics().capture(error, failure_reason(error), None)
    assert fixed == {"error": "RuntimeError", "reason": reason}
    assert message not in str(fixed)
    frame = {"kind": "failure", "stage": "evidence_review", "evidence_phase": "reason", **fixed}
    assert DiagnosticFrame.model_validate(frame).evidence_phase == "reason"

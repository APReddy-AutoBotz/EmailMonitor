"""The optional focus snapshot cannot turn the keyboard limit into success."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from operator_ui_protocol import DiagnosticFrame, FocusExhaustion
from playwright.async_api import Locator, Page
from pydantic import ValidationError


@pytest.mark.parametrize(
    "snapshot",
    [
        {
            "target_focused": True,
            "document_focused": True,
            "modal_open": False,
            "active_kind": "target",
        },
        {
            "target_focused": False,
            "document_focused": False,
            "modal_open": False,
            "active_kind": "body",
        },
        RuntimeError("untrusted diagnostic failure"),
        {"target_focused": False, "private_value": "must not be emitted"},
    ],
)
def test_focus_exhaustion_preserves_original_failure(
    monkeypatch: pytest.MonkeyPatch, snapshot: object
) -> None:
    import asyncio

    import operator_ui_acceptance as guest

    target = SimpleNamespace(
        wait_for=AsyncMock(), evaluate=AsyncMock(side_effect=[False] * 100 + [snapshot])
    )
    keyboard = SimpleNamespace(press=AsyncMock())
    monkeypatch.setattr(guest, "expect", lambda _: SimpleNamespace(to_be_enabled=AsyncMock()))
    with pytest.raises(RuntimeError, match="^Control not reachable by keyboard$"):
        asyncio.run(
            guest.focus(cast(Page, SimpleNamespace(keyboard=keyboard)), cast(Locator, target))
        )
    assert keyboard.press.await_count == 100
    assert all(call.args == ("Tab",) for call in keyboard.press.await_args_list)
    if isinstance(snapshot, dict) and "active_kind" in snapshot:
        assert isinstance(guest.focus_exhaustion, FocusExhaustion)
        assert guest.focus_exhaustion.model_dump(exclude_none=True) == snapshot
    else:
        assert guest.focus_exhaustion == "unavailable"


def test_successful_focus_clears_prior_snapshot_without_extra_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    import operator_ui_acceptance as guest

    guest.focus_exhaustion = "unavailable"
    target = SimpleNamespace(wait_for=AsyncMock(), evaluate=AsyncMock(return_value=True))
    keyboard = SimpleNamespace(press=AsyncMock())
    monkeypatch.setattr(guest, "expect", lambda _: SimpleNamespace(to_be_enabled=AsyncMock()))
    asyncio.run(guest.focus(cast(Page, SimpleNamespace(keyboard=keyboard)), cast(Locator, target)))
    assert guest.focus_exhaustion is None
    assert target.evaluate.await_count == 1
    keyboard.press.assert_not_awaited()


def test_pending_snapshot_is_cancelled_without_masking_original_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    import operator_ui_acceptance as guest

    reads = 0
    cancelled = False

    async def evaluate(_: str) -> object:
        nonlocal reads, cancelled
        reads += 1
        if reads <= 100:
            return False
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True
        return None

    target = SimpleNamespace(wait_for=AsyncMock(), evaluate=evaluate)
    keyboard = SimpleNamespace(press=AsyncMock())
    monkeypatch.setattr(guest, "expect", lambda _: SimpleNamespace(to_be_enabled=AsyncMock()))
    with pytest.raises(RuntimeError, match="^Control not reachable by keyboard$"):
        asyncio.run(
            guest.focus(cast(Page, SimpleNamespace(keyboard=keyboard)), cast(Locator, target))
        )
    assert cancelled and reads == 101
    assert keyboard.press.await_count == 100
    assert guest.focus_exhaustion == "unavailable"


@pytest.mark.parametrize(
    "extra",
    [
        {"kind": "stage", "error": None, "reason": "unknown"},
        {"reason": "unknown"},
        {"error": "AssertionError"},
        {
            "focus_exhaustion": {
                "target_focused": "true",
                "document_focused": True,
                "modal_open": False,
                "active_kind": "target",
            }
        },
        {
            "focus_exhaustion": {
                "target_focused": True,
                "document_focused": True,
                "modal_open": False,
                "active_kind": "secret",
            }
        },
        {
            "focus_exhaustion": {
                "target_focused": True,
                "document_focused": True,
                "modal_open": False,
                "active_kind": "target",
                "text": "secret",
            }
        },
    ],
)
def test_focus_snapshot_is_closed_and_failure_only(extra: dict[str, object]) -> None:
    frame = {
        "kind": "failure",
        "stage": "url_worker",
        "error": "RuntimeError",
        "reason": "keyboard_focus",
        "focus_exhaustion": "unavailable",
    }
    assert DiagnosticFrame.model_validate(frame).focus_exhaustion == "unavailable"
    with pytest.raises(ValidationError):
        DiagnosticFrame.model_validate({**frame, **extra})


@pytest.mark.parametrize(
    "phase", ["contacts", "open", "citation", "reason", "save", "closed", "returned"]
)
def test_evidence_action_is_fixed_and_failure_only(phase: str) -> None:
    frame = {
        "kind": "failure",
        "stage": "evidence_review",
        "error": "RuntimeError",
        "reason": "keyboard_focus",
        "evidence_phase": phase,
    }
    assert DiagnosticFrame.model_validate(frame).evidence_phase == phase
    for patch in (
        {"stage": "url_worker"},
        {"kind": "stage", "error": None, "reason": "unknown"},
        {"evidence_phase": phase + ":private-value"},
    ):
        with pytest.raises(ValidationError):
            DiagnosticFrame.model_validate({**frame, **patch})


@pytest.mark.parametrize(
    "delivery", ["not_requested", "request_received", "asset_verified", "fulfilled"]
)
def test_callback_delivery_is_fixed_and_exact_phase_only(delivery: str) -> None:
    frame = {
        "kind": "failure",
        "stage": "keyword_worker",
        "error": "TimeoutError",
        "reason": "installed_login_deadline",
        "installed_login_phase": "callback_document",
        "installed_callback_delivery": delivery,
    }
    assert DiagnosticFrame.model_validate(frame).installed_callback_delivery == delivery
    for patch in (
        {"installed_login_phase": "callback_complete"},
        {"stage": "evidence_review"},
        {"installed_callback_delivery": delivery + ":private-url"},
    ):
        with pytest.raises(ValidationError):
            DiagnosticFrame.model_validate({**frame, **patch})


def test_focus_target_metadata_never_accepts_dom_values() -> None:
    snapshot = {
        "target_focused": False,
        "document_focused": True,
        "modal_open": True,
        "active_kind": "other",
        "target_kind": "textarea",
        "active_control": "button",
        "target_disabled": False,
        "target_in_dialog": True,
        "active_in_target_dialog": True,
        "target_inert": False,
        "target_tab_stop": True,
    }
    assert FocusExhaustion.model_validate(snapshot).model_dump() == snapshot
    for patch in (
        {"target_kind": "private-label"},
        {"active_control": "private-value"},
        {"target_disabled": "false"},
        {"target_in_dialog": 1},
        {"text": "private"},
    ):
        with pytest.raises(ValidationError):
            FocusExhaustion.model_validate({**snapshot, **patch})

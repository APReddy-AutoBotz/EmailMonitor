"""The optional focus snapshot cannot turn the keyboard limit into success."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from operator_ui_protocol import DiagnosticFrame
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
def test_focus_exhaustion_preserves_original_failure(monkeypatch, snapshot):
    import asyncio

    import operator_ui_acceptance as guest

    target = SimpleNamespace(
        wait_for=AsyncMock(), evaluate=AsyncMock(side_effect=[False] * 100 + [snapshot])
    )
    keyboard = SimpleNamespace(press=AsyncMock())
    monkeypatch.setattr(guest, "expect", lambda _: SimpleNamespace(to_be_enabled=AsyncMock()))
    with pytest.raises(RuntimeError, match="^Control not reachable by keyboard$"):
        asyncio.run(guest.focus(SimpleNamespace(keyboard=keyboard), target))
    assert keyboard.press.await_count == 100
    assert all(call.args == ("Tab",) for call in keyboard.press.await_args_list)
    if isinstance(snapshot, dict) and "active_kind" in snapshot:
        assert guest.focus_exhaustion.model_dump() == snapshot
    else:
        assert guest.focus_exhaustion == "unavailable"


def test_successful_focus_clears_prior_snapshot_without_extra_read(monkeypatch):
    import asyncio

    import operator_ui_acceptance as guest

    guest.focus_exhaustion = "unavailable"
    target = SimpleNamespace(wait_for=AsyncMock(), evaluate=AsyncMock(return_value=True))
    keyboard = SimpleNamespace(press=AsyncMock())
    monkeypatch.setattr(guest, "expect", lambda _: SimpleNamespace(to_be_enabled=AsyncMock()))
    asyncio.run(guest.focus(SimpleNamespace(keyboard=keyboard), target))
    assert guest.focus_exhaustion is None
    assert target.evaluate.await_count == 1
    keyboard.press.assert_not_awaited()


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
def test_focus_snapshot_is_closed_and_failure_only(extra):
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

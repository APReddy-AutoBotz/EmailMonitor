"""Synthetic doubles for deletion diagnostics; the guarded browser is not run."""

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import operator_ui_acceptance as guest
import pytest
from operator_ui_protocol import DiagnosticFrame
from playwright.async_api import Locator, Page
from pydantic import ValidationError


@pytest.mark.parametrize("commit", [False, True])
@pytest.mark.parametrize("failure_at", [None, "focus", "key", "job", "exports", "purge"])
def test_confirmation_preserves_sequence_and_first_failure(
    monkeypatch: pytest.MonkeyPatch, commit: bool, failure_at: str | None
) -> None:
    prefix = "confirm" if commit else "cancel"
    original = RuntimeError("private synthetic failure")
    actions: list[str] = []
    phases: list[str] = []
    target, dialog = object(), object()

    async def action(name: str) -> None:
        actions.append(name)
        if failure_at == name:
            raise original

    async def focus(page: Page, locator: Locator) -> None:
        assert locator is target
        await action("focus")

    async def key(value: str) -> None:
        assert value == "Enter"
        await action("key")

    async def contains(value: str) -> None:
        label = {
            "synthetic-job": "job",
            "all existing exports in this organization": "exports",
            "Physical purge": "purge",
        }[value]
        await action(label)

    page = SimpleNamespace(
        keyboard=SimpleNamespace(press=key),
        get_by_role=lambda role: dialog if role == "dialog" else None,
    )
    monkeypatch.setattr(guest, "focus", focus)
    monkeypatch.setattr(guest, "expect", lambda locator: SimpleNamespace(to_contain_text=contains))
    operation = guest.deletion_open_confirmation(
        cast(Page, page), cast(Locator, target), "synthetic-job", commit, phases.append
    )
    if failure_at:
        with pytest.raises(RuntimeError) as caught:
            asyncio.run(operation)
        assert caught.value is original
    else:
        assert asyncio.run(operation) is dialog
    expected_actions = ["focus", "key", "job", "exports", "purge"]
    count = expected_actions.index(failure_at) + 1 if failure_at else len(expected_actions)
    assert actions == expected_actions[:count]
    assert (
        phases
        == [
            prefix + "_open_focus",
            prefix + "_open_key",
            prefix + "_dialog_job",
            prefix + "_dialog_exports",
            prefix + "_dialog_purge",
        ][:count]
    )


@pytest.mark.parametrize("failure_at", [None, "focus", "key"])
def test_open_job_preserves_keyboard_action_and_failure(
    monkeypatch: pytest.MonkeyPatch, failure_at: str | None
) -> None:
    original = RuntimeError("private synthetic failure")
    phases: list[str] = []
    target = object()
    keyboard = SimpleNamespace(
        press=AsyncMock(side_effect=original if failure_at == "key" else None)
    )
    focus = AsyncMock(side_effect=original if failure_at == "focus" else None)
    monkeypatch.setattr(guest, "focus", focus)
    page = cast(Page, SimpleNamespace(keyboard=keyboard))
    operation = guest.deletion_open_job(page, cast(Locator, target), phases.append)
    if failure_at:
        with pytest.raises(RuntimeError) as caught:
            asyncio.run(operation)
        assert caught.value is original
    else:
        asyncio.run(operation)
    focus.assert_awaited_once_with(page, target)
    if failure_at == "focus":
        keyboard.press.assert_not_awaited()
        assert phases == ["open_job_focus"]
    else:
        keyboard.press.assert_awaited_once_with("Enter")
        assert phases == ["open_job_focus", "open_job_key"]


@pytest.mark.parametrize("value", ["absent", "closed", "open_box", "open_no_box", "private", {}])
def test_dialog_snapshot_has_only_fixed_categories(value: object) -> None:
    page = cast(Page, SimpleNamespace(evaluate=AsyncMock(return_value=value)))
    result = asyncio.run(guest.deletion_dialog_snapshot(page))
    assert result == (
        value if value in ["absent", "closed", "open_box", "open_no_box"] else "unavailable"
    )


def test_dialog_snapshot_failure_does_not_escape() -> None:
    page = cast(Page, SimpleNamespace(evaluate=AsyncMock(side_effect=RuntimeError("private"))))
    assert asyncio.run(guest.deletion_dialog_snapshot(page)) == "unavailable"


def test_dialog_snapshot_deadline_cancels_owned_observation() -> None:
    cancelled = False

    async def pending(_: str) -> None:
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True

    page = cast(Page, SimpleNamespace(evaluate=pending))
    assert asyncio.run(guest.deletion_dialog_snapshot(page)) == "unavailable"
    assert cancelled


@pytest.mark.parametrize(
    "changes",
    [
        {"job_deletion_dialog_state": "private"},
        {"job_deletion_phase": "confirm_open_key"},
        {"stage": "evidence_review"},
        {"kind": "stage", "error": None},
    ],
)
def test_dialog_state_refuses_unlisted_or_wrong_scope(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DiagnosticFrame.model_validate(
            {
                "kind": "failure",
                "stage": "job_deletion",
                "error": "RuntimeError",
                "job_deletion_phase": "confirm_dialog_job",
                "job_deletion_dialog_state": "open_box",
                **changes,
            }
        )

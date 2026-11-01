"""Synthetic doubles for deletion diagnostics; the guarded browser is not run."""

import asyncio
import json
import subprocess
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
    observations: list[str] = []
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
        evaluate=AsyncMock(return_value="open_box"),
    )
    monkeypatch.setattr(guest, "focus", focus)
    monkeypatch.setattr(guest, "expect", lambda locator: SimpleNamespace(to_contain_text=contains))
    operation = guest.deletion_open_confirmation(
        cast(Page, page),
        cast(Locator, target),
        "synthetic-job",
        commit,
        phases.append,
        observations.append,
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
    assert observations == (["open_box"] if failure_at == "job" else [])
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


@pytest.mark.parametrize("failure_at", [None, "verified", "fenced", "purge"])
def test_receipt_assertions_observe_before_context_exit_and_preserve_failure(
    monkeypatch: pytest.MonkeyPatch, failure_at: str | None
) -> None:
    original = RuntimeError("private synthetic failure")
    actions: list[str] = []
    phases: list[str] = []
    observations: list[str] = []
    in_context = True

    async def contains(value: str) -> None:
        label = {
            "Verified deletion receipt:": "verified",
            "is fenced": "fenced",
            "No physical purge was requested": "purge",
        }[value]
        actions.append(label)
        if failure_at == label:
            raise original

    async def evaluate(_: str) -> str:
        assert in_context
        return "submitted_unverified"

    monkeypatch.setattr(guest, "expect", lambda _: SimpleNamespace(to_contain_text=contains))
    page = cast(Page, SimpleNamespace(evaluate=evaluate))
    operation = guest.deletion_receipt_checks(
        page, cast(Locator, object()), phases.append, observations.append
    )
    if failure_at:
        with pytest.raises(RuntimeError) as caught:
            asyncio.run(operation)
        assert caught.value is original
    else:
        asyncio.run(operation)
    in_context = False
    expected_actions = ["verified", "fenced", "purge"]
    count = expected_actions.index(failure_at) + 1 if failure_at else len(expected_actions)
    assert actions == expected_actions[:count]
    assert phases == ["receipt_verified", "receipt_fenced", "receipt_no_purge"][:count]
    assert observations == (["submitted_unverified"] if failure_at else [])


def test_receipt_observer_failure_never_masks_assertion(monkeypatch: pytest.MonkeyPatch) -> None:
    original = AssertionError("private assertion")
    monkeypatch.setattr(
        guest, "expect", lambda _: SimpleNamespace(to_contain_text=AsyncMock(side_effect=original))
    )
    page = cast(Page, SimpleNamespace(evaluate=AsyncMock(return_value="other")))

    def refuse(_: str) -> None:
        raise RuntimeError("observer failure")

    with pytest.raises(AssertionError) as caught:
        asyncio.run(
            guest.deletion_receipt_checks(page, cast(Locator, object()), lambda _: None, refuse)
        )
    assert caught.value is original


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
    "value",
    [
        "region_absent",
        "verified_fenced",
        "verified_other",
        "submitted_unverified",
        "awaiting_submission",
        "other",
        "private synthetic content",
        {},
    ],
)
def test_receipt_snapshot_never_returns_arbitrary_content(value: object) -> None:
    page = cast(Page, SimpleNamespace(evaluate=AsyncMock(return_value=value)))
    result = asyncio.run(guest.deletion_receipt_snapshot(page))
    allowed = [
        "region_absent",
        "verified_fenced",
        "verified_other",
        "submitted_unverified",
        "awaiting_submission",
        "other",
    ]
    assert result == (value if value in allowed else "unavailable")


def test_receipt_snapshot_failure_and_deadline_remain_unavailable() -> None:
    cancelled = False

    async def pending(_: str) -> None:
        nonlocal cancelled
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True

    page = cast(Page, SimpleNamespace(evaluate=pending))
    assert asyncio.run(guest.deletion_receipt_snapshot(page)) == "unavailable"
    assert cancelled
    page = cast(Page, SimpleNamespace(evaluate=AsyncMock(side_effect=RuntimeError("private"))))
    assert asyncio.run(guest.deletion_receipt_snapshot(page)) == "unavailable"


def test_receipt_snapshot_expression_classifies_only_fixed_synthetic_states() -> None:
    expressions: list[str] = []

    async def capture(expression: str) -> str:
        expressions.append(expression)
        return "other"

    page = cast(Page, SimpleNamespace(evaluate=capture))
    assert asyncio.run(guest.deletion_receipt_snapshot(page)) == "other"
    assert len(expressions) == 1
    program = r"""
const fs = require('fs');
const classify = eval('(' + fs.readFileSync(0, 'utf8') + ')');
const cases = [
  null,
  {text: 'Verified deletion receipt: synthetic. Job synthetic is fenced.', select: false},
  {text: 'Verified deletion receipt: synthetic. Job synthetic is purged.', select: false},
  {text: 'A deletion request was submitted. Its outcome is unverified here.', select: false},
  {text: '', select: true},
  {text: 'unrelated synthetic content', select: false},
];
const result = cases.map(value => {
  global.document = {querySelector: () => value === null ? null : {
    textContent: value.text,
    querySelector: () => value.select ? {} : null,
  }};
  return classify();
});
process.stdout.write(JSON.stringify(result));
"""
    result = subprocess.run(
        ["node", "-e", program],
        input=expressions[0],
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == [
        "region_absent",
        "verified_fenced",
        "verified_other",
        "submitted_unverified",
        "awaiting_submission",
        "other",
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"job_deletion_receipt_state": "private"},
        {"job_deletion_phase": "confirm_open_key"},
        {"stage": "evidence_review"},
        {"kind": "stage", "error": None},
    ],
)
def test_receipt_state_refuses_unlisted_or_wrong_scope(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DiagnosticFrame.model_validate(
            {
                "kind": "failure",
                "stage": "job_deletion",
                "error": "RuntimeError",
                "job_deletion_phase": "receipt_verified",
                "job_deletion_receipt_state": "submitted_unverified",
                **changes,
            }
        )


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

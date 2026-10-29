"""Authored local trace tests; never enable the genuine-CI browser guard."""

from pathlib import Path
from typing import get_args

import guest_outcome as trace
import pytest
from operator_ui_protocol import (
    OUTCOME_PHASES,
    DiagnosticFrame,
    FocusExhaustion,
    InstalledExportStep,
    InstalledLoginPhase,
    OutcomePhase,
)


@pytest.fixture
def output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "output"
    monkeypatch.setenv("EM_GUEST_OUTCOME_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(path))
    monkeypatch.setattr(trace, "_first_failure", None)
    return path


@pytest.mark.parametrize("stage", sorted(trace.HOST - {"complete"}))
def test_fixed_host_failure_preserves_original_exception(output: Path, stage: str) -> None:
    original = RuntimeError("private sentinel must not be metadata")

    @trace.observed_guest
    def synthetic() -> None:
        trace.guest_stage(stage)
        raise original

    with pytest.raises(RuntimeError) as caught:
        synthetic()
    assert caught.value is original
    assert output.read_text() == (
        f"guest_outcome={stage}-phase_unavailable-error_none-reason_unknown-cleanup_none-login_none-outcome_none-focus_none\n"
    )
    assert trace._current.get() is None


def test_first_failure_survives_cleanup_and_later_success(output: Path) -> None:
    primary = AssertionError("private sentinel")

    @trace.observed_guest
    def failed() -> None:
        try:
            trace.guest_stage("conversation")
            trace.guest_frame(
                DiagnosticFrame(
                    kind="failure",
                    stage="evidence_review",
                    error="AssertionError",
                    reason="dialog_focus_restore",
                )
            )
            raise primary
        except BaseException:
            trace.guest_failure()
            raise
        finally:
            trace.guest_stage("cleanup_container")
            trace.guest_failure("container")
            trace.guest_stage("cleanup_image")
            trace.guest_failure("image")

    @trace.observed_guest
    def success() -> int:
        trace.guest_stage("complete")
        return 7

    with pytest.raises(AssertionError) as caught:
        failed()
    assert caught.value is primary
    assert success() == 7
    lines = output.read_text().splitlines()
    assert len(lines) == 2 and lines[0] == lines[1]
    assert lines[0] == (
        "guest_outcome=conversation-phase_evidence_review-error_AssertionError-"
        "reason_dialog_focus_restore-cleanup_both-login_none-outcome_none-focus_none"
    )


@pytest.mark.parametrize(
    "phase",
    [
        "navigate",
        "format",
        "preview_activate",
        "preview_wait",
        "create",
        "row_wait",
        "ready_wait",
        "refresh",
        "download_activate",
        "download_wait",
        "verify",
    ],
)
def test_installed_export_failure_reports_fixed_step_and_preserves_failure(
    output: Path, phase: str
) -> None:
    original = TimeoutError("synthetic private detail")

    @trace.observed_guest
    def failed() -> None:
        trace.guest_stage("conversation")
        trace.guest_frame(
            DiagnosticFrame(
                kind="failure",
                stage="export_preview",
                error="TimeoutError",
                installed_export_step=InstalledExportStep.model_validate(
                    {"phase": phase, "format": "xlsx"}
                ),
            )
        )
        raise original

    with pytest.raises(TimeoutError) as caught:
        failed()
    assert caught.value is original
    result = output.read_text()
    assert f"-export_{phase}.xlsx" in result
    assert "synthetic private detail" not in result


def test_success_and_owned_cleanup_are_not_skipped(output: Path, tmp_path: Path) -> None:
    owned = tmp_path / "owned"
    owned.mkdir()

    @trace.observed_guest
    def success() -> str:
        for stage in ("build", "create", "initial_validation", "conversation", "final_validation"):
            trace.guest_stage(stage)
        try:
            return "unchanged"
        finally:
            trace.guest_stage("cleanup_container")
            owned.rmdir()
            trace.guest_stage("cleanup_image")
            trace.guest_stage("complete")

    assert success() == "unchanged" and not owned.exists()
    assert output.read_text().startswith("guest_outcome=complete-")


def test_mutated_guest_model_cannot_export_payload(output: Path) -> None:
    frame = DiagnosticFrame(kind="stage", stage="evidence_review")
    frame.stage = "private@example.invalid"

    @trace.observed_guest
    def synthetic() -> None:
        trace.guest_stage("conversation")
        trace.guest_frame(frame)

    with pytest.raises(ValueError):
        synthetic()
    assert "private" not in output.read_text()
    assert "phase_unavailable" in output.read_text()


def test_reporting_failure_does_not_replace_original(
    output: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(output / "missing"))
    original = AssertionError("original")

    @trace.observed_guest
    def synthetic() -> None:
        raise original

    with pytest.raises(AssertionError) as caught:
        synthetic()
    assert caught.value is original
    assert original.__notes__ == ["Fixed guest outcome reporting unavailable"]


def test_exit_status_and_default_no_output(output: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    @trace.observed_guest
    def exiting() -> None:
        trace.guest_stage("conversation")
        raise SystemExit(23)

    with pytest.raises(SystemExit) as caught:
        exiting()
    assert caught.value.code == 23
    assert output.read_text().startswith("guest_outcome=conversation-")
    output.unlink()
    monkeypatch.delenv("EM_GUEST_OUTCOME_REPORT")
    with pytest.raises(SystemExit) as caught:
        exiting()
    assert caught.value.code == 23
    assert not output.exists()


@pytest.mark.parametrize("phase", get_args(InstalledLoginPhase))
def test_existing_login_phase_preserves_timeout_and_first_failure(
    output: Path, phase: InstalledLoginPhase
) -> None:
    original = TimeoutError("private synthetic session sentinel")

    @trace.observed_guest
    def failed() -> None:
        trace.guest_stage("conversation")
        trace.guest_frame(
            DiagnosticFrame(
                kind="failure",
                stage="keyword_worker",
                error="TimeoutError",
                reason="installed_login_deadline",
                installed_login_phase=phase,
            )
        )
        raise original

    @trace.observed_guest
    def success() -> int:
        trace.guest_stage("complete")
        return 7

    with pytest.raises(TimeoutError) as caught:
        failed()
    assert caught.value is original
    assert success() == 7
    lines = output.read_text().splitlines()
    assert (
        lines
        == [
            "guest_outcome=conversation-phase_keyword_worker-error_TimeoutError-"
            "reason_installed_login_deadline-cleanup_none-login_"
            + phase
            + "-outcome_none-focus_none"
        ]
        * 2
    )
    assert "private" not in output.read_text()
    assert trace._current.get() is None


def test_invalid_login_phase_cannot_enter_metadata(output: Path) -> None:
    frame = DiagnosticFrame(
        kind="failure",
        stage="keyword_worker",
        error="TimeoutError",
        reason="installed_login_deadline",
        installed_login_phase="organization",
    )
    object.__setattr__(frame, "installed_login_phase", "private@example.invalid")

    @trace.observed_guest
    def failed() -> None:
        trace.guest_frame(frame)

    with pytest.raises(ValueError):
        failed()
    assert "private" not in output.read_text()
    assert "login_none" in output.read_text()
    value = trace.Trace()
    value.login = "private@example.invalid"
    with pytest.raises(ValueError, match="Closed installed login phase"):
        value.label()


@pytest.mark.parametrize(
    "delivery", ["not_requested", "request_received", "asset_verified", "fulfilled"]
)
def test_callback_delivery_metadata_preserves_timeout_and_is_allowlisted(
    output: Path, delivery: str
) -> None:
    original = TimeoutError("private synthetic session sentinel")

    @trace.observed_guest
    def failed() -> None:
        trace.guest_stage("conversation")
        frame = DiagnosticFrame.model_validate(
            {
                "kind": "failure",
                "stage": "keyword_worker",
                "error": "TimeoutError",
                "reason": "installed_login_deadline",
                "installed_login_phase": "callback_document",
                "installed_callback_delivery": delivery,
            }
        )
        trace.guest_frame(frame)
        raise original

    with pytest.raises(TimeoutError) as caught:
        failed()
    assert caught.value is original
    assert output.read_text().strip().endswith("-callback_" + delivery)
    assert "private" not in output.read_text()
    value = trace.Trace()
    value.login = "callback_document"
    value.callback = "private@example.invalid"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="Closed callback delivery"):
        value.label()
    value.callback = "fulfilled"
    value.login = "none"
    with pytest.raises(ValueError, match="Closed callback delivery"):
        value.label()


@pytest.mark.parametrize("phase", OUTCOME_PHASES)
def test_fixed_outcome_and_focus_preserve_failure(output: Path, phase: OutcomePhase) -> None:
    original = RuntimeError("Control not reachable by keyboard")
    frame = DiagnosticFrame(
        kind="failure",
        stage="url_worker",
        error="RuntimeError",
        reason="keyboard_focus",
        outcome_phase=phase,
        focus_exhaustion=FocusExhaustion(
            target_focused=False,
            document_focused=True,
            modal_open=False,
            active_kind="outcomes_heading",
            target_kind="button",
            active_control="other",
            target_disabled=False,
            target_in_dialog=False,
            active_in_target_dialog=False,
            target_inert=False,
            target_tab_stop=True,
        ),
    )

    @trace.observed_guest
    def failed() -> None:
        trace.guest_stage("conversation")
        trace.guest_frame(frame)
        raise original

    with pytest.raises(RuntimeError) as caught:
        failed()
    assert caught.value is original
    assert output.read_text().endswith(
        "-outcome_" + phase + "-focus_outcomes_heading.button.other.01000001\n"
    )


def test_focus_unknowns_and_unavailable_are_distinct() -> None:
    value = trace.Trace()
    value.focus = FocusExhaustion(
        target_focused=True, document_focused=False, modal_open=True, active_kind="target"
    )
    assert value.label().endswith("-focus_target.none.none.101uuuuu")
    value.focus = "unavailable"
    assert value.label().endswith("-focus_unavailable")
    value.focus = None
    assert value.label().endswith("-focus_none")


@pytest.mark.parametrize("field", ["outcome", "focus"])
def test_arbitrary_outcome_or_focus_cannot_be_reported(field: str) -> None:
    value = trace.Trace()
    setattr(value, field, "private@example.invalid")
    with pytest.raises(ValueError, match="Closed"):
        value.label()


def test_mutated_focus_model_is_revalidated_before_reporting() -> None:
    value = trace.Trace()
    value.focus = FocusExhaustion(
        target_focused=False, document_focused=True, modal_open=False, active_kind="body"
    )
    object.__setattr__(value.focus, "active_kind", "private@example.invalid")
    with pytest.raises(ValueError):
        value.label()


def test_synthetic_keyboard_flow_keeps_all_tabs_and_original_failure(
    output: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from types import SimpleNamespace
    from typing import cast
    from unittest.mock import AsyncMock

    import operator_ui_acceptance as guest
    from playwright.async_api import Locator, Page

    snapshot = dict(
        target_focused=False, document_focused=True, modal_open=False, active_kind="body"
    )
    target = SimpleNamespace(
        wait_for=AsyncMock(), evaluate=AsyncMock(side_effect=[False] * 100 + [snapshot])
    )
    keyboard = SimpleNamespace(press=AsyncMock())
    monkeypatch.setattr(guest, "expect", lambda _: SimpleNamespace(to_be_enabled=AsyncMock()))
    original = []

    @trace.observed_guest
    def execute() -> None:
        trace.guest_stage("conversation")
        try:
            asyncio.run(
                guest.focus(cast(Page, SimpleNamespace(keyboard=keyboard)), cast(Locator, target))
            )
        except RuntimeError as error:
            original.append(error)
            trace.guest_frame(
                DiagnosticFrame(
                    kind="failure",
                    stage="url_worker",
                    error="RuntimeError",
                    reason="keyboard_focus",
                    outcome_phase="outcomes_actual_modal",
                    focus_exhaustion=guest.focus_exhaustion,
                )
            )
            raise

    with pytest.raises(RuntimeError, match="^Control not reachable by keyboard$") as caught:
        execute()
    assert caught.value is original[0]
    assert keyboard.press.await_count == 100
    assert all(call.args == ("Tab",) for call in keyboard.press.await_args_list)
    assert output.read_text().endswith(
        "-outcome_outcomes_actual_modal-focus_body.none.none.010uuuuu\n"
    )


@pytest.mark.parametrize("truncated", [False, True])
@pytest.mark.parametrize("replaced", [False, True])
def test_existing_attempt_summary_preserves_failure_without_event_payloads(
    output: Path, truncated: bool, replaced: bool
) -> None:
    from operator_ui_protocol import KeyboardAttemptTrace, KeyboardTransition

    events = [KeyboardTransition(kind="start", tab=0, target_connected=True)]
    if replaced:
        events.extend(
            [
                KeyboardTransition(kind="heading_focus", tab=47, target_connected=True),
                KeyboardTransition(kind="target_detached", tab=47, target_connected=False),
                KeyboardTransition(kind="target_replaced", tab=47, target_connected=True),
            ]
        )
    events.append(KeyboardTransition(kind="finish", tab=100, target_connected=True))
    frame = DiagnosticFrame(
        kind="failure",
        stage="url_worker",
        error="RuntimeError",
        reason="keyboard_focus",
        outcome_phase="outcomes_late_organization",
        focus_exhaustion=FocusExhaustion(
            target_focused=False,
            document_focused=True,
            modal_open=False,
            active_kind="other",
            attempt_trace=KeyboardAttemptTrace(tabs=100, truncated=truncated, events=events),
        ),
    )
    original = RuntimeError("private sentinel")

    @trace.observed_guest
    def execute() -> None:
        trace.guest_stage("conversation")
        trace.guest_frame(frame)
        raise original

    with pytest.raises(RuntimeError) as caught:
        execute()
    assert caught.value is original
    suffix = "1at47" if replaced else "0atnone"
    assert output.read_text().endswith(
        f"-attempt_tabs100.truncated{int(truncated)}.heading{suffix}.detached{suffix}.replaced{suffix}\n"
    )
    assert "private" not in output.read_text()
    assert "target_connected" not in output.read_text()
    assert "events" not in output.read_text()


def test_missing_and_unavailable_attempts_remain_distinct() -> None:
    value = trace.Trace()
    value.focus = FocusExhaustion(
        target_focused=False, document_focused=True, modal_open=False, active_kind="other"
    )
    assert "-attempt_" not in value.label()
    value.focus.attempt_trace = "unavailable"
    assert value.label().endswith("-attempt_unavailable")


@pytest.mark.parametrize("field,value", [("kind", "private@example.invalid"), ("tab", 101)])
def test_mutated_nested_attempt_is_rejected_before_export(field: str, value: object) -> None:
    from operator_ui_protocol import KeyboardAttemptTrace, KeyboardTransition

    event = KeyboardTransition(kind="start", tab=0, target_connected=True)
    observation = trace.Trace()
    observation.focus = FocusExhaustion(
        target_focused=False,
        document_focused=True,
        modal_open=False,
        active_kind="other",
        attempt_trace=KeyboardAttemptTrace(tabs=100, truncated=False, events=[event]),
    )
    object.__setattr__(event, field, value)
    with pytest.raises(ValueError):
        observation.label()


@pytest.mark.parametrize("pending", [False, True])
def test_completion_boundary_keeps_owned_pipe_failure(
    output: Path, monkeypatch: pytest.MonkeyPatch, pending: bool
) -> None:
    import json
    import subprocess
    import sys
    import time

    import run_operator_ui_acceptance as host
    from fastapi import FastAPI

    original_popen = subprocess.Popen
    processes = []
    request = {"kind": "control", "identifier": 1, "action": "verify_retained"}
    result = {"kind": "result", "diagnostic": "synthetic-operator-ui"}
    program = "import sys;sys.stdin.readline();"
    if pending:
        program += f"print({json.dumps(request)!r},flush=True);"
    program += f"print({json.dumps(result)!r},flush=True);sys.stdin.read();sys.exit(7)"

    def owned_pipe(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        process = original_popen(
            [sys.executable, "-c", program],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", owned_pipe)

    @trace.observed_guest
    def execute() -> None:
        host.conversation(
            "owned-synthetic-pipe",
            FastAPI(),
            {},
            lambda action: time.sleep(0.1),
            lambda request: False,
        )

    message = (
        "Guest completed with pending requests"
        if pending
        else "Actual UI completion evidence missing"
    )
    with pytest.raises(RuntimeError, match=message):
        execute()
    stage = "conversation_result" if pending else "conversation_exit"
    assert output.read_text().startswith("guest_outcome=" + stage + "-")
    assert len(processes) == 1 and processes[0].poll() is not None

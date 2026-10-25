"""Value-free source location and actual installed reauthentication stage grammar."""

import pytest
from operator_ui_protocol import DiagnosticFrame, export_assertion_line
from pydantic import ValidationError


def test_export_assertion_location_never_includes_exception_or_local_values() -> None:
    try:
        exec(
            compile(
                "raise AssertionError('private fixture text')",
                "/app/operator_ui_acceptance.py",
                "exec",
            )
        )
    except AssertionError as error:
        assert export_assertion_line(error) == 1
        frame = DiagnosticFrame(
            kind="failure", stage="export_preview", error="AssertionError", export_assertion_line=1
        )
        assert "private fixture" not in frame.model_dump_json()
    try:
        raise AssertionError("unrelated test source")
    except AssertionError as error:
        assert export_assertion_line(error) is None
    assert export_assertion_line(RuntimeError("private fixture")) is None


@pytest.mark.parametrize("stage", ["assets_session", "keyword_worker", "url_worker"])
def test_installed_login_diagnostic_supports_both_real_reauthentication_branches(
    stage: str,
) -> None:
    frame = DiagnosticFrame.model_validate(
        {
            "kind": "failure",
            "stage": stage,
            "error": "TimeoutError",
            "installed_login_phase": "callback_document",
            "reason": "installed_login_deadline",
        }
    )
    assert frame.stage == stage and frame.error == "TimeoutError"


@pytest.mark.parametrize(
    "change",
    [
        {"stage": "source_review"},
        {"error": "RuntimeError"},
        {"export_assertion_line": 0},
        {"export_assertion_line": 10001},
        {"export_assertion_line": True},
        {"export_assertion_line": "secret"},
    ],
)
def test_export_location_rejects_other_stages_types_and_unbounded_values(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        DiagnosticFrame.model_validate(
            {
                "kind": "failure",
                "stage": "export_preview",
                "error": "AssertionError",
                "export_assertion_line": 1,
                **change,
            }
        )


def test_installed_login_diagnostic_still_refuses_unrelated_stage() -> None:
    with pytest.raises(ValidationError):
        DiagnosticFrame.model_validate(
            {
                "kind": "failure",
                "stage": "export_preview",
                "error": "TimeoutError",
                "installed_login_phase": "callback_document",
            }
        )


def test_login_timing_measures_existing_budget_without_modifying_it() -> None:
    from operator_ui_protocol import LoginTiming

    clock = [100.0]
    timing = LoginTiming(clock=lambda: clock[0])
    with pytest.raises(ValueError):
        timing.snapshot()
    timing.begin()
    clock[0] = 104.0
    timing.phase()
    clock[0] = 105.0
    timing.fulfilled()
    clock[0] = 110.0
    assert timing.snapshot().model_dump() == {
        "total_ms": 10000,
        "phase_ms": 6000,
        "callback_fulfilled_ms": 5000,
    }
    timing.fulfilled()
    assert timing.snapshot().callback_fulfilled_ms == 5000
    timing.begin()
    assert timing.snapshot().callback_fulfilled_ms is None
    clock[0] = 200.0
    assert timing.snapshot().total_ms == 60000


@pytest.mark.parametrize(
    "change",
    [
        {"click_events": 3},
        {"association": "private"},
        {"screen": "private"},
        {"private": "payload"},
    ],
)
def test_handoff_trace_is_a_closed_value_free_observation(change: dict[str, object]) -> None:
    from operator_ui_protocol import HandoffTrace

    value = {
        "key_events": 1,
        "click_events": 1,
        "trusted_click": True,
        "disabled_on_enter": False,
        "focused_on_enter": True,
        "last_enter_target": "handoff",
        "screen": "review",
        "association": "needs_review",
        "error_count": 0,
        "error_kind": "none",
    }
    assert HandoffTrace.model_validate(value).click_events == 1
    with pytest.raises(ValidationError):
        HandoffTrace.model_validate({**value, **change})


@pytest.mark.parametrize("stage", ["assets_session", "keyword_worker", "url_worker"])
def test_login_timing_requires_the_existing_failure_and_owned_phase(stage: str) -> None:
    value = {
        "kind": "failure",
        "stage": stage,
        "error": "TimeoutError",
        "installed_login_phase": "callback_document",
        "installed_login_timing": {
            "total_ms": 10000,
            "phase_ms": 5000,
            "callback_fulfilled_ms": 6000,
        },
    }
    assert DiagnosticFrame.model_validate(value).installed_login_timing is not None
    with pytest.raises(ValidationError):
        DiagnosticFrame.model_validate({**value, "installed_login_phase": None})

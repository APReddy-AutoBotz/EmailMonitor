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

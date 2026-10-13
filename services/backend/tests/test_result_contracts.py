"""Committed response/command parity and bounded authorization-free envelope syntax."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict
from emailmonitor.organizations.roles import ROLE_CAPABILITIES, Capability, Role
from emailmonitor.results.broker import ExportEvent
from emailmonitor.results.models import ContactPage, ExportInput, ExportState, OutcomePage
from emailmonitor.results.service import translate
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "name,model",
    [
        ("result-contacts", ContactPage),
        ("result-outcomes", OutcomePage),
        ("export-request", ExportInput),
        ("export-state", ExportState),
    ],
)
def test_committed_result_schema_examples(
    name: str, model: type[ContactPage | OutcomePage | ExportInput | ExportState]
) -> None:
    raw = (ROOT / f"contracts/examples/{name}.json").read_text()
    schema = json.loads((ROOT / f"contracts/{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(json.loads(raw))
    assert model.model_validate_json(raw)


@pytest.mark.parametrize("role", list(Role))
def test_export_capability_has_no_implicit_operator_reviewer_or_viewer_grant(role: Role) -> None:
    assert (Capability.EXPORT_RESULTS in ROLE_CAPABILITIES[role]) == (
        role in {Role.OWNER, Role.ADMIN, Role.DATA_STEWARD}
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"ttl_seconds": 0},
        {"ttl_seconds": 86401},
        {"ttl_seconds": True},
        {"purpose": "marketing"},
        {"raw_address": "private@example.org"},
        {"include_unresolved": "false"},
        {"format": "pdf"},
        {"job_id": "bad"},
    ],
)
def test_export_commands_have_no_content_or_unsafe_option_input(changes: dict[str, object]) -> None:
    body: dict[str, object] = {"format": "csv", "purpose": "academic_contact_research", **changes}
    with pytest.raises(ValidationError):
        ExportInput.model_validate(body)


@pytest.mark.parametrize(
    "changes",
    [
        {"body": "raw data"},
        {"snapshot": {}},
        {"generation": True},
        {"organization_id": "bad"},
        {"version": 2},
        {"kind": "export.ready"},
    ],
)
def test_broker_export_envelope_is_current_id_work_only(changes: dict[str, object]) -> None:
    body: dict[str, object] = {
        "organization_id": str(uuid4()),
        "export_id": str(uuid4()),
        "event_id": str(uuid4()),
        "generation": 1,
        **changes,
    }
    with pytest.raises(ValidationError):
        ExportEvent.model_validate(body)


@pytest.mark.parametrize(
    "code,message,expected",
    [
        ("EM011", "RESULT_SCOPE_DENIED", AuthorizationDenied),
        ("EM009", "ASSOCIATION_DENIED", AuthorizationDenied),
        ("EM010", "EXECUTION_SCOPE_DENIED", AuthorizationDenied),
        ("EM009", "unrelated", DBAPIError),
        ("EM409", "EXPORT_KEY_CONFLICT", RevisionConflict),
        ("EM409", "EXPORT_REVISION", RevisionConflict),
        ("EM011", "unrelated", DBAPIError),
        ("55P03", "lock timeout", DBAPIError),
    ],
)
def test_only_exact_owned_driver_denials_are_translated(
    code: str, message: str, expected: type[Exception]
) -> None:
    error = DBAPIError("synthetic", {}, Exception({"C": code, "M": message}), False)
    with pytest.raises(expected):
        translate(error)

"""Offline request/event parity and diagnostic configuration boundaries."""

import json
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import jsonschema
import pytest
from emailmonitor.jobs.broker import FixtureWorkerConfig
from emailmonitor.jobs.ledger import Ledger, Work
from emailmonitor.jobs.models import TERMINAL, TRANSITIONS, JobRequest, effect_key
from emailmonitor.organizations.database import AuthorizationDenied
from pydantic import ValidationError
from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError

ROOT = Path(__file__).resolve().parents[3]


def request_body() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "input": {
            "type": "keyword",
            "source_id": "synthetic-publisher",
            "original_query": "original",
        },
        "purpose": "academic_contact_research",
        "options": {"max_articles": 1, "max_search_pages": 1, "author_target": "both"},
    }


def test_original_request_and_committed_example_contract_parity() -> None:
    schema = json.loads((ROOT / "contracts/job-request.schema.json").read_text())
    body = request_body()
    jsonschema.validate(body, schema)
    parsed = JobRequest.model_validate(body)
    jsonschema.validate(parsed.model_dump(mode="json", exclude_none=True), schema)
    for path in (ROOT / "contracts/examples").glob("*job*.json"):
        JobRequest.model_validate_json(path.read_text())


def test_reuse_choice_is_explicit_and_legacy_request_stays_unchanged() -> None:
    body = request_body()
    legacy = JobRequest.model_validate(body).model_dump(mode="json", exclude_none=True)
    assert "reuse" not in legacy
    requested = {
        **body,
        "reuse": {"mode": "verified_retained", "fresh_since": "2026-10-01T09:00:00-04:00"},
    }
    model = JobRequest.model_validate(requested)
    assert model.model_dump(mode="json", exclude_none=True)["reuse"] == {
        "mode": "verified_retained",
        "fresh_since": "2026-10-01T13:00:00Z",
    }
    schema = json.loads((ROOT / "contracts/job-request.schema.json").read_text())
    jsonschema.validate(requested, schema, format_checker=jsonschema.FormatChecker())
    jsonschema.validate(
        model.model_dump(mode="json", exclude_none=True),
        schema,
        format_checker=jsonschema.FormatChecker(),
    )


@pytest.mark.parametrize(
    "choice",
    [
        {"mode": "verified_retained"},
        {"mode": "verified_retained", "fresh_since": "2026-10-01"},
        {"mode": "verified_retained", "fresh_since": "2026-10-01T13:00:00"},
        {"mode": "verified_retained", "fresh_since": 1790860000},
        {"mode": "automatic", "fresh_since": "2026-10-01T13:00:00Z"},
        {"mode": "verified_retained", "fresh_since": "2026-02-30T13:00:00Z"},
    ],
)
def test_reuse_choice_requires_explicit_offset_and_valid_cutoff(choice: object) -> None:
    with pytest.raises(ValidationError):
        JobRequest.model_validate({**request_body(), "reuse": choice})


def test_unavailable_reuse_refuses_after_authorization_before_job_writes() -> None:
    from emailmonitor.config import Settings
    from emailmonitor.organizations.roles import Capability
    from fastapi import HTTPException

    database, connection = MagicMock(), MagicMock()
    database.tenant.return_value.__enter__.return_value = (connection, MagicMock())
    request = JobRequest.model_validate(
        {
            **request_body(),
            "reuse": {"mode": "verified_retained", "fresh_since": "2026-10-01T13:00:00Z"},
        }
    )
    with pytest.raises(HTTPException) as error:
        Ledger(database, "synthetic", Settings(environment="test", fixture_mode=True)).create(
            UUID(int=1), request, "synthetic-key"
        )
    assert error.value.status_code == 409
    database.tenant.assert_called_once_with("synthetic", UUID(int=1), Capability.ACQUIRE_SOURCE)
    connection.execute.assert_not_called()


def test_unavailable_reuse_does_not_override_authorization_refusal() -> None:
    from emailmonitor.config import Settings

    database = MagicMock()
    database.tenant.side_effect = AuthorizationDenied()
    request = JobRequest.model_validate(
        {
            **request_body(),
            "reuse": {"mode": "verified_retained", "fresh_since": "2026-10-01T13:00:00Z"},
        }
    )
    with pytest.raises(AuthorizationDenied):
        Ledger(database, "synthetic", Settings(environment="test", fixture_mode=True)).create(
            UUID(int=1), request, "synthetic-key"
        )


@pytest.mark.parametrize("environment", ["test", "production"])
def test_supported_reuse_refuses_without_synthetic_fixture_mode(environment: str) -> None:
    from emailmonitor.config import Settings
    from fastapi import HTTPException

    database, connection = MagicMock(), MagicMock()
    database.tenant.return_value.__enter__.return_value = (connection, MagicMock())
    request = JobRequest.model_validate(
        {
            **request_body(),
            "input": {"type": "url", "url": "https://synthetic.publisher.example/article-a.html"},
            "reuse": {"mode": "verified_retained", "fresh_since": "2026-10-01T13:00:00Z"},
        }
    )
    settings = Settings.model_validate({"environment": environment, "fixture_mode": False})
    with pytest.raises(HTTPException) as error:
        Ledger(database, "synthetic", settings).create(UUID(int=1), request, "synthetic-key")
    assert error.value.status_code == 409
    connection.execute.assert_not_called()


def test_unconfirmed_query_change_is_rejected() -> None:
    body = request_body()
    body["input"] = {
        "type": "keyword",
        "source_id": "synthetic-publisher",
        "original_query": "original",
        "effective_query": "changed",
    }
    with pytest.raises(ValidationError):
        JobRequest.model_validate(body)
    value = body["input"]
    assert isinstance(value, dict)
    value["query_change_confirmed"] = True
    assert JobRequest.model_validate(body).input.type == "keyword"


def test_internal_work_messages_match_existing_event_contract() -> None:
    work = Work(uuid4(), uuid4(), uuid4(), uuid4())
    schema = json.loads((ROOT / "contracts/event.schema.json").read_text())
    for kind in ("job.queued", "job.item_terminal"):
        body = work.message(kind)
        jsonschema.validate(body, schema, format_checker=jsonschema.FormatChecker())
        assert Work.parse(body) == work
        payload = body["payload"]
        assert isinstance(payload, dict)
        payload["url"] = "https://synthetic.publisher.example/article-a.html"
        with pytest.raises(ValueError):
            Work.parse(body)


@pytest.mark.parametrize(
    "change",
    [
        {"environment": "production"},
        {"database_url": "postgresql+pg8000://user@external.example/db"},
        {"broker_url": "pyamqp://fixture@external.example//"},
        {"queue": "arbitrary"},
        {"diagnostic_delay_seconds": 31},
        {"lease_seconds": 0},
        {"environment": "development"},
    ],
)
def test_worker_config_is_bounded_and_loopback_test_only(change: dict[str, object]) -> None:
    body = {
        "environment": "test",
        "database_url": "postgresql+pg8000://fixture@127.0.0.1/db",
        "broker_url": "pyamqp://fixture@127.0.0.1//",
        "session_token": "synthetic-session-token",
        "organization": str(uuid4()),
        "queue": "em-fixture-unit",
        **change,
    }
    with pytest.raises(ValidationError):
        FixtureWorkerConfig.model_validate(body)


def test_terminal_states_are_closed_and_effects_are_tenant_bound() -> None:
    for state in TERMINAL:
        assert not TRANSITIONS[state]
    assert effect_key("a", "job", "item", "digest") == effect_key("a", "job", "item", "digest")
    assert effect_key("a", "job", "item", "digest") != effect_key("b", "job", "item", "digest")


@pytest.mark.parametrize("invalid", [None, 0, 1, True, "false"])
def test_unavailable_option_requires_literal_boolean_false(invalid: object) -> None:
    body = request_body()
    options = body["options"]
    assert isinstance(options, dict)
    options["allow_ocr"] = invalid
    with pytest.raises(ValidationError):
        JobRequest.model_validate(body)


def test_dates_and_null_input_contract_boundary() -> None:
    body = request_body()
    body["filters"] = {"publication_from": "2026-01-01", "publication_to": "2026-10-10"}
    parsed = JobRequest.model_validate(body)
    assert str(parsed.filters.publication_from) == "2026-01-01"
    body["filters"] = {"publication_from": None}
    with pytest.raises(ValidationError):
        JobRequest.model_validate(body)
    body["input"] = {"type": "url", "url": "http://"}
    with pytest.raises(ValidationError):
        JobRequest.model_validate(body)


@pytest.mark.parametrize("date_type", ["published", "online", "issue"])
def test_explicit_date_type_preserves_legacy_request_and_contract(date_type: str) -> None:
    schema = json.loads((ROOT / "contracts/job-request.schema.json").read_text())
    body = request_body()
    body["filters"] = {"publication_from": "2026-02-20", "publication_date_type": date_type}
    parsed = JobRequest.model_validate(body)
    document = parsed.model_dump(mode="json", exclude_none=True)
    jsonschema.validate(document, schema)
    assert document["filters"]["publication_date_type"] == date_type
    legacy = request_body()
    legacy["filters"] = {"publication_from": "2026-02-20"}
    old_document = JobRequest.model_validate(legacy).model_dump(mode="json", exclude_none=True)
    assert "publication_date_type" not in old_document["filters"]


@pytest.mark.parametrize(
    "filters",
    [
        {"publication_date_type": "published"},
        {"publication_date_type": "accepted", "publication_from": "2026-01-01"},
        {"publication_date_type": None, "publication_from": "2026-01-01"},
        {"publication_date_type": "issue", "publication_from": "2026-02-30"},
        {
            "publication_date_type": "online",
            "publication_from": "2026-03-01",
            "publication_to": "2026-02-01",
        },
    ],
)
def test_explicit_date_selection_invalid_shapes_refused(filters: dict[str, object]) -> None:
    body = request_body()
    body["filters"] = filters
    with pytest.raises(ValidationError):
        JobRequest.model_validate(body)


def test_disposable_container_context_is_only_used_in_runner_step() -> None:
    workflow = (ROOT / ".github/workflows/application.yml").read_text()
    before_steps, steps = workflow.split("    steps:", 1)
    assert "${{ job." not in before_steps
    test_step = steps.split("- name: Execute offline scaffold and real tenant SQL/API checks", 1)[1]
    assert (
        "        env:\n          EM_TEST_BROKER_CONTAINER: ${{ job.services.rabbitmq.id }}"
        in test_step
    )
    assert 'EM_REQUIRE_REAL_BROKER: "true"' in before_steps


@pytest.mark.parametrize("stage", ["lock", "recheck"])
@pytest.mark.parametrize(
    "detail,denied",
    [
        ({"C": "P0001", "M": "JOB_UNAVAILABLE"}, True),
        ({"C": "P0001", "M": "JOB_UNAVAILABLE private suffix"}, False),
        ({"C": "42501", "M": "JOB_UNAVAILABLE"}, False),
        ({"C": "55P03", "M": "lock timeout"}, False),
        ({}, False),
        ("JOB_UNAVAILABLE", False),
    ],
)
def test_job_lock_translates_only_exact_authority_denial(
    stage: str, detail: object, denied: bool
) -> None:
    error = DBAPIError("synthetic protected query", {}, Exception(detail), False)
    connection = MagicMock(spec=Connection)
    row = MagicMock()
    row.mappings.return_value.first.return_value = {"id": uuid4()}
    connection.execute.side_effect = [None, error] if stage == "lock" else [None, row, error]
    if denied:
        with pytest.raises(AuthorizationDenied) as caught:
            Ledger._lock(connection, uuid4(), uuid4())
        assert caught.value.__cause__ is None and caught.value.__suppress_context__
    else:
        with pytest.raises(DBAPIError) as unchanged:
            Ledger._lock(connection, uuid4(), uuid4())
        assert unchanged.value is error

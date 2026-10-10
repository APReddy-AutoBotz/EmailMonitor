"""Offline request/event parity and diagnostic configuration boundaries."""

import json
from pathlib import Path
from uuid import uuid4

import jsonschema
import pytest
from emailmonitor.jobs.broker import FixtureWorkerConfig
from emailmonitor.jobs.ledger import Work
from emailmonitor.jobs.models import TERMINAL, TRANSITIONS, JobRequest, effect_key
from pydantic import ValidationError

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

"""Committed metadata schemas and stronger runtime counter/association semantics."""

import json
from pathlib import Path

import pytest
from emailmonitor.progress.models import Event, Item, Snapshot
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "name,model",
    [("progress-snapshot", Snapshot), ("progress-event", Event), ("progress-item", Item)],
)
def test_committed_progress_examples_and_schema(
    name: str, model: type[Snapshot | Event | Item]
) -> None:
    raw = (ROOT / f"contracts/examples/{name}.json").read_text()
    schema = json.loads((ROOT / f"contracts/{name}.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(json.loads(raw))
    assert model.model_validate_json(raw)


@pytest.mark.parametrize(
    "review,field",
    [(False, "batch_id"), (False, "association_id"), (True, "batch_id"), (True, "association_id")],
)
def test_schema_runtime_review_identifier_parity(review: bool, field: str) -> None:
    body = json.loads((ROOT / "contracts/examples/progress-event.json").read_text())
    if review:
        body.update(
            event_type="association.reviewed",
            batch_id="55555555-5555-4555-8555-555555555555",
            association_id="66666666-6666-4666-8666-666666666666",
        )
        body[field] = None
    else:
        body[field] = "55555555-5555-4555-8555-555555555555"
    schema = json.loads((ROOT / "contracts/progress-event.schema.json").read_text())
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(body))
    with pytest.raises(ValidationError):
        Event.model_validate_json(json.dumps(body))


@pytest.mark.parametrize("field", ["inherited_job_id", "inherited_item_id"])
def test_inherited_item_schema_runtime_require_both_provenance_ids(field: str) -> None:
    body = json.loads((ROOT / "contracts/examples/progress-item.json").read_text())
    body[field] = "66666666-6666-4666-8666-666666666666"
    schema = json.loads((ROOT / "contracts/progress-item.schema.json").read_text())
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(body))
    with pytest.raises(ValidationError):
        Item.model_validate_json(json.dumps(body))


def test_inherited_item_is_prior_terminal_receipt_not_new_running_work() -> None:
    body = json.loads((ROOT / "contracts/examples/progress-item.json").read_text())
    body.update(
        inherited_job_id="66666666-6666-4666-8666-666666666666",
        inherited_item_id="77777777-7777-4777-8777-777777777777",
        state="running",
    )
    schema = json.loads((ROOT / "contracts/progress-item.schema.json").read_text())
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(body))
    with pytest.raises(ValidationError):
        Item.model_validate_json(json.dumps(body))

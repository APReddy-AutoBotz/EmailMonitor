"""Open Access contracts stay generated from the models and fixtures (OA-022)."""

from typing import Any

from emailmonitor.discovery.oa_contracts import drift, examples, schemas
from jsonschema import Draft202012Validator, FormatChecker


def test_committed_contracts_match_models_and_fixture_outputs() -> None:
    assert drift() == [], "run: python -m emailmonitor.discovery.oa_contracts --write"


def test_schemas_are_valid_and_examples_conform() -> None:
    generated: dict[str, dict[str, Any]] = schemas()
    pairs = {
        "oa-discovery-result.json": "oa-discovery-result.schema.json",
        "oa-document-extraction.json": "oa-document-extraction.schema.json",
        "oa-researcher-profile.json": "oa-researcher-profile.schema.json",
    }
    for example_name, value in examples().items():
        schema = generated[pairs[example_name]]
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        assert list(validator.iter_errors(value)) == []


def test_schema_rejects_unknown_fields_and_bad_eligibility() -> None:
    schema = schemas()["oa-discovery-result.schema.json"]
    validator = Draft202012Validator(schema)
    example = examples()["oa-discovery-result.json"]
    assert list(validator.iter_errors({**example, "unexpected": 1}))
    contact = dict(example["contacts_extracted"][0])
    contact["outreach_eligibility"] = "verified_deliverable"
    broken = {**example, "contacts_extracted": [contact]}
    assert list(validator.iter_errors(broken))

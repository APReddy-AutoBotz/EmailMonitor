"""Structural PDF contract checks; runtime also validates relational evidence."""

import copy
import json
from pathlib import Path

import pytest
from emailmonitor.extraction.pdf import PdfObservation
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from test_pdf_extraction import parse

ROOT = Path(__file__).resolve().parents[3]


def example() -> dict[str, object]:
    return json.loads((ROOT / "contracts/examples/pdf-observation.json").read_text())  # type: ignore[no-any-return]


def validator() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((ROOT / "contracts/pdf-observation.schema.json").read_text())
    )


def test_pdf_example_is_actual_parser_output_with_shared_structural_contract() -> None:
    value = example()
    validator().validate(value)
    assert PdfObservation.model_validate_json(json.dumps(value)) == parse("article-a.pdf")


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "accepted",
        "numeric_false",
        "ocr",
        "wrong_url",
        "wrong_first",
        "no_contact",
        "incomplete_observed",
        "missing_metadata",
        "populated_unsupported",
    ],
)
def test_schema_and_runtime_refuse_unavailable_claims(change: str) -> None:
    value = copy.deepcopy(example())
    if change == "extra":
        value["send_email"] = True
    elif change == "accepted":
        value["identity_association_implemented"] = True
    elif change == "numeric_false":
        value["identity_association_implemented"] = 0
    elif change == "ocr":
        value["ocr_implemented"] = True
    elif change == "wrong_url":
        value["url"] = "https://unapproved.example/article.pdf"
    elif change == "wrong_first":
        assert isinstance(value["authors"], list)
        value["authors"][0]["first"] = False
    elif change == "no_contact":
        value["status"] = "no_contact"
    elif change == "incomplete_observed":
        value["complete_scan"] = False
    elif change == "missing_metadata":
        del value["preferred_metadata"]
    else:
        value.update(status="unsupported", reason="corrupt", complete_scan=False, pages_inspected=0)
    assert not validator().is_valid(value)
    with pytest.raises(ValidationError):
        PdfObservation.model_validate_json(json.dumps(value))


@pytest.mark.parametrize(
    "change", ["invented_address", "unknown_author", "invented_metadata", "locator_page"]
)
def test_runtime_semantics_are_stronger_than_structural_schema(change: str) -> None:
    value = copy.deepcopy(example())
    assert isinstance(value["candidates"], list)
    if change == "invented_address":
        value["candidates"][0]["raw_address"] = "fabricated@example.org"
    elif change == "unknown_author":
        value["candidates"][0]["author_positions"] = [100]
    elif change == "invented_metadata":
        assert isinstance(value["preferred_metadata"], dict)
        value["preferred_metadata"]["title"] = "Unobserved title"
    else:
        value["candidates"][0]["evidence"][0]["locator"] = "page:1:fragment:1"
    # These are relational predicates, not claims of JSON Schema equivalence.
    assert validator().is_valid(value)
    with pytest.raises(ValidationError):
        PdfObservation.model_validate_json(json.dumps(value))

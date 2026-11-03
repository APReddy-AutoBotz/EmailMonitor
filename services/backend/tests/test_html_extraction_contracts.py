"""Shared observation/schema failures, separate from accepted-contact records."""

import copy
import json
from pathlib import Path

import pytest
from emailmonitor.extraction.html import ArticleObservation
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]


def example() -> dict[str, object]:
    return json.loads((ROOT / "contracts/examples/article-observation.json").read_text())  # type: ignore[no-any-return]


def validator() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((ROOT / "contracts/article-observation.schema.json").read_text())
    )


def test_committed_observation_contract_matches_actual_fixture_parser() -> None:
    from test_html_extraction import parse

    value = example()
    assert ArticleObservation.model_validate(value) == parse("article-a.html")
    validator().validate(value)


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "accepted",
        "numeric_false",
        "wrong_url",
        "false_complete",
        "wrong_first",
        "browser_wrong_article",
    ],
)
def test_schema_and_model_refuse_unavailable_claims_and_inconsistent_observations(
    change: str,
) -> None:
    value = copy.deepcopy(example())
    if change == "extra":
        value["send_email"] = True
    elif change == "accepted":
        value["identity_association_implemented"] = True
    elif change == "numeric_false":
        value["identity_association_implemented"] = 0
    elif change == "wrong_url":
        value["url"] = "https://unapproved.example/article"
    elif change == "false_complete":
        value["status"] = "no_contact"
    elif change == "wrong_first":
        authors = value["authors"]
        assert isinstance(authors, list)
        authors[0]["first"] = False
    else:
        value["route"] = "browser_dom"
    assert not validator().is_valid(value)
    with pytest.raises(ValidationError):
        ArticleObservation.model_validate(value)


def test_required_browser_plan_cannot_be_omitted_from_static_tooltip() -> None:
    from test_html_extraction import parse

    value = parse("tooltip.html").model_dump(mode="json")
    validator().validate(value)
    del value["browser_plan"]
    assert not validator().is_valid(value)
    with pytest.raises(ValidationError):
        ArticleObservation.model_validate(value)

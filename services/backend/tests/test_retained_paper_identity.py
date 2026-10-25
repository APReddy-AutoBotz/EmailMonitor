"""Paper selector syntax and compatibility; actual persistence is tested separately."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from emailmonitor.results.cursor import decode, encode, fingerprint
from emailmonitor.results.models import ExportInput, Filters
from jsonschema import Draft202012Validator
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
DOI = "10.9999/synthetic.article-a"


@pytest.mark.parametrize("value", ["10.9999/ARTICLE-A", "10.12345/AbC(12);x_y:z", DOI])
def test_paper_selector_normalizes_without_changing_legacy_defaults(value: str) -> None:
    filters = Filters(paper_doi=value)
    assert filters.paper_doi == value.lower()
    assert "paper_doi" not in Filters().model_dump()
    assert Filters(paper_doi=None).model_dump_json() == Filters().model_dump_json()
    request = ExportInput(format="xlsx", purpose="academic_contact_research", paper_doi=value)
    assert request.filters().paper_doi == filters.paper_doi
    assert fingerprint(filters) == fingerprint(Filters(paper_doi=value.lower()))
    schema = json.loads((ROOT / "contracts/export-request.schema.json").read_text())
    Draft202012Validator(schema).validate(request.model_dump(mode="json"))


@pytest.mark.parametrize(
    "value",
    [
        "",
        "10.99/a",
        "https://doi.org/10.9999/a",
        "10.9999/",
        "10.9999/a//b",
        "10.9999/../a",
        "10.9999/a/.",
        "10.9999/a b",
        "10.9999/é",
        "10.9999/a\n",
        "10.9999/a?x",
        "10.9999/a#b",
        "10.9999/" + "a" * 249,
    ],
)
def test_unsupported_identity_is_not_silently_repaired(value: str) -> None:
    with pytest.raises(ValidationError):
        Filters(paper_doi=value)
    with pytest.raises(ValidationError):
        ExportInput(format="csv", purpose="academic_contact_research", paper_doi=value)


def test_paper_cursor_binds_tenant_dataset_and_all_selectors() -> None:
    org, job, item = uuid4(), uuid4(), uuid4()
    selected = Filters(paper_doi=DOI, job_id=job, item_id=item)
    cursor = encode(org, "contacts", selected, uuid4(), uuid4())
    assert decode(org, "contacts", selected, cursor)
    for other in (Filters(), Filters(paper_doi="10.9999/different"), Filters(paper_doi=DOI)):
        with pytest.raises(ValueError):
            decode(org, "contacts", other, cursor)
    with pytest.raises(ValueError):
        decode(uuid4(), "contacts", selected, cursor)
    with pytest.raises(ValueError):
        decode(org, "outcomes", selected, cursor)

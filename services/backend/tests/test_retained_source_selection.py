"""Exact registered source selection, legacy request identities and cursor binding."""

import json
from pathlib import Path
from typing import Final
from uuid import uuid4

import pytest
from emailmonitor.results.cursor import decode, encode, fingerprint
from emailmonitor.results.models import ExportInput, Filters
from jsonschema import Draft202012Validator
from pydantic import ValidationError

SOURCE: Final = "synthetic-publisher"
ROOT = Path(__file__).resolve().parents[3]


def test_source_defaults_preserve_legacy_payload_and_cursor_identity() -> None:
    legacy = Filters()
    assert legacy.model_dump() == {
        "job_id": None,
        "states": ("accepted",),
        "author_target": "all",
        "query": "",
    }
    assert Filters(source_id=None).model_dump_json() == legacy.model_dump_json()
    assert fingerprint(Filters(source_id=None)) == fingerprint(legacy)
    request = ExportInput(format="csv", purpose="academic_contact_research")
    assert "source_id" not in request.model_dump()
    assert (
        request.model_dump_json()
        == request.model_copy(update={"source_id": None}).model_dump_json()
    )
    selected = ExportInput(format="csv", purpose="academic_contact_research", source_id=SOURCE)
    assert selected.filters().source_id == SOURCE
    Draft202012Validator(
        json.loads((ROOT / "contracts/export-request.schema.json").read_text())
    ).validate(selected.model_dump(mode="json"))


@pytest.mark.parametrize(
    "value",
    [
        "",
        "other",
        "elsevier_sciencedirect_v2",
        "https://synthetic.publisher.example",
        "10.9999/paper",
        "pdf",
        "SYNTHETIC-PUBLISHER",
        "synthetic-publisher ",
        [],
        True,
    ],
)
def test_source_cannot_be_inferred_repaired_or_expanded(value: object) -> None:
    with pytest.raises(ValidationError):
        Filters.model_validate({"source_id": value})
    with pytest.raises(ValidationError):
        ExportInput.model_validate(
            {"format": "csv", "purpose": "academic_contact_research", "source_id": value}
        )


def test_source_cursor_is_bound_even_when_single_source_membership_is_equal() -> None:
    org, job, item = uuid4(), uuid4(), uuid4()
    selected = Filters(source_id=SOURCE, job_id=job, item_id=item, paper_doi="10.9999/paper")
    cursor = encode(org, "contacts", selected, uuid4(), uuid4())
    assert decode(org, "contacts", selected, cursor)
    with pytest.raises(ValueError):
        decode(org, "contacts", selected.model_copy(update={"source_id": None}), cursor)
    with pytest.raises(ValueError):
        decode(uuid4(), "contacts", selected, cursor)
    with pytest.raises(ValueError):
        decode(org, "outcomes", selected, cursor)

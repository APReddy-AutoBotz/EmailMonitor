"""Offline filter semantics; never a production adapter or authority receipt."""

import json
from pathlib import Path

import pytest
from emailmonitor.jobs.models import Filters
from emailmonitor.sources.filter_capabilities import (
    REGISTERED_FIXTURE_FILTERS,
    FilterCapabilities,
    assess_filters,
)
from emailmonitor.sources.synthetic_filter_fixture import (
    FilterRefused,
    FixtureCursor,
    FixtureIndex,
    FixturePage,
    FixtureRequest,
    search_fixture,
)
from jsonschema import Draft202012Validator
from pydantic import ValidationError

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures/filtering/source-index.json"
SCHEMA = Path(__file__).resolve().parents[3] / "contracts/source-filter-capability.schema.json"


def index() -> FixtureIndex:
    return FixtureIndex.model_validate_json(FIXTURE.read_bytes())


def request(filters: dict[str, object] | None = None, **options: object) -> FixtureRequest:
    return FixtureRequest(
        query="synthetic research",
        filters=Filters.model_validate(filters or {}),
        page_size=options.get("page_size", 2),  # type: ignore[arg-type]
        max_pages=options.get("max_pages", 10),  # type: ignore[arg-type]
        max_articles=options.get("max_articles", 10),  # type: ignore[arg-type]
    )


def ids(page: FixturePage) -> list[str]:
    return [row.id for row in page.records]


def test_registered_source_declares_no_supported_source_side_filters() -> None:
    assert assess_filters(Filters(), REGISTERED_FIXTURE_FILTERS) == "none_requested"
    assert assess_filters(Filters(journal="Synthetic Journal A"), REGISTERED_FIXTURE_FILTERS) == (
        "journal_unavailable"
    )
    assert assess_filters(Filters(article_types=["research"]), REGISTERED_FIXTURE_FILTERS) == (
        "article_type_unavailable"
    )
    assert (
        assess_filters(
            Filters.model_validate({"publication_from": "2024-01-01"}), REGISTERED_FIXTURE_FILTERS
        )
        == "date_type_required"
    )
    assert assess_filters(Filters(journal=""), REGISTERED_FIXTURE_FILTERS) == "blank_filter"


@pytest.mark.parametrize(
    "value,valid",
    [
        ({}, True),
        ({"date_types": ["published"], "journal": "exact", "article_type": "exact_any"}, True),
        ({"date_types": ["published", "published"]}, False),
        ({"date_types": ["accepted"]}, False),
        ({"date_types": "published"}, False),
        ({"journal": "contains"}, False),
        ({"article_type": "any"}, False),
        ({"enabled": True}, False),
        ({"journal": None}, False),
    ],
)
def test_capability_schema_and_internal_model_agree(value: object, valid: bool) -> None:
    schema = json.loads(SCHEMA.read_text())
    assert Draft202012Validator(schema).is_valid(value) is valid
    if valid:
        FilterCapabilities.model_validate_json(json.dumps(value))
    else:
        with pytest.raises(ValidationError):
            FilterCapabilities.model_validate_json(json.dumps(value))


def test_inclusive_leap_day_and_combined_exact_source_filters_before_paging() -> None:
    query = request(
        {
            "publication_date_type": "published",
            "publication_from": "2024-02-29",
            "publication_to": "2024-03-01",
            "journal": "Synthetic Journal A",
            "article_types": ["research", "review"],
        },
        page_size=1,
    )
    first = search_fixture(index(), query)
    assert ids(first) == ["fixture-paper-02"] and first.fixture_reported_total == 2
    assert first.status == "more" and first.next_cursor is not None
    second = search_fixture(index(), query, first.next_cursor)
    assert ids(second) == ["fixture-paper-04"]
    assert second.status == "complete" and second.reason == "source_exhausted"
    assert second.next_cursor is None and second.fixture_reported_total == 2


def test_date_bounds_are_inclusive_and_unmatched_is_an_explicit_empty_fixture_result() -> None:
    exact = request(
        {
            "publication_date_type": "published",
            "publication_from": "2024-02-29",
            "publication_to": "2024-02-29",
        }
    )
    assert ids(search_fixture(index(), exact)) == ["fixture-paper-02"]
    empty = search_fixture(index(), request({"journal": "synthetic journal a"}))
    assert empty.records == () and empty.fixture_reported_total == 0
    assert empty.status == "complete" and empty.reason == "source_exhausted"


@pytest.mark.parametrize(
    "filters,reason",
    [
        ({"publication_from": "2024-01-01"}, "date_type_required"),
        (
            {"publication_date_type": "online", "publication_from": "2024-01-01"},
            "date_type_unavailable",
        ),
        (
            {"publication_date_type": "issue", "publication_to": "2024-12-31"},
            "date_type_unavailable",
        ),
        ({"journal": ""}, "blank_filter"),
        ({"article_types": ["  "]}, "blank_filter"),
    ],
)
def test_unsupported_or_ambiguous_request_refuses_without_substitution(
    filters: dict[str, object], reason: str
) -> None:
    with pytest.raises(FilterRefused, match="^" + reason + "$"):
        search_fixture(index(), request(filters))


@pytest.mark.parametrize(
    "field,value,filters,reason",
    [
        (
            "dates",
            [],
            {"publication_date_type": "published", "publication_from": "2024-01-01"},
            "fixture_date_evidence_incomplete",
        ),
        (
            "dates",
            [
                {"type": "published", "value": "2024-02-28"},
                {"type": "published", "value": "2024-02-29"},
            ],
            {"publication_date_type": "published", "publication_from": "2024-01-01"},
            "fixture_date_evidence_incomplete",
        ),
        (
            "journal",
            None,
            {"journal": "Synthetic Journal A"},
            "fixture_journal_evidence_incomplete",
        ),
        (
            "article_type",
            None,
            {"article_types": ["research"]},
            "fixture_article_type_evidence_incomplete",
        ),
    ],
)
def test_missing_or_conflicting_required_metadata_refuses_complete_filter_claim(
    field: str, value: object, filters: dict[str, object], reason: str
) -> None:
    raw = json.loads(FIXTURE.read_text())
    raw["records"][0][field] = value
    altered = FixtureIndex.model_validate_json(json.dumps(raw))
    with pytest.raises(FilterRefused, match="^" + reason + "$"):
        search_fixture(altered, request(filters))


def test_partial_or_invalid_date_is_never_filled_or_normalized() -> None:
    for value in ("2024", "2024-02", "2024-02-30", "2024-2-29"):
        raw = json.loads(FIXTURE.read_text())
        raw["records"][0]["dates"][0]["value"] = value
        with pytest.raises(ValidationError):
            FixtureIndex.model_validate_json(json.dumps(raw))


def test_caps_are_partial_and_natural_exhaustion_is_complete() -> None:
    limited_articles = search_fixture(index(), request(page_size=3, max_articles=2))
    assert ids(limited_articles) == ["fixture-paper-01", "fixture-paper-02"]
    assert limited_articles.status == "partial" and limited_articles.reason == "article_cap"
    limited_pages = search_fixture(index(), request(page_size=2, max_pages=1))
    assert limited_pages.status == "partial" and limited_pages.reason == "page_cap"
    full = search_fixture(index(), request(page_size=10, max_articles=5))
    assert full.status == "complete" and len(full.records) == 5


def test_cursor_refuses_changed_query_filter_page_size_or_source_index() -> None:
    original = request({"journal": "Synthetic Journal A"}, page_size=1)
    first = search_fixture(index(), original)
    assert first.next_cursor is not None
    for changed in (
        request({"journal": "Synthetic Journal B"}, page_size=1),
        request({"journal": "Synthetic Journal A"}, page_size=2),
    ):
        with pytest.raises(FilterRefused, match="^fixture_cursor_mismatch$"):
            search_fixture(index(), changed, first.next_cursor)
    raw = json.loads(FIXTURE.read_text())
    raw["records"][0]["journal"] = "Changed authored index"
    with pytest.raises(FilterRefused, match="^fixture_cursor_mismatch$"):
        search_fixture(
            FixtureIndex.model_validate_json(json.dumps(raw)), original, first.next_cursor
        )
    with pytest.raises(FilterRefused, match="^fixture_query_unavailable$"):
        search_fixture(index(), original.model_copy(update={"query": "other"}), first.next_cursor)
    with pytest.raises(FilterRefused, match="^fixture_cursor_mismatch$"):
        search_fixture(
            index(),
            original,
            FixtureCursor(fingerprint=first.next_cursor.fingerprint, page=1, offset=2),
        )


def test_duplicate_article_identity_is_not_silently_deduplicated() -> None:
    raw = json.loads(FIXTURE.read_text())
    raw["records"][1]["id"] = raw["records"][0]["id"]
    with pytest.raises(ValidationError, match="duplicate_fixture_identity"):
        FixtureIndex.model_validate_json(json.dumps(raw))

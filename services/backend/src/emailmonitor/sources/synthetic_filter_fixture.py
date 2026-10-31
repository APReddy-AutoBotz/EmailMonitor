"""Offline source-side filter contract fixture; not a registered acquisition adapter.

The complete index and its declarations are authored test data. This module has
no network, database, source registration or authority. Its cursor is a local
consistency token, not the signed tenant-bound cursor required by an API.
"""

import hashlib
import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from emailmonitor.jobs.models import Filters
from emailmonitor.sources.filter_capabilities import DateType, FilterCapabilities, assess_filters

FIXTURE_CAPABILITIES = FilterCapabilities(
    date_types=("published",), journal="exact", article_type="exact_any"
)


class FilterRefused(ValueError):
    """Fixed refusal only; never carries the query or source content."""


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class DeclaredDate(Contract):
    type: DateType
    value: str = Field(min_length=10, max_length=10)

    @field_validator("value")
    @classmethod
    def calendar_day(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ValueError("full_calendar_date_required") from None
        if parsed.isoformat() != value:
            raise ValueError("full_calendar_date_required")
        return value


class IndexedArticle(Contract):
    id: str = Field(pattern=r"^fixture-paper-[0-9]{2}$")
    dates: tuple[DeclaredDate, ...] = Field(max_length=3)
    journal: str | None = Field(max_length=300)
    article_type: str | None = Field(max_length=100)


class FixtureIndex(Contract):
    schema_version: Literal["synthetic-filter-index-v1"]
    query: str = Field(min_length=1, max_length=200)
    records: tuple[IndexedArticle, ...] = Field(max_length=1000)
    completeness: Literal["authored_complete_index"]

    @model_validator(mode="after")
    def unique_ids(self) -> "FixtureIndex":
        if len({row.id for row in self.records}) != len(self.records):
            raise ValueError("duplicate_fixture_identity")
        return self


class FixtureRequest(Contract):
    query: str = Field(min_length=1, max_length=200)
    filters: Filters
    page_size: int = Field(ge=1, le=100)
    max_pages: int = Field(ge=1, le=1000)
    max_articles: int = Field(ge=1, le=500)


class FixtureCursor(Contract):
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    page: int = Field(ge=1, le=1000)
    offset: int = Field(ge=1, le=500)


class FixturePage(Contract):
    records: tuple[IndexedArticle, ...] = Field(max_length=100)
    fixture_reported_total: int = Field(ge=0, le=1000)
    status: Literal["more", "complete", "partial"]
    reason: Literal["next_page", "source_exhausted", "page_cap", "article_cap"]
    next_cursor: FixtureCursor | None


def _fingerprint(index: FixtureIndex, request: FixtureRequest) -> str:
    payload = [index.model_dump(mode="json"), request.model_dump(mode="json")]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "ascii"
        )
    ).hexdigest()


def search_fixture(
    index: FixtureIndex, request: FixtureRequest, cursor: FixtureCursor | None = None
) -> FixturePage:
    """Apply supported predicates to the complete fixture index before pagination."""
    if request.query != index.query:
        raise FilterRefused("fixture_query_unavailable")
    decision = assess_filters(request.filters, FIXTURE_CAPABILITIES)
    if decision not in {"none_requested", "supported"}:
        raise FilterRefused(decision)
    filters = request.filters
    bounded_date = filters.publication_from is not None or filters.publication_to is not None
    for row in index.records:
        if (
            bounded_date
            and len([fact for fact in row.dates if fact.type == filters.publication_date_type]) != 1
        ):
            raise FilterRefused("fixture_date_evidence_incomplete")
        if filters.journal is not None and row.journal is None:
            raise FilterRefused("fixture_journal_evidence_incomplete")
        if filters.article_types and row.article_type is None:
            raise FilterRefused("fixture_article_type_evidence_incomplete")

    matches = []
    for row in index.records:
        if bounded_date:
            observed = date.fromisoformat(
                next(fact.value for fact in row.dates if fact.type == filters.publication_date_type)
            )
            if filters.publication_from is not None and observed < filters.publication_from:
                continue
            if filters.publication_to is not None and observed > filters.publication_to:
                continue
        if filters.journal is not None and row.journal != filters.journal:
            continue
        if filters.article_types and row.article_type not in filters.article_types:
            continue
        matches.append(row)

    binding = _fingerprint(index, request)
    page, offset = (cursor.page, cursor.offset) if cursor else (0, 0)
    if cursor and (
        cursor.fingerprint != binding
        or offset != page * request.page_size
        or page >= request.max_pages
        or offset >= min(len(matches), request.max_articles)
    ):
        raise FilterRefused("fixture_cursor_mismatch")
    end = min(offset + request.page_size, len(matches), request.max_articles)
    records = tuple(matches[offset:end])
    if end == len(matches):
        return FixturePage(
            records=records,
            fixture_reported_total=len(matches),
            status="complete",
            reason="source_exhausted",
            next_cursor=None,
        )
    if end >= request.max_articles:
        reason: Literal["article_cap", "page_cap"] = "article_cap"
    elif page + 1 >= request.max_pages:
        reason = "page_cap"
    else:
        return FixturePage(
            records=records,
            fixture_reported_total=len(matches),
            status="more",
            reason="next_page",
            next_cursor=FixtureCursor(fingerprint=binding, page=page + 1, offset=end),
        )
    return FixturePage(
        records=records,
        fixture_reported_total=len(matches),
        status="partial",
        reason=reason,
        next_cursor=None,
    )

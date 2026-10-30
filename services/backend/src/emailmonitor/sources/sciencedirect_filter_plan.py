"""Offline provider-native request descriptions; never a registered search adapter.

These narrower provider fields are not the application's day-inclusive or exact
journal filters. Nothing here authenticates, issues requests, or authorizes use.
"""

import json
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from emailmonitor.jobs.models import Filters, has_requested_filters
from emailmonitor.sources.sciencedirect import (
    SEARCH_PATH,
    Contract,
    RequestPlan,
    SearchRequest,
    _text,
)


class ProviderFilterRefused(ValueError):
    """A fixed category, without query or provider text."""


class DocumentedSearchCapabilities(Contract):
    """Documentation facts and unresolved semantics, not access rights."""

    live_execution: Literal[False] = False
    publication_day_filter: Literal[False] = False
    exact_journal_filter: Literal[False] = False
    article_type_filter: Literal[False] = False
    provider_publication_year_query: Literal[True] = True
    provider_title_search: Literal[True] = True
    year_range_endpoint_inclusivity: Literal["unspecified"] = "unspecified"
    title_matching: Literal["unspecified"] = "unspecified"
    title_scope: Literal["journal_or_book"] = "journal_or_book"
    source_result_limit: Literal[6000] = 6000
    complete_search_guarantee: Literal[False] = False


class DocumentedSearchRequest(Contract):
    """An explicit provider-native query; not a product search request."""

    query: str = Field(min_length=1, max_length=250)
    provider_publication_year_query: str | None = Field(default=None, max_length=9)
    provider_title_search: str | None = Field(default=None, max_length=250)
    offset: int = Field(default=0, ge=0, le=6000)
    show: Literal[10, 25, 50, 100] = 25
    sort_by: Literal["relevance", "date"] = "relevance"
    product_filters: Filters = Field(default_factory=Filters)

    @field_validator("query", "provider_title_search")
    @classmethod
    def safe_text(cls, value: str | None) -> str | None:
        return _text(value) if value is not None else None

    @field_validator("provider_publication_year_query")
    @classmethod
    def bounded_year_syntax(cls, value: str | None) -> str | None:
        if value is not None:
            if re.fullmatch(r"[0-9]{4}(?:-[0-9]{4})?", value) is None:
                raise ValueError("provider_year_syntax_invalid")
            if len(value) == 9 and value[:4] > value[5:]:
                raise ValueError("provider_year_range_unordered")
        return value

    @model_validator(mode="after")
    def inside_documented_result_window(self) -> "DocumentedSearchRequest":
        # Offset 6000 is documented, but accepting a page crossing the separate
        # 6000-result cap could imply retrievability beyond it. Be conservative.
        if self.offset + self.show > 6000:
            raise ValueError("provider_result_window_exceeded")
        return self

    def plan(self) -> "DocumentedSearchPlan":
        if has_requested_filters(self.product_filters):
            raise ProviderFilterRefused("product_filters_unsupported")
        # Reuse only the inert base request's validation and serialization.
        base = SearchRequest(
            query=self.query, offset=self.offset, show=self.show, sort_by=self.sort_by
        )
        body = json.loads(base.body())
        if self.provider_publication_year_query is not None:
            body["date"] = self.provider_publication_year_query
        if self.provider_title_search is not None:
            body["pub"] = self.provider_title_search
        plan = RequestPlan(
            method="PUT",
            path=SEARCH_PATH,
            media_type="application/json",
            body=json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("ascii"),
        )
        return DocumentedSearchPlan(request=plan)


class DocumentedSearchPlan(Contract):
    request: RequestPlan
    capabilities: DocumentedSearchCapabilities = Field(default_factory=DocumentedSearchCapabilities)
    # No provider response or stable inventory exists in this offline plan.
    result_status: Literal["unknown_may_be_truncated"] = "unknown_may_be_truncated"

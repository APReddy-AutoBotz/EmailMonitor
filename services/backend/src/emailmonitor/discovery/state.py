"""Deterministic durable checkpoint reducer; no I/O or execution authority."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from emailmonitor.discovery.search import SearchPage


class DiscoveryState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["pending", "completed", "partial", "needs_refinement", "unsupported"]
    reason: str = Field(min_length=1, max_length=100)
    next_url: str | None = Field(default=None, max_length=2048)
    pages: list[str] = Field(default_factory=list, max_length=1000)
    digests: list[str] = Field(default_factory=list, max_length=1000)
    articles: list[str] = Field(default_factory=list, max_length=500)
    raw_entries: int = Field(default=0, ge=0, le=500000)
    duplicates: int = Field(default=0, ge=0, le=500000)
    reported_total: int | None = Field(default=None, ge=0, le=1000000)
    completeness: Literal["unknown", "partial", "pagination_exhausted", "single_article"] = (
        "unknown"
    )
    api_fallback: Literal["unavailable_not_attempted"] = "unavailable_not_attempted"
    discovery_complete: bool = False
    extraction_implemented: Literal[False] = False

    @model_validator(mode="after")
    def consistent(self) -> "DiscoveryState":
        if (self.status == "completed") != self.discovery_complete:
            raise ValueError("Only proven scoped exhaustion/single article is complete")
        if (self.status == "pending") != (self.next_url is not None):
            raise ValueError("Only pending discovery has a next page")
        if len(self.pages) != len(self.digests) or len(set(self.pages)) != len(self.pages):
            raise ValueError("Unique page checkpoints and digests must agree")
        if len(set(self.articles)) != len(self.articles):
            raise ValueError("Frontier URLs must be unique")
        return self


def advance(
    state: DiscoveryState, page: SearchPage, max_pages: int, max_articles: int
) -> DiscoveryState:
    if not 1 <= max_pages <= 1000 or not 1 <= max_articles <= 500:
        raise ValueError("Platform discovery caps required")
    if state.status != "pending" or page.url != state.next_url or page.url in state.pages:
        raise ValueError("Current uncommitted page required")
    values = state.model_dump()
    values["pages"] = [*state.pages, page.url]
    values["digests"] = [*state.digests, page.digest]
    values["next_url"] = None
    if page.digest in state.digests:
        values.update(status="partial", reason="repeated_page_content", completeness="partial")
        return DiscoveryState.model_validate(values)
    if not page.selector_valid:
        values.update(status="partial", reason="selectors_changed", completeness="partial")
        return DiscoveryState.model_validate(values)
    if page.reported_total is not None:
        if state.reported_total not in (None, page.reported_total):
            values.update(status="partial", reason="reported_total_changed", completeness="partial")
            return DiscoveryState.model_validate(values)
        values["reported_total"] = page.reported_total
    articles = list(state.articles)
    duplicates = state.duplicates
    capped = False
    for url in page.articles:
        if url in articles:
            duplicates += 1
        elif len(articles) < max_articles:
            articles.append(url)
        else:
            capped = True
    values.update(
        articles=articles, duplicates=duplicates, raw_entries=state.raw_entries + len(page.articles)
    )
    if capped:
        values.update(status="partial", reason="article_cap", completeness="partial")
    elif page.exhausted:
        values.update(
            status="completed",
            discovery_complete=True,
            reason="pagination_exhausted",
            completeness="pagination_exhausted",
        )
    elif len(articles) >= max_articles:
        values.update(status="partial", reason="article_cap", completeness="partial")
    elif page.next_url in values["pages"]:
        values.update(status="partial", reason="repeated_cursor", completeness="partial")
    elif len(values["pages"]) >= max_pages:
        values.update(status="partial", reason="page_cap", completeness="partial")
    elif not page.articles or articles == state.articles:
        values.update(status="partial", reason="no_new_results", completeness="partial")
    else:
        values.update(next_url=page.next_url, reason="next_page")
    return DiscoveryState.model_validate(values)

"""Declarative filter semantics; classification never grants source authority."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from emailmonitor.jobs.models import Filters, has_requested_filters

type DateType = Literal["published", "online", "issue"]
type FilterReason = Literal[
    "none_requested",
    "supported",
    "date_type_required",
    "date_type_unavailable",
    "journal_unavailable",
    "article_type_unavailable",
    "blank_filter",
]


class FilterCapabilities(BaseModel):
    """A reviewed adapter declaration, not a request-supplied authorization."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    version: Literal["source-filter-capability-v1"] = "source-filter-capability-v1"
    date_types: tuple[DateType, ...] = Field(default=(), max_length=3)
    journal: Literal["unsupported", "exact"] = "unsupported"
    article_type: Literal["unsupported", "exact_any"] = "unsupported"

    @model_validator(mode="after")
    def distinct_date_types(self) -> "FilterCapabilities":
        if len(set(self.date_types)) != len(self.date_types):
            raise ValueError("duplicate_date_type")
        return self


# The currently registered fixture source has no source-side filter semantics.
REGISTERED_FIXTURE_FILTERS = FilterCapabilities()


def assess_filters(filters: Filters, capability: FilterCapabilities) -> FilterReason:
    """Classify the whole request; no filter may be silently omitted."""
    if not has_requested_filters(filters):
        return "none_requested"
    if filters.journal is not None and not filters.journal.strip():
        return "blank_filter"
    if any(not value.strip() for value in filters.article_types):
        return "blank_filter"
    if filters.publication_from is not None or filters.publication_to is not None:
        if filters.publication_date_type is None:
            return "date_type_required"
        if filters.publication_date_type not in capability.date_types:
            return "date_type_unavailable"
    if filters.journal is not None and capability.journal != "exact":
        return "journal_unavailable"
    if filters.article_types and capability.article_type != "exact_any":
        return "article_type_unavailable"
    return "supported"

"""Metadata-only progress and tenant/job-bound durable event contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from emailmonitor.progress.state import ItemCounts, Outcome

JobState = Literal[
    "draft",
    "awaiting_approval",
    "ready",
    "queued",
    "running",
    "pausing",
    "paused",
    "cancelling",
    "cancelled",
    "completed",
    "completed_partial",
    "failed",
]


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    organization_id: UUID
    job_id: UUID
    state: JobState
    revision: int = Field(ge=1)
    generation: int = Field(ge=1)
    discovery_pages: int = Field(ge=0, le=1000)
    source_reported_total: int | None = Field(ge=0, le=1000000)
    unique_articles: int = Field(ge=0, le=500)
    duplicates: int = Field(ge=0, le=500000)
    discovery_complete: bool
    completeness: Literal["unknown", "partial", "pagination_exhausted", "single_article"]
    discovery_stop_reason: str = Field(min_length=1, max_length=100)
    counts: ItemCounts
    accepted_associations: int = Field(ge=0, le=5000000)
    review_needed_associations: int = Field(ge=0, le=5000000)
    progress_percent: int | None = Field(ge=0, le=100)
    last_sequence: int = Field(ge=0, le=9223372036854775807)
    synthetic_only: Literal[True] = True
    production_execution_available: Literal[False] = False

    @field_validator("synthetic_only", "production_execution_available", mode="before")
    @classmethod
    def actual_boolean(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("Actual execution availability boolean required")
        return value

    @model_validator(mode="after")
    def conserved_progress(self) -> "Snapshot":
        if self.unique_articles != self.counts.discovered:
            raise ValueError("Durable frontier and item totals disagree")
        expected = (
            None
            if not self.discovery_complete
            else (
                100
                if self.unique_articles == 0
                else self.counts.terminal * 100 // self.unique_articles
            )
        )
        if self.progress_percent != expected:
            raise ValueError("Unknown/capped enumeration cannot claim a complete percentage")
        return self


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal["1.0"] = "1.0"
    organization_id: UUID
    job_id: UUID
    sequence: int = Field(ge=1, le=9223372036854775807)
    event_id: UUID
    event_type: Literal[
        "job.queued",
        "job.discovery_progress",
        "job.item_terminal",
        "job.paused",
        "job.cancelled",
        "job.finished",
        "association.reviewed",
    ]
    aggregate_version: int = Field(ge=1)
    item_id: UUID | None
    batch_id: UUID | None
    association_id: UUID | None
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone-aware durable event timestamp required")
        return value

    @model_validator(mode="after")
    def association_identifiers(self) -> "Event":
        review = self.event_type == "association.reviewed"
        if (review and (self.batch_id is None or self.association_id is None)) or (
            not review and (self.batch_id is not None or self.association_id is not None)
        ):
            raise ValueError("Review event requires actual batch/association identifiers")
        return self


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: UUID
    work_kind: Literal["discover", "article"]
    state: Outcome
    reason: Literal[
        "scheduled",
        "leased",
        "observed",
        "no_contact",
        "requires_review",
        "browser_not_completed",
        "xml_partial",
        "xml_unsupported",
        "source_policy_changed",
        "worker_failure",
        "lease_exhausted",
        "user_cancelled",
        "pagination_committed",
        "quota_exhausted",
    ]
    attempts: int = Field(ge=0, le=3)
    batch_id: UUID | None
    completed_at: datetime | None
    inherited_job_id: UUID | None = None
    inherited_item_id: UUID | None = None

    @model_validator(mode="after")
    def inherited_receipt(self) -> "Item":
        if (self.inherited_job_id is None) != (self.inherited_item_id is None):
            raise ValueError("Inherited receipt requires both same-tenant provenance identifiers")
        if self.inherited_job_id is not None and self.state in {
            "pending",
            "running",
            "retry_wait",
            "failed",
        }:
            raise ValueError("Only terminal prior receipts may be inherited")
        return self

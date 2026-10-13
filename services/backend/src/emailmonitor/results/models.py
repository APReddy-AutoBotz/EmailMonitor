"""Observed correspondence, article outcomes and export eligibility remain distinct."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from emailmonitor.associations.api import Identifier
from emailmonitor.associations.models import Evidence
from emailmonitor.progress.state import Outcome


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Filters(Record):
    job_id: UUID | None = None
    states: tuple[Literal["accepted", "needs_review", "unmatched", "rejected"], ...] = ("accepted",)
    author_target: Literal["all", "first", "corresponding"] = "all"
    query: str = Field(default="", max_length=100)

    @field_validator("states")
    @classmethod
    def unique_states(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(set(value)) != len(value):
            raise ValueError("Distinct requested result states required")
        return value

    @field_validator("query")
    @classmethod
    def literal_query(cls, value: str) -> str:
        if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("Bounded printable literal query required")
        return value


class Contact(Record):
    organization_id: UUID
    job_id: UUID
    batch_id: UUID
    association_id: UUID
    revision: int = Field(ge=1)
    candidate_id: UUID
    author_id: UUID | None
    author_name: str | None = Field(default=None, max_length=300)
    first_author: bool | None
    corresponding_author: bool | None
    affiliations: tuple[Annotated[str, Field(max_length=1000)], ...] = Field(max_length=20)
    raw_address: str = Field(min_length=1, max_length=320)
    normalized_address: str | None = Field(default=None, max_length=320)
    state: Literal["accepted", "needs_review", "unmatched", "rejected"]
    identity_state: Literal["article_local_unresolved"] = "article_local_unresolved"
    evidence_strength: Literal["explicit", "supported", "ambiguous", "none"]
    association_reason: str = Field(min_length=1, max_length=64)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=40)
    source_id: Literal["synthetic-publisher"] = "synthetic-publisher"
    source_url: str = Field(min_length=1, max_length=2048)
    policy_version: int = Field(ge=1)
    title: str | None = Field(default=None, max_length=1000)
    observed_at: datetime
    syntax_status: Literal["valid", "invalid", "unsupported"]
    technical_status: Literal["not_checked"] = "not_checked"
    delivery_status: Literal["unverified"] = "unverified"
    outreach_eligibility: Literal["not_assessed"] = "not_assessed"

    @field_validator("observed_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Observed UTC-aware time required")
        return value

    @model_validator(mode="after")
    def accepted_evidence(self) -> "Contact":
        if self.state == "accepted" and (
            self.author_id is None
            or self.author_name is None
            or self.normalized_address is None
            or self.syntax_status != "valid"
            or self.evidence_strength not in {"explicit", "supported"}
        ):
            raise ValueError("Accepted correspondence requires observed author/address evidence")
        return self


class ArticleOutcome(Record):
    organization_id: UUID
    job_id: UUID
    item_id: UUID
    source_url: str = Field(min_length=1, max_length=2048)
    state: Outcome
    reason: str = Field(min_length=1, max_length=64)
    batch_id: UUID | None
    completed_at: datetime | None
    inherited_job_id: UUID | None
    observation_status: (
        Literal["observed", "no_contact", "requires_browser", "partial", "unsupported"] | None
    )
    technical_status: Literal["not_checked"] = "not_checked"
    outreach_eligibility: Literal["not_assessed"] = "not_assessed"


class EvidenceView(Record):
    organization_id: UUID
    batch_id: UUID
    source_url: str = Field(min_length=1, max_length=2048)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    citation: Evidence
    synthetic: Literal[True] = True
    raw_document_available: Literal[False] = False


class ContactPage(Record):
    items: tuple[Contact, ...] = Field(max_length=200)
    next_cursor: str | None = Field(default=None, max_length=2048)
    synthetic: Literal[True] = True


class OutcomePage(Record):
    items: tuple[ArticleOutcome, ...] = Field(max_length=200)
    next_cursor: str | None = Field(default=None, max_length=2048)
    synthetic: Literal[True] = True


class ExportInput(BaseModel):
    # UUID text and arrays are normal HTTP JSON; trusted internals validate Filters.
    model_config = ConfigDict(extra="forbid")
    job_id: Identifier | None = None
    format: Literal["csv", "xlsx"]
    purpose: Literal["academic_contact_research"]
    include_unresolved: bool = Field(default=False, strict=True)
    include_article_outcomes: bool = Field(default=True, strict=True)
    author_target: Literal["all", "first", "corresponding"] = "all"
    query: str = Field(default="", max_length=100, strict=True)

    ttl_seconds: int = Field(default=86400, ge=1, le=86400, strict=True)

    @field_validator("query")
    @classmethod
    def literal_query(cls, value: str) -> str:
        return Filters.literal_query(value)

    def filters(self) -> Filters:
        return Filters(
            job_id=self.job_id,
            states=("accepted", "needs_review", "unmatched")
            if self.include_unresolved
            else ("accepted",),
            author_target=self.author_target,
            query=self.query,
        )


class ExportState(Record):
    organization_id: UUID
    id: UUID
    requested_by: UUID
    format: Literal["csv", "xlsx"]
    purpose: Literal["academic_contact_research"]
    state: Literal["queued", "running", "ready", "failed", "revoked", "expired"]
    reason: Literal[
        "scheduled",
        "rendering",
        "complete",
        "unsafe_csv_cell",
        "snapshot_changed",
        "worker_failure",
        "unsupported_text",
        "render_limit",
        "user_revoked",
        "expired",
    ]
    revision: int = Field(ge=1)
    generation: int = Field(ge=1)
    download_available: bool = False
    contacts: int = Field(ge=0, le=2000)
    article_outcomes: int = Field(ge=0, le=2000)
    created_at: datetime
    expires_at: datetime
    synthetic: Literal[True] = True
    production_enabled: Literal[False] = False


class ExportSnapshot(Record):
    schema_version: Literal["1.0"] = "1.0"
    organization_id: UUID
    export_id: UUID
    requested_by: UUID
    purpose: Literal["academic_contact_research"]
    filters: Filters
    format: Literal["csv", "xlsx"]
    include_article_outcomes: bool
    contacts: tuple[Contact, ...] = Field(max_length=2000)
    article_outcomes: tuple[ArticleOutcome, ...] = Field(max_length=2000)
    created_at: datetime
    expires_at: datetime
    synthetic: Literal[True] = True
    technical_checks_performed: Literal[False] = False
    outreach_approved: Literal[False] = False

    @field_validator("expires_at", "created_at")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("UTC-aware export timestamp required")
        return value

    @model_validator(mode="after")
    def scoped_snapshot(self) -> "ExportSnapshot":
        if (
            self.expires_at <= self.created_at
            or (self.expires_at - self.created_at).total_seconds() > 86400
        ):
            raise ValueError("Export expiry must be current-policy bounded within24hours")
        if any(item.organization_id != self.organization_id for item in self.contacts) or any(
            item.organization_id != self.organization_id for item in self.article_outcomes
        ):
            raise ValueError("Snapshot records must share the authoritative tenant")
        if len({(item.batch_id, item.association_id) for item in self.contacts}) != len(
            self.contacts
        ):
            raise ValueError("Duplicate snapshot associations are not extra contacts")
        if len({(item.job_id, item.item_id) for item in self.article_outcomes}) != len(
            self.article_outcomes
        ):
            raise ValueError("Distinct durable article units required")
        if not self.include_article_outcomes and self.article_outcomes:
            raise ValueError("Unrequested article outcomes cannot enter the artifact")
        if any(
            item.state == "rejected" or item.state not in self.filters.states
            for item in self.contacts
        ):
            raise ValueError("Export snapshots cannot contain rejected/unrequested associations")
        return self

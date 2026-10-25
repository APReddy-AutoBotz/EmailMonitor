"""Observed correspondence, article outcomes and export eligibility remain distinct."""

import re
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from emailmonitor.associations.api import Identifier
from emailmonitor.associations.models import Evidence
from emailmonitor.progress.state import Outcome


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


ArticleOutcomePresence = Literal[
    "all", "observed_candidate", "completed_without_candidate", "unresolved"
]


class ArticleSelection(BaseModel):
    """New default keys are omitted so legacy cursor/request identities stay stable."""

    source_id: Literal["synthetic-publisher"] | None = None
    paper_doi: str | None = Field(default=None, max_length=256, strict=True)

    @field_validator("paper_doi")
    @classmethod
    def validated_paper_doi(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if re.fullmatch(r"10\.[0-9]{4,9}/[A-Za-z0-9._;()/:-]+", value) is None or any(
            segment in ("", ".", "..") for segment in value.split("/")
        ):
            raise ValueError("Supported bare observed DOI required")
        return value.lower()

    @model_serializer(mode="wrap")
    def legacy_defaults(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document: dict[str, Any] = handler(self)
        if document.get("source_id") is None:
            document.pop("source_id", None)
        if document.get("paper_doi") is None:
            document.pop("paper_doi", None)
        if document.get("item_id") is None:
            document.pop("item_id", None)
        if document.get("article_outcome_presence") == "all":
            document.pop("article_outcome_presence", None)
        return document


class Filters(ArticleSelection, Record):
    job_id: UUID | None = None
    states: tuple[Literal["accepted", "needs_review", "unmatched", "rejected"], ...] = ("accepted",)
    author_target: Literal["all", "first", "corresponding"] = "all"
    query: str = Field(default="", max_length=100)
    item_id: UUID | None = None
    article_outcome_presence: ArticleOutcomePresence = "all"

    @model_validator(mode="after")
    def selected_item_requires_job(self) -> "Filters":
        if self.item_id is not None and self.job_id is None:
            raise ValueError("Exact article item selection requires its job")
        return self

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


class ExportInput(ArticleSelection):
    # UUID text and arrays are normal HTTP JSON; trusted internals validate Filters.
    model_config = ConfigDict(extra="forbid")
    job_id: Identifier | None = None
    item_id: Identifier | None = None
    article_outcome_presence: ArticleOutcomePresence = "all"
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

    optional_contact_fields: tuple[Literal["affiliations", "article_title"], ...] = Field(
        default=("affiliations", "article_title"),
        max_length=2,
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("optional_contact_fields")
    @classmethod
    def distinct_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Distinct allowlisted optional fields required")
        return value

    @model_validator(mode="after")
    def selected_item_requires_job(self) -> "ExportInput":
        if self.item_id is not None and self.job_id is None:
            raise ValueError("Exact article item selection requires its job")
        return self

    def filters(self) -> Filters:
        return Filters(
            job_id=self.job_id,
            paper_doi=self.paper_doi,
            source_id=self.source_id,
            item_id=self.item_id,
            article_outcome_presence=self.article_outcome_presence,
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


class ArticleFilterBinding(Record):
    job_id: UUID
    item_id: UUID
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExportSnapshot(Record):
    schema_version: Literal["1.0"] = "1.0"
    organization_id: UUID
    export_id: UUID
    requested_by: UUID
    purpose: Literal["academic_contact_research"]
    filters: Filters
    format: Literal["csv", "xlsx"]
    include_article_outcomes: bool
    optional_contact_fields: tuple[Literal["affiliations", "article_title"], ...] = Field(
        default=("affiliations", "article_title"),
        max_length=2,
        json_schema_extra={"uniqueItems": True},
    )
    article_filter_bindings: tuple[ArticleFilterBinding, ...] = Field(default=(), max_length=2001)
    contacts: tuple[Contact, ...] = Field(max_length=2000)
    article_outcomes: tuple[ArticleOutcome, ...] = Field(max_length=2000)
    created_at: datetime
    expires_at: datetime
    synthetic: Literal[True] = True
    technical_checks_performed: Literal[False] = False
    outreach_approved: Literal[False] = False

    @model_serializer(mode="wrap")
    def legacy_binding_default(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document: dict[str, Any] = handler(self)
        if (
            self.filters.paper_doi is None
            and self.filters.item_id is None
            and self.filters.article_outcome_presence == "all"
        ):
            document.pop("article_filter_bindings", None)
        return document

    @field_validator("optional_contact_fields")
    @classmethod
    def distinct_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return ExportInput.distinct_fields(value)

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
        identities = {(item.job_id, item.item_id) for item in self.article_outcomes}
        expected_bindings = set(identities)
        if self.filters.item_id is not None:
            if any(
                item.job_id != self.filters.job_id or item.item_id != self.filters.item_id
                for item in self.article_outcomes
            ):
                raise ValueError("Outcome records must match the exact selected article")
            assert self.filters.job_id is not None
            expected_bindings.add((self.filters.job_id, self.filters.item_id))
        if (
            self.filters.paper_doi is not None
            or self.filters.item_id is not None
            or self.filters.article_outcome_presence != "all"
        ):
            actual_bindings = {(item.job_id, item.item_id) for item in self.article_filter_bindings}
            if actual_bindings != expected_bindings or len(actual_bindings) != len(
                self.article_filter_bindings
            ):
                raise ValueError("Filtered snapshots require exact immutable article bindings")
        elif self.article_filter_bindings:
            raise ValueError("Legacy snapshots have no article-filter binding records")
        return self


class ExportPreview(Record):
    organization_id: UUID
    contacts: int = Field(ge=0, le=2000)
    article_outcomes: int = Field(ge=0, le=2000)
    optional_contact_fields: tuple[Literal["affiliations", "article_title"], ...]
    counts_may_change: Literal[True] = True
    excluded_reasons: tuple[
        Literal[
            "unaccepted_excluded_by_default",
            "rejected_and_suppressed_excluded",
            "unavailable_records_not_disclosed",
        ],
        ...,
    ]

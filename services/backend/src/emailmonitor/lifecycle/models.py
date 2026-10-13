"""Closed lifecycle requests, metadata receipts and conservative privacy grammar."""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from emailmonitor.associations.api import Identifier


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Retention(Closed):
    raw_hours: int = Field(default=24, ge=0, le=24)
    excerpt_days: int = Field(default=30, ge=0, le=30)
    contact_days: int = Field(default=90, ge=0, le=90)
    export_hours: int = Field(default=24, ge=0, le=24)
    audit_days: int = Field(default=365, ge=1, le=365)
    idempotency_hours: int = Field(default=24, ge=1, le=24)


class RetentionUpdate(Closed):
    expected_revision: int = Field(ge=1)
    retention: Retention


class RetentionState(Closed):
    organization_id: UUID
    revision: int = Field(ge=1)
    retention: Retention
    next_due_at: datetime


def canonical_privacy(kind: str, value: str) -> str:
    """ASCII synthetic privacy matching, not identity association or mailbox validation."""
    if not isinstance(value, str) or not value.isascii() or not 1 <= len(value) <= 254:
        raise ValueError("Bounded authored ASCII privacy value required")
    value = value.lower()
    domain = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
    local = r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    if kind == "source" and value == "synthetic-publisher":
        return value
    if kind == "domain" and re.fullmatch(domain, value):
        return value
    if kind == "contact" and re.fullmatch(local + "@" + domain, value):
        if len(value.split("@", 1)[0]) <= 64:
            return value
    raise ValueError("Unsupported privacy value")


class SuppressionCreate(Closed):
    kind: Literal["source", "domain", "contact"]
    value: str = Field(min_length=1, max_length=254, repr=False)
    reason: Literal["privacy_request", "source_restriction"]

    @model_validator(mode="after")
    def canonical(self) -> "SuppressionCreate":
        canonical_privacy(self.kind, self.value)
        return self


class Suppression(Closed):
    organization_id: UUID
    id: UUID
    kind: Literal["source", "domain", "contact"]
    reason: Literal["privacy_request", "source_restriction"]
    active: bool
    created_at: datetime
    withdrawn_at: datetime | None

    @field_validator("active", mode="before")
    @classmethod
    def actual_boolean(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("Actual boolean required")
        return value


class DeletionRequest(Closed):
    job_id: Identifier | None
    reason: Literal["privacy_request", "retention_expired", "owner_request"]


class DeletionReceipt(Closed):
    organization_id: UUID
    id: UUID
    job_id: UUID | None
    reason: Literal["privacy_request", "retention_expired", "owner_request"]
    stage: Literal["fenced", "purged"]
    created_at: datetime
    purged_at: datetime | None
    backup_replay_required: Literal[True] = True

    @field_validator("backup_replay_required", mode="before")
    @classmethod
    def true_flag(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("Actual boolean required")
        return value


class SupportCreate(Closed):
    grantee_id: Identifier
    job_id: Identifier
    minutes: int = Field(ge=1, le=240)
    reason: Literal["synthetic_incident", "synthetic_privacy_check"]


class SupportContext(Closed):
    organization_id: UUID
    id: UUID
    grantee_id: UUID
    job_id: UUID
    reason: Literal["synthetic_incident", "synthetic_privacy_check"]
    expires_at: datetime
    revoked_at: datetime | None


class SupportInspection(Closed):
    organization_id: UUID
    context_id: UUID
    job_id: UUID
    job_state: Literal[
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
    generation: int = Field(ge=1)
    retained_observations: int = Field(ge=0)
    content_access: Literal[False] = False

    @field_validator("content_access", mode="before")
    @classmethod
    def false_flag(cls, value: object) -> object:
        if type(value) is not bool:
            raise ValueError("Actual boolean required")
        return value

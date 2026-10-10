"""Immutable synthetic platform ceiling; policy decisions never perform I/O."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Operation(StrEnum):
    SEARCH = "search"
    HTML = "fetch_html"
    BROWSER = "browser"
    EXTRACT = "extract_contacts"
    EXCERPT = "retain_excerpt"
    EXPORT = "export_contacts"


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_concurrent_requests: int = Field(ge=1, le=1)
    min_request_interval_seconds: float = Field(ge=5, le=86400, allow_inf_nan=False)
    max_articles_per_job: int = Field(ge=1, le=500)


class Retention(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    raw_hours: int = Field(ge=0, le=24)
    excerpt_days: int = Field(ge=0, le=30)
    contact_days: int = Field(ge=0, le=90)


class PolicyProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execution_mode: Literal["fixture"] = "fixture"
    purpose: Literal["academic_contact_research"]
    allowed_hosts: list[Literal["synthetic.publisher.example"]] = Field(min_length=1, max_length=1)
    allowed_operations: list[Operation] = Field(min_length=1, max_length=6)
    permission_reference: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    credential_reference: None = None
    allowed_regions: list[Literal["test-only"]] = Field(min_length=1, max_length=1)
    robots_handling: Literal["fixture_no_network"]
    limits: Limits
    retention: Retention
    export_contacts_allowed: bool = False
    valid_until: datetime

    @field_validator("valid_until")
    @classmethod
    def aware_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Expiry must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def operations_consistent(self) -> "PolicyProposal":
        if len(set(self.allowed_operations)) != len(self.allowed_operations):
            raise ValueError("Operations must be unique")
        if self.export_contacts_allowed != (Operation.EXPORT in self.allowed_operations):
            raise ValueError("Export operation and permission must agree")
        if self.retention.excerpt_days and Operation.EXCERPT not in self.allowed_operations:
            raise ValueError("Excerpt retention requires its own operation")
        return self


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    policy: PolicyProposal


class Transition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    expected_revision: int = Field(ge=1)
    state: Literal["approved", "suspended", "revoked"]


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    operation: Operation
    host: str = Field(max_length=253)
    path: str = Field(min_length=1, max_length=2048)
    execution_mode: Literal["fixture", "live"]


def validate_approval(policy: PolicyProposal, now: datetime) -> None:
    if not policy.permission_reference or not now < policy.valid_until <= now + timedelta(days=365):
        raise ValueError("Approval requires permission reference and bounded future expiry")

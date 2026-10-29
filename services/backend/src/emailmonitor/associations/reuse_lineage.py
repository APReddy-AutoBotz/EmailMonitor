"""Offline lineage shape; it neither establishes authority nor persists reuse."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class ReuseLineageDraft(BaseModel):
    """Keep the original observation identity and timestamps in a proposed link.

    Values must eventually come from transactionally locked database rows, not
    an API caller. This object is not a grant, a durable record or an authority
    check, and no route or worker executes it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    organization_id: UUID
    source_job_id: UUID
    target_job_id: UUID
    source_id: str = Field(min_length=1, max_length=200)
    article_url: str = Field(min_length=1, max_length=8192)
    source_revision: int = Field(gt=0)
    source_policy_version: int = Field(gt=0)
    source_generation: int = Field(gt=0)
    deletion_generation: int = Field(gt=0)
    acquisition_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: AwareDatetime
    expires_at: AwareDatetime
    fresh_since: AwareDatetime
    checked_at: AwareDatetime

    @field_validator("observed_at", "expires_at", "fresh_since", "checked_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_candidate(self) -> "ReuseLineageDraft":
        if self.source_job_id == self.target_job_id:
            raise ValueError("Source and target jobs must be independent")
        if self.fresh_since > self.checked_at:
            raise ValueError("Future freshness cutoff")
        if not self.fresh_since <= self.observed_at <= self.checked_at < self.expires_at:
            raise ValueError("Observation is outside the selected current window")
        return self

"""Closed service work references and immutable wall-time bounds.

These objects describe requested scope; they never confer authority. PostgreSQL
authenticates the service login and resolves its current delegation independently.
No browser token, requester identity or role can enter through a work reference.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_WORK_SECONDS = 21_600
type WorkPurpose = Literal["extraction", "export"]
type ServiceKind = Literal["worker", "publisher"]


class ServiceWork(BaseModel):
    """Trusted application scope, not a queue credential or bearer grant."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    organization: UUID
    resource: UUID
    purpose: WorkPurpose
    generation: int = Field(ge=1)


class WorkLifetime(BaseModel):
    """Lower configurable duration under doc21's conservative starting ceiling."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    seconds: int = Field(default=MAX_WORK_SECONDS, ge=1, le=MAX_WORK_SECONDS)

    def deadline(
        self,
        started_at: datetime,
        *,
        source_expires_at: datetime,
        resource_expires_at: datetime,
        prior_deadline: datetime | None = None,
    ) -> datetime:
        values: tuple[datetime, ...] = (started_at, source_expires_at, resource_expires_at)
        if prior_deadline is not None:
            values += (prior_deadline,)
        if any(type(value) is not datetime or value.utcoffset() is None for value in values):
            raise ValueError("Timezone-aware authority times required")
        deadline = min(
            started_at + timedelta(seconds=self.seconds),
            source_expires_at,
            resource_expires_at,
            *(() if prior_deadline is None else (prior_deadline,)),
        )
        if deadline <= started_at:
            raise ValueError("Positive bounded authority lifetime required")
        return deadline.astimezone(UTC)


class ServiceProcess(BaseModel):
    """Non-secret process identity; deployment registration remains separate."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: ServiceKind
    principal: UUID
    pass_limit: int = Field(default=100, ge=1, le=100)

    @field_validator("principal")
    @classmethod
    def nonzero_principal(cls, value: UUID) -> UUID:
        if value.int == 0:
            raise ValueError("Explicit registered service principal required")
        return value

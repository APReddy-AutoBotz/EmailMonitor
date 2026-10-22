"""Validate bounded service configuration before importing execution machinery."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from emailmonitor.runtime.authority import ServiceProcess


class ServiceRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    environment: Literal["test"]
    database_url: str = Field(repr=False)
    broker_url: str = Field(repr=False)
    queue: str
    organization: UUID
    process: ServiceProcess
    lease_seconds: int = Field(default=30, ge=1, le=120)
    profile: Literal["authored-html-service-reference", "controlled-xml-service-reference"] = (
        "authored-html-service-reference"
    )

    @model_validator(mode="after")
    def isolated(self) -> "ServiceRuntimeConfig":
        if self.queue != "em-fixture-" + self.organization.hex:
            raise ValueError("Tenant-isolated queue namespace required")
        from emailmonitor.runtime.assembly import _database_target

        _database_target(self.database_url)
        from emailmonitor.runtime.publisher import TestPublisherConfig

        TestPublisherConfig(
            environment=self.environment, broker_url=self.broker_url, queue=self.queue
        )
        return self

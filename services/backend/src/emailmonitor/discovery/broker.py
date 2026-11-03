"""Identifier-only test worker scheduling on the existing confirmed JSON broker."""

from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from emailmonitor.discovery.fixture import step_fixture
from emailmonitor.discovery.service import Discovery
from emailmonitor.jobs.models import StrictModel
from emailmonitor.jobs.queues import phase_queue
from emailmonitor.organizations.database import AuthorizationDenied


class DiscoveryEvent(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    event_type: Literal["discovery.page"] = "discovery.page"
    organization_id: str = Field(
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    )
    job_id: str = Field(
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    )
    event_id: str = Field(
        min_length=36,
        max_length=36,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    )
    generation: int = Field(ge=1)
    revision: int = Field(ge=1)

    @field_validator("organization_id", "job_id", "event_id")
    @classmethod
    def canonical_uuid(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("Canonical identifiers required")
        return value


def process(discovery: Discovery, organization: UUID, body: dict[str, object]) -> None:
    event = DiscoveryEvent.model_validate(body)
    if event.organization_id != str(organization):
        raise AuthorizationDenied()
    job = UUID(event.job_id)
    row = discovery.read(organization, job)
    if row["generation"] != event.generation:
        raise AuthorizationDenied()
    if not discovery.event_matches(organization, job, UUID(event.event_id), event.revision):
        raise AuthorizationDenied()
    discovery.received(organization, job, UUID(event.event_id))
    if int(str(row["revision"])) > event.revision:
        # Already committed uncertain/duplicate delivery. No second page fetch.
        return
    if row["revision"] != event.revision:
        raise ValueError("Future discovery revision denied")
    step_fixture(discovery, organization, job, event.revision)


def publish_discovery(application: Any, discovery: Discovery, organization: UUID) -> int:
    count = 0
    for row in discovery.pending(organization):
        event = DiscoveryEvent(
            organization_id=str(organization),
            job_id=str(row["job_id"]),
            event_id=str(row["event_id"]),
            generation=int(str(row["generation"])),
            revision=int(str(row["revision"])),
        )
        application.send_task(
            "emailmonitor.fixture.discover",
            args=[event.model_dump()],
            queue=phase_queue(application.conf.task_default_queue, "fixture_io"),
            routing_key=phase_queue(application.conf.task_default_queue, "fixture_io"),
            delivery_mode=2,
            mandatory=True,
            retry=False,
        )
        discovery.confirmed(organization, UUID(event.job_id), UUID(event.event_id))
        count += 1
    return count

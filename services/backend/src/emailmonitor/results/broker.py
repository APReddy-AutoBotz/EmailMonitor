"""Bounded IDs-only export work; PostgreSQL remains replay/current-authority source."""

from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from emailmonitor.jobs.models import StrictModel
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.results.service import Results


class ExportEvent(StrictModel):
    version: Literal[1] = 1
    kind: Literal["export.work"] = "export.work"
    organization_id: str = Field(min_length=36, max_length=36)
    export_id: str = Field(min_length=36, max_length=36)
    event_id: str = Field(min_length=36, max_length=36)
    generation: int = Field(ge=1)

    @field_validator("organization_id", "export_id", "event_id")
    @classmethod
    def canonical(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("Canonical UUID required")
        return value


def process(
    results: Results,
    org: UUID,
    body: dict[str, object],
    *,
    seconds: int = 30,
    after_claim: Callable[[], None] | None = None,
) -> bool:
    event = ExportEvent.model_validate(body)
    if event.organization_id != str(org):
        raise AuthorizationDenied()
    lease = results.claim(
        org, UUID(event.export_id), UUID(event.event_id), event.generation, seconds
    )
    if lease is None:
        return False
    if after_claim:
        after_claim()
    return results.process(lease)


def publish(application: Any, results: Results, org: UUID) -> int:
    count = 0
    for row in results.pending(org):
        event = ExportEvent(
            organization_id=str(org),
            export_id=str(row["export_id"]),
            event_id=str(row["event_id"]),
            generation=int(str(row["generation"])),
        )
        application.send_task(
            "emailmonitor.fixture.export",
            args=[event.model_dump()],
            queue=application.conf.task_default_queue,
            routing_key=application.conf.task_default_queue,
            delivery_mode=2,
            mandatory=True,
            retry=False,
        )
        results.confirmed(org, UUID(event.export_id), UUID(event.event_id))
        count += 1
    return count

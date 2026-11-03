"""Identifier-only scheduled cleanup; existing owned test queues and current owner."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from emailmonitor.jobs.queues import phase_queue
from emailmonitor.lifecycle.service import Lifecycle


class LifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    organization_id: UUID
    event_id: UUID
    kind: Literal["synthetic_retention_tick"] = "synthetic_retention_tick"


def process(service: Lifecycle, organization: UUID, body: dict[str, object]) -> int:
    import json

    event = LifecycleEvent.model_validate_json(json.dumps(body))
    if event.organization_id != organization:
        raise ValueError("Lifecycle event scope mismatch")
    return service.scheduled_tick(organization, event.event_id)


def publish(application: Any, service: Lifecycle, organization: UUID) -> int:
    events = service.schedule(organization)
    for identifier in events:
        event = LifecycleEvent(organization_id=organization, event_id=identifier)
        queue = phase_queue(application.conf.task_default_queue, "fixture_io")
        application.send_task(
            "emailmonitor.fixture.retention",
            args=[event.model_dump(mode="json")],
            queue=queue,
            routing_key=queue,
            delivery_mode=2,
            mandatory=True,
            retry=False,
        )
        service.confirmed(organization, identifier)
    return len(events)

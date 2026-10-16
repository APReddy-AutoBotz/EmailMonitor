"""Confirmed identifier-only work publication on the existing synthetic broker."""

from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from emailmonitor.jobs.diagnostics import Stage, emit
from emailmonitor.jobs.models import StrictModel
from emailmonitor.jobs.queues import phase_queue
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.progress.execution import ExecutionDispatcher, ExecutorFactory
from emailmonitor.progress.service import Progress


class ExecutionEvent(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    event_type: Literal["execution.work"] = "execution.work"
    organization_id: str = Field(min_length=36, max_length=36)
    job_id: str = Field(min_length=36, max_length=36)
    item_id: str = Field(min_length=36, max_length=36)
    event_id: str = Field(min_length=36, max_length=36)
    generation: int = Field(ge=1)

    @field_validator("organization_id", "job_id", "item_id", "event_id")
    @classmethod
    def identifier(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("Canonical UUID required")
        return value


def process(
    progress: Progress,
    organization: UUID,
    body: dict[str, object],
    *,
    seconds: int = 30,
    after_observation: Callable[[], None] | None = None,
    diagnostic: Callable[[Stage], None] | None = None,
    executor_factory: ExecutorFactory = ExecutionDispatcher,
) -> bool:
    event = ExecutionEvent.model_validate(body)
    if event.organization_id != str(organization):
        raise AuthorizationDenied()
    emit("validated", diagnostic)
    # PostgreSQL binds event/item/current generation and grants a current lease.
    # Admission may return before its inner delivery counter; zero is not proof
    # that the broker never delivered this task.
    emit("claim_enter", diagnostic)
    try:
        work = progress.claim(
            organization,
            UUID(event.job_id),
            UUID(event.item_id),
            UUID(event.event_id),
            seconds,
            event.generation,
        )
    except Exception:
        emit("claim_error", diagnostic)
        raise
    if work is None:
        emit("claim_empty", diagnostic)
        return False
    emit("claim_acquired", diagnostic)
    emit("process_enter", diagnostic)
    try:
        if work.lease.generation != event.generation:
            raise AuthorizationDenied()
        executor_factory(progress).process(work, after_observation=after_observation)
    except Exception:
        emit("process_error", diagnostic)
        raise
    emit("process_return", diagnostic)
    return True


def publish(application: Any, progress: Progress, organization: UUID) -> int:
    sent = 0
    for row in progress.pending(organization):
        event = ExecutionEvent(
            organization_id=str(organization),
            job_id=str(row["job_id"]),
            item_id=str(row["item_id"]),
            event_id=str(row["event_id"]),
            generation=int(str(row["generation"])),
        )
        if row["work_kind"] not in ("discover", "article"):
            raise ValueError("Unsupported server-owned execution phase")
        queue = phase_queue(
            application.conf.task_default_queue,
            "fixture_io" if row["work_kind"] == "discover" else "parse",
        )
        application.send_task(
            "emailmonitor.fixture.execute",
            args=[event.model_dump()],
            queue=queue,
            routing_key=queue,
            delivery_mode=2,
            mandatory=True,
            retry=False,
        )
        progress.confirmed(organization, UUID(event.job_id), UUID(event.event_id))
        sent += 1
    return sent

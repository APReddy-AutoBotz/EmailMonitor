"""Read-only elapsed queue-to-terminal interval from retained execution events."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from emailmonitor.progress.models import JobState


class JobTiming(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    view_version: Literal["job-timing-v1"] = "job-timing-v1"
    organization_id: UUID
    job_id: UUID
    revision: int = Field(ge=1)
    generation: int = Field(ge=1)
    state: JobState
    basis: Literal["first_queued_to_current_terminal_event"] = (
        "first_queued_to_current_terminal_event"
    )
    availability: Literal["recorded", "not_started", "not_terminal", "not_recorded", "inconsistent"]
    queued_at: datetime | None = None
    terminal_at: datetime | None = None
    elapsed_seconds: float | None = Field(default=None, ge=0)
    includes_waiting_and_pauses: Literal[True] = True


def project_timing(
    organization: UUID,
    job: UUID,
    state: JobState,
    revision: int,
    generation: int,
    queued_at: datetime | None,
    terminal_at: datetime | None,
    queued_sequence: int | None,
    terminal_sequence: int | None,
    terminal_revision: int | None,
) -> JobTiming:
    availability: Literal["recorded", "not_started", "not_terminal", "not_recorded", "inconsistent"]
    elapsed = None
    if state in {"draft", "awaiting_approval", "ready"}:
        availability = "not_started"
    elif state not in {"completed", "completed_partial", "failed", "cancelled"}:
        availability = "not_terminal"
    elif queued_at is None or terminal_at is None:
        availability = "not_recorded"
    elif (
        queued_at.utcoffset() is None
        or terminal_at.utcoffset() is None
        or queued_sequence is None
        or terminal_sequence is None
        or terminal_sequence <= queued_sequence
        or terminal_revision != revision
        or terminal_at < queued_at
    ):
        availability = "inconsistent"
    else:
        availability = "recorded"
        elapsed = (terminal_at - queued_at).total_seconds()
    return JobTiming(
        organization_id=organization,
        job_id=job,
        revision=revision,
        generation=generation,
        state=state,
        availability=availability,
        queued_at=queued_at if availability == "recorded" else None,
        terminal_at=terminal_at if availability == "recorded" else None,
        elapsed_seconds=elapsed,
    )

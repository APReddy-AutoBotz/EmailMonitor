"""Bounded metadata replay; each yielded frame needs fresh tenant authorization."""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Protocol
from uuid import UUID

from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.progress.models import Event, Snapshot
from emailmonitor.progress.state import cursor


class Reader(Protocol):
    def events(self, org: UUID, job: UUID, after: int) -> list[Event]: ...
    def snapshot(self, org: UUID, job: UUID) -> Snapshot: ...
    def authorize(self, org: UUID, job: UUID) -> None: ...


def frame(organization: UUID, job: UUID, event: Event) -> str:
    if event.organization_id != organization or event.job_id != job:
        raise AuthorizationDenied()
    payload = event.model_dump_json()
    if len(payload.encode()) > 2048:
        raise ValueError("Bounded metadata-only event required")
    return (
        f"id: {cursor(organization, job, event.sequence)}\n"
        f"event: {event.event_type}\ndata: {payload}\n\n"
    )


async def replay(
    reader: Reader,
    organization: UUID,
    job: UUID,
    after: int,
    *,
    duration: float = 60,
    poll_interval: float = 0.25,
    max_events: int = 100,
) -> AsyncIterator[str]:
    if not 0 < duration <= 60 or not 0.01 <= poll_interval <= 1 or not 1 <= max_events <= 100:
        raise ValueError("Bounded stream duration/poll/event limits required")
    deadline, sent = time.monotonic() + duration, 0
    try:
        while time.monotonic() < deadline:
            events = await asyncio.wait_for(
                asyncio.to_thread(reader.events, organization, job, after),
                timeout=max(0, deadline - time.monotonic()),
            )
            for event in events:
                if event.sequence <= after:
                    raise ValueError("Ordered durable replay sequence required")
                await asyncio.wait_for(
                    asyncio.to_thread(reader.authorize, organization, job),
                    timeout=max(0, deadline - time.monotonic()),
                )
                if time.monotonic() >= deadline:
                    return
                yield frame(organization, job, event)
                after, sent = event.sequence, sent + 1
                if sent >= max_events:
                    return
            if not events:
                current = await asyncio.wait_for(
                    asyncio.to_thread(reader.snapshot, organization, job),
                    timeout=max(0, deadline - time.monotonic()),
                )
                if current.state in {"cancelled", "completed", "completed_partial", "failed"}:
                    return
                await asyncio.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
                await asyncio.wait_for(
                    asyncio.to_thread(reader.authorize, organization, job),
                    timeout=max(0, deadline - time.monotonic()),
                )
                if time.monotonic() < deadline:
                    yield ": heartbeat\n\n"
    except (AuthorizationDenied, TimeoutError):
        # Close a previously authorized stream; never emit cached results/heartbeats.
        return

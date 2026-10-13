"""Pure metadata contract/replay checks, with no database, sockets or browser."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.progress.models import Event, Snapshot
from emailmonitor.progress.state import counts
from emailmonitor.progress.stream import frame, replay
from pydantic import ValidationError

ORG, JOB = uuid4(), uuid4()


def event(sequence: int = 1) -> Event:
    return Event(
        organization_id=ORG,
        job_id=JOB,
        sequence=sequence,
        event_id=uuid4(),
        event_type="job.queued",
        aggregate_version=1,
        item_id=None,
        batch_id=None,
        association_id=None,
        occurred_at=datetime.now(UTC),
    )


def snapshot(state: str = "completed") -> Snapshot:
    return Snapshot.model_validate(
        {
            "organization_id": ORG,
            "job_id": JOB,
            "state": state,
            "revision": 1,
            "generation": 1,
            "discovery_pages": 0,
            "source_reported_total": None,
            "unique_articles": 0,
            "duplicates": 0,
            "discovery_complete": True,
            "completeness": "pagination_exhausted",
            "discovery_stop_reason": "exhausted",
            "counts": counts([]),
            "accepted_associations": 0,
            "review_needed_associations": 0,
            "progress_percent": 100,
            "last_sequence": 0,
        }
    )


@pytest.mark.parametrize("field", ["batch_id", "association_id"])
def test_job_event_refuses_partial_review_identifiers(field: str) -> None:
    body = event().model_dump()
    body[field] = uuid4()
    with pytest.raises(ValidationError):
        Event.model_validate(body)


def test_review_requires_both_ids_and_timestamp_is_aware() -> None:
    body = event().model_dump()
    body["event_type"] = "association.reviewed"
    with pytest.raises(ValidationError):
        Event.model_validate(body)
    body.update(batch_id=uuid4(), association_id=uuid4())
    assert Event.model_validate(body).event_type == "association.reviewed"
    body["occurred_at"] = datetime(2026, 10, 13)
    with pytest.raises(ValidationError):
        Event.model_validate(body)


def test_metadata_frame_scope_and_no_arbitrary_content() -> None:
    value = event()
    result = frame(ORG, JOB, value)
    assert f"id: {ORG}/{JOB}:1\n" in result
    assert "event: job.queued\n" in result
    with pytest.raises(AuthorizationDenied):
        frame(uuid4(), JOB, value)
    body = value.model_dump()
    body["email"] = "never@example.test"
    with pytest.raises(ValidationError):
        Event.model_validate(body)


class MemoryReader:
    def __init__(self) -> None:
        self.authorizations = 0
        self.revoked_after = 100
        self.rows = [event(1), event(2)]

    def events(self, org: object, job: object, after: int) -> list[Event]:
        return [row for row in self.rows if row.sequence > after]

    def authorize(self, org: object, job: object) -> None:
        self.authorizations += 1
        if self.authorizations > self.revoked_after:
            raise AuthorizationDenied()

    def snapshot(self, org: object, job: object) -> Snapshot:
        return snapshot()


def collect(reader: MemoryReader, after: int = 0, maximum: int = 100) -> list[str]:
    async def run() -> list[str]:
        return [part async for part in replay(reader, ORG, JOB, after, max_events=maximum)]

    return asyncio.run(run())


def test_replay_and_reconnect_use_durable_sequence() -> None:
    reader = MemoryReader()
    assert len(collect(reader)) == 2 and reader.authorizations == 2
    assert len(collect(reader, after=1)) == 1
    assert len(collect(reader, maximum=1)) == 1


def test_revoked_tenant_cannot_receive_cached_second_frame() -> None:
    reader = MemoryReader()
    reader.revoked_after = 1
    assert len(collect(reader)) == 1


def test_revoked_before_first_frame_and_empty_terminal_stream_close() -> None:
    reader = MemoryReader()
    reader.revoked_after = 0
    assert collect(reader) == []
    reader.rows = []
    assert collect(reader) == []


@pytest.mark.parametrize("field,value", [("progress_percent", 0), ("unique_articles", 1)])
def test_snapshot_conservation(field: str, value: int) -> None:
    body = snapshot().model_dump()
    body[field] = value
    with pytest.raises(ValidationError):
        Snapshot.model_validate(body)


def test_unknown_enumeration_never_uses_source_total_as_denominator() -> None:
    body = snapshot().model_dump()
    body.update(
        discovery_complete=False,
        completeness="unknown",
        source_reported_total=900,
        progress_percent=None,
    )
    assert Snapshot.model_validate(body).progress_percent is None
    body["progress_percent"] = 0
    with pytest.raises(ValidationError):
        Snapshot.model_validate(body)


def test_slow_read_closes_at_bound_without_emitting_late_result() -> None:
    import time

    class SlowReader(MemoryReader):
        def events(self, org: object, job: object, after: int) -> list[Event]:
            time.sleep(0.05)
            return super().events(org, job, after)

    async def run() -> list[str]:
        return [part async for part in replay(SlowReader(), ORG, JOB, 0, duration=0.01)]

    assert asyncio.run(run()) == []


def test_unknown_or_nonmonotonic_replay_is_not_silently_accepted() -> None:
    reader = MemoryReader()
    reader.rows = [event(2), event(1)]
    with pytest.raises(ValueError, match="sequence"):
        collect(reader)


@pytest.mark.parametrize(
    "duration,interval,maximum", [(0, 0.25, 100), (61, 0.25, 100), (1, 0, 100), (1, 0.25, 101)]
)
def test_invalid_stream_limits_refuse(duration: float, interval: float, maximum: int) -> None:
    async def run() -> None:
        async for _ in replay(
            MemoryReader(),
            ORG,
            JOB,
            0,
            duration=duration,
            poll_interval=interval,
            max_events=maximum,
        ):
            pytest.fail("Invalid bounds produced a frame")

    with pytest.raises(ValueError):
        asyncio.run(run())

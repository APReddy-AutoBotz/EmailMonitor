"""Bounded synthetic admission diagnostics; never replace the receipt-gap oracle."""

import math
import time
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from emailmonitor.administration.source import SourceLease
from emailmonitor.fetching.resources import HopResources
from emailmonitor.fetching.safety import SafeURL
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.service import Progress
from emailmonitor.sources.policy import Operation
from sqlalchemy import text


class BrowserTiming:
    def __init__(self) -> None:
        self.records: list[dict[str, float | int]] = []
        self.failed = False

    def resources(
        self,
        delegate: HopResources,
        read: Callable[[object, float], Mapping[str, Any]],
    ) -> HopResources:
        timing = self

        class ObservedResources:
            def acquire(self, url: SafeURL, operation: Operation, deadline: float) -> object:
                ticket = delegate.acquire(url, operation, deadline)
                # An observation must never strand an acquired ticket. The normal
                # gateway still owns finish/abandon; completeness is checked later.
                try:
                    start = time.monotonic()
                    row = read(ticket, deadline)
                    end = time.monotonic()
                    attempt, admitted = row["attempts"], float(row["admitted"])
                    if (
                        len(timing.records) >= 2
                        or type(attempt) is not int
                        or attempt != len(timing.records) + 1
                        or not all(math.isfinite(n) for n in (start, end, admitted))
                        or end < start
                        or end >= deadline
                    ):
                        raise ValueError("Incomplete synthetic timing observation")
                    timing.records.append(
                        {"attempt": attempt, "admitted": admitted, "start": start, "end": end}
                    )
                except Exception:
                    timing.failed = True
                return ticket

            def finish(self, ticket: object, status: int | None, retry_after: str) -> None:
                delegate.finish(ticket, status, retry_after)

        return ObservedResources()

    def receipt(self, calls: list[dict[str, Any]]) -> dict[str, object]:
        complete = not self.failed and len(self.records) == len(calls) == 2
        value: dict[str, object] = {"complete": complete, "records": len(self.records)}
        if complete:
            first, second = self.records
            received = [float(call["received_monotonic"]) for call in calls]
            if not all(math.isfinite(n) for n in received):
                raise ValueError("Nonfinite synthetic receipt time")
            value.update(
                sql_admission_gap=second["admitted"] - first["admitted"],
                host_capture_gap=second["end"] - first["end"],
                fixture_receipt_gap=received[1] - received[0],
                capture_durations=[record["end"] - record["start"] for record in self.records],
            )
        return value


def read_admission_timing(
    progress: Progress,
    organization: UUID,
    job: UUID,
    version: int,
    ticket: object,
    deadline: float,
) -> dict[str, Any]:
    if not isinstance(ticket, SourceLease) or ticket.organization != organization:
        raise ValueError("Unexpected synthetic resource ticket")
    with progress.database.tenant(progress.token, organization, Capability.ACQUIRE_SOURCE) as (
        connection,
        _,
    ):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Synthetic timing deadline elapsed")
        connection.execute(
            text("SELECT set_config('statement_timeout',:milliseconds,true)"),
            {"milliseconds": str(max(1, min(5000, int(remaining * 1000))))},
        )
        row = (
            connection.execute(
                text("""SELECT b.attempts,
extract(epoch FROM b.ready_at - interval '5 seconds') AS admitted
FROM emailmonitor.source_resource_requests r
JOIN emailmonitor.tenant_source_buckets b
 ON (b.organization_id,b.source_id)=(r.organization_id,r.source_id)
JOIN emailmonitor.source_policies p
 ON (p.organization_id,p.source_id,p.version)=(r.organization_id,r.source_id,r.policy_version)
WHERE r.organization_id=:org AND r.id=:ticket AND r.job_id=:job
 AND r.source_id='synthetic-publisher' AND r.policy_version=:version
 AND r.operation='browser' AND r.state='active' AND r.lease_until>clock_timestamp()
 AND p.state='approved' AND p.valid_until>clock_timestamp()
 AND (p.policy->'limits'->>'min_request_interval_seconds')::numeric=5"""),
                {
                    "org": organization,
                    "ticket": ticket.identifier,
                    "job": job,
                    "version": version,
                },
            )
            .mappings()
            .one()
        )
    return dict(row)

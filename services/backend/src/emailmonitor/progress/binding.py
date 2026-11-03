"""Server-owned, transaction-local synthetic work scope, never request headers."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Connection, text


@dataclass(frozen=True)
class Lease:
    organization: UUID
    job: UUID
    item: UUID
    token: UUID
    generation: int
    deletion_generation: int


CURRENT: ContextVar[Lease | None] = ContextVar("emailmonitor_synthetic_work", default=None)


@contextmanager
def bound(lease: Lease) -> Iterator[None]:
    if (
        any(
            not isinstance(value, UUID)
            for value in (lease.organization, lease.job, lease.item, lease.token)
        )
        or type(lease.generation) is not int
        or type(lease.deletion_generation) is not int
        or lease.generation < 1
        or lease.deletion_generation < 1
    ):
        raise ValueError("Positive current work generations required")
    marker = CURRENT.set(lease)
    try:
        yield
    finally:
        CURRENT.reset(marker)


def apply(connection: Connection, organization: UUID) -> None:
    lease = CURRENT.get()
    if lease is not None and lease.organization != organization:
        raise ValueError("Work binding cannot change tenant authority")
    connection.execute(
        text("""SELECT set_config('emailmonitor.execution_job',:job,true),
set_config('emailmonitor.execution_item',:item,true),
set_config('emailmonitor.execution_token',:token,true),
set_config('emailmonitor.execution_generation',:generation,true),
set_config('emailmonitor.execution_deletion',:deletion,true)"""),
        {
            "job": str(lease.job) if lease else "",
            "item": str(lease.item) if lease else "",
            "token": str(lease.token) if lease else "",
            "generation": str(lease.generation) if lease else "",
            "deletion": str(lease.deletion_generation) if lease else "",
        },
    )


def allowed(connection: Connection, organization: UUID, job: UUID) -> bool:
    return bool(
        connection.execute(
            text("SELECT emailmonitor.execution_write_allowed(:org,:job)"),
            {"org": organization, "job": job},
        ).scalar_one()
    )


def matches(connection: Connection, organization: UUID, job: UUID, kind: str, url: str) -> bool:
    """Reject a different item's acquisition before any authored bytes are loaded."""
    return bool(
        connection.execute(
            text("""SELECT emailmonitor.execution_write_allowed(:org,:job) AND EXISTS(
SELECT 1 FROM emailmonitor.jobs j WHERE j.organization_id=:org AND j.id=:job AND
(j.state='draft' OR EXISTS(SELECT 1 FROM emailmonitor.execution_items i WHERE
 i.organization_id=j.organization_id AND i.job_id=j.id AND i.work_kind=:kind
 AND i.input_url=:url AND i.id::text=current_setting('emailmonitor.execution_item',true))))"""),
            {"org": organization, "job": job, "kind": kind, "url": url},
        ).scalar_one()
    )

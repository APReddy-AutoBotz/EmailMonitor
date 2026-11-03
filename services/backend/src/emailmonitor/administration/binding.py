"""Owned fixture admission context; never sourced from HTTP headers or page data."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Connection, text


@dataclass(frozen=True)
class FixtureLease:
    organization: UUID
    job: UUID
    url: str
    reference: UUID
    nonce: UUID


CURRENT: ContextVar[FixtureLease | None] = ContextVar(
    "emailmonitor_fixture_admission", default=None
)


@contextmanager
def bound(lease: FixtureLease) -> Iterator[None]:
    if any(
        type(value) is not UUID
        for value in (lease.organization, lease.job, lease.reference, lease.nonce)
    ):
        raise ValueError("Owned UUID fixture lease required")
    marker = CURRENT.set(lease)
    try:
        yield
    finally:
        CURRENT.reset(marker)


def apply(connection: Connection, organization: UUID) -> None:
    lease = CURRENT.get()
    if lease is not None and lease.organization != organization:
        raise ValueError("Fixture binding cannot change tenant authority")
    connection.execute(
        text("""SELECT set_config('emailmonitor.fixture_job',:job,true),
set_config('emailmonitor.fixture_url',:url,true),set_config('emailmonitor.fixture_reference',:reference,true),
set_config('emailmonitor.fixture_nonce',:nonce,true)"""),
        {
            "job": str(lease.job) if lease else "",
            "url": lease.url if lease else "",
            "reference": str(lease.reference) if lease else "",
            "nonce": str(lease.nonce) if lease else "",
        },
    )


def fence(connection: Connection, organization: UUID, job: UUID, url: str) -> None:
    from emailmonitor.organizations.database import AuthorizationDenied

    lease = CURRENT.get()
    if lease is None:
        return  # Running durable work retains its independent execution lease fence.
    if (lease.organization, lease.job, lease.url) != (
        organization,
        job,
        url,
    ) or not connection.execute(
        text("SELECT emailmonitor.fixture_commit_allowed(:org,:job,:url)"),
        {"org": organization, "job": job, "url": url},
    ).scalar_one():
        raise AuthorizationDenied()

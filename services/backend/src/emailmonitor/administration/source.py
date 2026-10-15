"""Actual protected-hop admission using short current-tenant metadata transactions.

No database connection spans DNS/TLS/browser work. Retry-After can only postpone
future admission; this module supplies no source/network permission.
"""

import json
import math
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from emailmonitor.administration.service import Administration
from emailmonitor.fetching.safety import FetchDenied, SafeURL
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.sources.policy import Operation


class SourceAdvice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    admitted: bool
    wait_seconds: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def state(self) -> "SourceAdvice":
        if (self.admitted and self.wait_seconds != 0) or (
            not self.admitted and self.wait_seconds < 0.05
        ):
            raise ValueError("Bounded server admission advice required")
        return self


@dataclass(frozen=True)
class SourceLease:
    identifier: UUID
    nonce: UUID
    organization: UUID

    def __post_init__(self) -> None:
        if any(
            type(value) is not UUID for value in (self.identifier, self.nonce, self.organization)
        ):
            raise FetchDenied("source_resource_scope_denied")


def resource_denied(error: DBAPIError) -> bool:
    args = getattr(error.orig, "args", ())
    detail = args[0] if args else None
    return isinstance(detail, dict) and (detail.get("C"), detail.get("M")) == (
        "EM013",
        "SOURCE_RESOURCE_SCOPE_DENIED",
    )


class SourceAdmission(Administration):
    def acquire(
        self,
        organization: UUID,
        version: int,
        operation: Operation,
        url: SafeURL,
        deadline: float,
        job: UUID | None = None,
    ) -> SourceLease:
        if (
            type(organization) is not UUID
            or (job is not None and type(job) is not UUID)
            or type(url) is not SafeURL
            or type(operation) is not Operation
            or type(deadline) not in (int, float)
            or type(version) is not int
            or version < 1
            or operation not in (Operation.HTML, Operation.XML, Operation.BROWSER, Operation.SEARCH)
            or url.host != "synthetic.publisher.example"
            or not math.isfinite(deadline)
            or not 0 < deadline - time.monotonic() <= 60
        ):
            raise FetchDenied("source_resource_scope_denied")
        lease = SourceLease(uuid4(), uuid4(), organization)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchDenied("source_admission_deadline")
                with self._tenant(organization, Capability.ACQUIRE_SOURCE) as connection:
                    value: object = connection.execute(
                        text("""SELECT emailmonitor.source_resource_claim(
:org,:id,:job,:version,:operation,:path,:nonce,:seconds)"""),
                        {
                            "org": organization,
                            "id": lease.identifier,
                            "job": job,
                            "version": version,
                            "operation": operation.value,
                            "path": url.path,
                            "nonce": lease.nonce,
                            "seconds": min(60, max(1, math.ceil(remaining))),
                        },
                    ).scalar_one()
                advice = SourceAdvice.model_validate_json(json.dumps(value))
                if time.monotonic() >= deadline:
                    raise FetchDenied("source_admission_deadline")
                if advice.admitted:
                    return lease
                time.sleep(min(advice.wait_seconds, max(0, deadline - time.monotonic())))
        except (AuthorizationDenied, DBAPIError) as error:
            if isinstance(error, AuthorizationDenied) or resource_denied(error):
                raise FetchDenied("source_resource_scope_denied") from error
            raise
        except FetchDenied:
            # Abandon a waiting/admitted ticket after the shared deadline. Current
            # session loss can prevent cleanup; its 120s metadata/60s lease expires.
            try:
                self.finish(lease)
            except (AuthorizationDenied, DBAPIError, FetchDenied):
                pass
            raise

    def finish(self, lease: SourceLease, status: int | None = None, retry_after: str = "") -> None:
        if (
            type(lease) is not SourceLease
            or (status is not None and (type(status) is not int or not 100 <= status <= 599))
            or type(retry_after) is not str
        ):
            raise FetchDenied("source_resource_scope_denied")
        outcome, delay = "network_failure" if status is None else "response", 0
        if status in (429, 503):
            outcome, delay = "provider_backoff", 5
            if retry_after:
                # Closed synthetic scope supports bounded delta-seconds only.
                # Unknown/date/oversized hints stop the shared source; no earlier
                # retry is invented or enabled by changing tenant entitlements.
                delay = (
                    max(5, int(retry_after))
                    if retry_after.isascii()
                    and retry_after.isdecimal()
                    and len(retry_after) <= 5
                    and int(retry_after) <= 86400
                    else -1
                )
        try:
            with self._tenant(lease.organization, Capability.READ_ORGANIZATION) as connection:
                connection.execute(
                    text(
                        "SELECT emailmonitor.source_resource_finish("
                        ":org,:id,:nonce,:outcome,:delay)"
                    ),
                    {
                        "org": lease.organization,
                        "id": lease.identifier,
                        "nonce": lease.nonce,
                        "outcome": outcome,
                        "delay": delay,
                    },
                )
        except (AuthorizationDenied, DBAPIError) as error:
            if isinstance(error, AuthorizationDenied) or resource_denied(error):
                if status is not None:
                    try:
                        # The network call has ended. Only failure cleanup may
                        # release its owned slot; refusal never becomes success.
                        self.finish(lease, None)
                    except (AuthorizationDenied, DBAPIError, FetchDenied):
                        error.add_note("Owned source cleanup refused; lease remains bounded")
                raise FetchDenied("source_resource_scope_denied") from error
            raise


class TenantHopResources:
    """Server composition bound to one current tenant/source-version and test session."""

    def __init__(self, admission: SourceAdmission, organization: UUID, version: int) -> None:
        self.admission, self.organization, self.version = admission, organization, version

    def acquire(self, url: SafeURL, operation: Operation, deadline: float) -> object:
        from emailmonitor.progress.binding import CURRENT

        bound = CURRENT.get()
        if bound is not None and bound.organization != self.organization:
            raise FetchDenied("source_resource_scope_denied")
        return self.admission.acquire(
            self.organization,
            self.version,
            operation,
            url,
            deadline,
            bound.job if bound is not None else None,
        )

    def finish(self, ticket: object, status: int | None, retry_after: str) -> None:
        if type(ticket) is not SourceLease or ticket.organization != self.organization:
            raise FetchDenied("source_resource_scope_denied")
        self.admission.finish(ticket, status, retry_after)

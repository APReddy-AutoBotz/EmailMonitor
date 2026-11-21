"""Europe PMC live connector (OA-027): owner-approved source, disabled by default.

Owner decision 2026-11-19 approved Europe PMC as the first live Open Access source
(document 19). This module is the connector half of that path. It contains **no
network code**: every request goes through an injected :class:`ProtectedTransport`,
which must be the shared protected egress layer (DNS pinning, TLS, no off-host
redirects, byte/time ceilings; documents 33, 50 and 90). No production transport
exists in this repository yet, so nothing here can reach the network on its own.

Rules enforced here, independent of the transport:

* Only URLs produced by the typed planners are requested, and each must pass
  :func:`classify_url` with the Europe PMC host set (exact search grammar).
  Response bodies are untrusted data: links inside them are never requested.
* A valid, unexpired approval record is required at construction and before
  every request; the approved limits (concurrency 1, at least 1 s between
  requests for Europe PMC) are applied by a per-source throttle.
* 429/503 put the source into back-off for at least the policy interval (or the
  provider's ``Retry-After``, capped); nothing is retried inside the connector.
  401/403 stop the source for the rest of the run: no retries, no other identity.
* Size, media type and SHA-256 are checked before parsing.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from emailmonitor.fetching.europepmc import (
    HOSTS,
    MAX_BYTES,
    EuropePmcBoundary,
    EuropePmcRequest,
    EuropePmcResponse,
)
from emailmonitor.fetching.safety import FetchDenied, SafeURL, classify_url
from emailmonitor.sources.europepmc_search import (
    MAX_PAYLOAD_BYTES,
    EuropePmcHit,
    EuropePmcSearchPage,
    EuropePmcSearchRequest,
    doi_lookup_request,
    parse_search_response,
)
from emailmonitor.sources.policy import Operation

MAX_BACKOFF_SECONDS = 3600.0
# Owner-delegated decision 2026-11-21 (document 19): Europe PMC publishes no
# per-second figure; third-party guides cite about 10 requests/s (unverified).
# One request at a time, at most one per second, is a tenth of that figure.
EUROPE_PMC_MIN_INTERVAL_SECONDS = 1.0


class LiveApiLimits(BaseModel):
    """Limits for an approved documented API. Separate from the fixture-policy
    ``Limits`` (5 s floor), which stays unchanged for every other source."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    max_concurrent_requests: int = Field(ge=1, le=1)
    min_request_interval_seconds: float = Field(
        ge=EUROPE_PMC_MIN_INTERVAL_SECONDS, le=86400, allow_inf_nan=False
    )
    max_articles_per_job: int = Field(ge=1, le=500)


class LiveSourceApproval(BaseModel):
    """In-memory form of the owner's approval for one live source.

    The durable, tenant-scoped policy record is the persistence slice's job; this
    record carries the same bounded fields so the connector cannot run without them.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    source: Literal["europe_pmc"]
    purpose: Literal["academic_contact_research"]
    permission_reference: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    valid_until: datetime
    limits: LiveApiLimits
    # Owner decision 2026-11-21: raw full text is never retained (0 hours); only
    # evidence excerpts and digests survive parsing.
    raw_retention_hours: Literal[0] = 0

    @field_validator("valid_until")
    @classmethod
    def aware_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Expiry must include a timezone")
        return value.astimezone(UTC)

    def require_valid(self, now: datetime) -> None:
        if not now < self.valid_until <= now + timedelta(days=365):
            raise FetchDenied("live_source_approval_invalid")


@dataclass(frozen=True)
class TransportReply:
    """What the protected transport hands back. Headers are pre-reduced to the
    one value the connector may act on; nothing else from the response is trusted."""

    status_code: int
    media_type: str
    body: bytes
    elapsed_ms: int
    retry_after_seconds: float | None = None


class ProtectedTransport(Protocol):
    """Port to the shared protected egress layer. Connectors never open sockets."""

    def get(self, url: SafeURL, operation: Operation, max_bytes: int) -> TransportReply: ...


class SourceThrottle:
    """Concurrency 1 and a minimum interval between request starts, per source.

    The floor can be raised per source, never lowered below the approved minimum.
    Process-local. The cross-worker, cross-tenant fair throttle is EM-013; until it
    exists a deployment must run one live worker per source.
    """

    def __init__(
        self,
        min_interval_seconds: float,
        *,
        floor_seconds: float = EUROPE_PMC_MIN_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if (
            not math.isfinite(min_interval_seconds)
            or floor_seconds < EUROPE_PMC_MIN_INTERVAL_SECONDS
            or min_interval_seconds < floor_seconds
        ):
            raise FetchDenied("throttle_interval_below_policy_floor")
        self._interval = min_interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_start: float | None = None

    @property
    def interval(self) -> float:
        return self._interval

    @contextmanager
    def slot(self) -> Iterator[None]:
        with self._lock:
            if self._last_start is not None:
                wait = self._last_start + self._interval - self._clock()
                if wait > 0:
                    self._sleep(wait)
            self._last_start = self._clock()
            yield


class EuropePmcLiveGateway:
    """Search and full-text gateway with the same interface as the fixture gateways."""

    def __init__(
        self,
        approval: LiveSourceApproval,
        transport: ProtectedTransport | None,
        *,
        throttle: SourceThrottle | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(approval) is not LiveSourceApproval:
            raise FetchDenied("live_source_approval_invalid")
        approval.require_valid(now())
        if transport is None:
            raise FetchDenied("live_transport_unavailable")
        self._approval = approval
        self._transport = transport
        self._throttle = throttle or SourceThrottle(
            approval.limits.min_request_interval_seconds, clock=clock
        )
        if self._throttle.interval < approval.limits.min_request_interval_seconds:
            raise FetchDenied("throttle_interval_below_policy_floor")
        self._now = now
        self._clock = clock
        self._stopped = False
        self._backoff_until: float | None = None
        self._boundary = EuropePmcBoundary()
        self.requests_made = 0

    # ---------------------------------------------------------------- transport

    def _get(self, url: str, operation: Operation, max_bytes: int) -> TransportReply:
        if self._stopped:
            raise FetchDenied("europe_pmc_source_stopped")
        if self._backoff_until is not None and self._clock() < self._backoff_until:
            raise FetchDenied("europe_pmc_backoff_active")
        self._approval.require_valid(self._now())
        safe = classify_url(url, HOSTS)
        with self._throttle.slot():
            self.requests_made += 1
            reply = self._transport.get(safe, operation, max_bytes)
        if type(reply) is not TransportReply:
            raise FetchDenied("transport_reply_invalid")
        if len(reply.body) > max_bytes:
            raise FetchDenied("europe_pmc_payload_too_large")
        if reply.status_code in (429, 503):
            self._backoff_until = self._clock() + self._backoff_seconds(reply.retry_after_seconds)
            raise FetchDenied("europe_pmc_rate_limited")
        if reply.status_code in (401, 403):
            self._stopped = True
            raise FetchDenied("europe_pmc_access_refused")
        return reply

    def _backoff_seconds(self, retry_after: float | None) -> float:
        floor = self._throttle.interval
        if retry_after is None or not math.isfinite(retry_after) or retry_after < floor:
            return floor
        return min(retry_after, MAX_BACKOFF_SECONDS)

    # ------------------------------------------------------------------ search

    def search(self, request: EuropePmcSearchRequest) -> EuropePmcSearchPage:
        reply = self._get(request.plan_url(), Operation.SEARCH, MAX_PAYLOAD_BYTES)
        if reply.status_code != 200:
            raise FetchDenied(f"europe_pmc_http_{reply.status_code}")
        if "json" not in reply.media_type.lower():
            raise FetchDenied("invalid_media_type_not_json")
        return parse_search_response(reply.body)

    def resolve_doi(self, doi: str) -> EuropePmcHit | None:
        page = self.search(doi_lookup_request(doi))
        return page.hits[0] if page.hits else None

    # --------------------------------------------------------------- full text

    def fetch(self, request: EuropePmcRequest) -> EuropePmcResponse:
        reply = self._get(request.url, Operation.XML, MAX_BYTES)
        if reply.status_code == 404:
            # Europe PMC answers 404 when it holds no open-access full text.
            raise FetchDenied("europe_pmc_full_text_not_found")
        response = EuropePmcResponse(
            request=request,
            status_code=reply.status_code,
            media_type=reply.media_type,
            body=reply.body,
            content_digest=hashlib.sha256(reply.body).hexdigest(),
            elapsed_ms=min(max(reply.elapsed_ms, 0), 300_000),
        )
        self._boundary.require_response(response)
        return response

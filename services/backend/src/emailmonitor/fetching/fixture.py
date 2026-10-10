"""Test-only bounded byte acquisition. There is no socket/DNS/network fallback."""

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urljoin
from uuid import UUID

from fastapi import HTTPException

from emailmonitor.config import Settings
from emailmonitor.fetching.safety import FetchDenied, IsolationUnavailable, SafeURL, classify_url
from emailmonitor.organizations.database import AuthorizationDenied, Database
from emailmonitor.organizations.roles import Capability
from emailmonitor.sources.access import current_policy, policy_decision
from emailmonitor.sources.policy import Evaluation, Operation

HOSTS = frozenset({"synthetic.publisher.example"})


@dataclass(frozen=True)
class ByteResponse:
    status: int
    chunks: Iterable[bytes]
    content_type: str = "text/html"
    location: str | None = None
    content_length: int | None = None
    content_encoding: str | None = None


@dataclass(frozen=True)
class FetchLimits:
    max_bytes: int = 5_242_880
    total_seconds: float = 60
    max_redirects: int = 5

    def __post_init__(self) -> None:
        if type(self.max_bytes) is not int or type(self.max_redirects) is not int:
            raise ValueError("Byte/redirect caps must be integer limits")
        if not (
            1 <= self.max_bytes <= 5_242_880
            and 0 < self.total_seconds <= 60
            and 0 <= self.max_redirects <= 5
        ):
            raise ValueError("Fixture fetch limits cannot relax platform ceilings")


class FixtureByteTransport:
    """Trusted test composition supplies synthetic responses; no HTTP client exists."""

    def __init__(self, settings: Settings, responses: dict[str, ByteResponse]) -> None:
        require_fixture(settings)
        self._responses = dict(responses)

    def request(self, url: SafeURL) -> ByteResponse:
        response = self._responses.get(url.normalized)
        if response is None:
            raise FetchDenied("fixture_route_unavailable")
        return response


def require_fixture(settings: Settings) -> None:
    if settings.environment != "test" or not settings.fixture_mode:
        raise IsolationUnavailable("fixture_transport_requires_explicit_test_mode")


class FixtureGateway:
    def __init__(
        self,
        settings: Settings,
        transport: FixtureByteTransport,
        authorize: Callable[[SafeURL, Operation], None],
        limits: FetchLimits | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        require_fixture(settings)
        if type(transport) is not FixtureByteTransport:
            raise FetchDenied("fixture_transport_type_denied")
        self._transport, self._authorize = transport, authorize
        self._limits, self._clock = limits or FetchLimits(), clock

    def fetch(self, url: str, operation: Operation = Operation.HTML) -> bytes:
        deadline = self._clock() + self._limits.total_seconds
        seen: set[str] = set()
        current = url
        for hop in range(self._limits.max_redirects + 1):
            if self._clock() >= deadline:
                raise FetchDenied("total_deadline_exceeded")
            validated = classify_url(current, HOSTS)
            if validated.normalized in seen:
                raise FetchDenied("redirect_loop_denied")
            seen.add(validated.normalized)
            self._authorize(validated, operation)
            if self._clock() >= deadline:
                raise FetchDenied("total_deadline_exceeded")
            response = self._transport.request(validated)
            if self._clock() >= deadline:
                raise FetchDenied("total_deadline_exceeded")
            if response.status in (301, 302, 303, 307, 308):
                if not response.location or hop == self._limits.max_redirects:
                    raise FetchDenied("redirect_limit_denied")
                current = urljoin(validated.normalized, response.location)
                continue
            if response.status != 200:
                # 401/403/429/challenges never trigger proxy, credential or retry fallback.
                raise FetchDenied("source_response_denied")
            if response.content_type.split(";", 1)[0].lower() != "text/html":
                raise FetchDenied("content_type_denied")
            if response.content_encoding not in (None, "identity"):
                raise FetchDenied("compressed_fixture_denied")
            if response.content_length is not None and (
                response.content_length < 0 or response.content_length > self._limits.max_bytes
            ):
                raise FetchDenied("body_limit_exceeded")
            body = bytearray()
            for chunk in response.chunks:
                if self._clock() >= deadline:
                    raise FetchDenied("total_deadline_exceeded")
                if len(body) + len(chunk) > self._limits.max_bytes:
                    raise FetchDenied("body_limit_exceeded")
                body.extend(chunk)
            # Consult current permission again before releasing acquired bytes.
            self._authorize(validated, operation)
            if self._clock() >= deadline:
                raise FetchDenied("total_deadline_exceeded")
            return bytes(body)
        raise FetchDenied("redirect_limit_denied")


class TenantFixtureAuthorization:
    def __init__(
        self, database: Database, token: str, organization: UUID, source: str, version: int
    ) -> None:
        self._database, self._token = database, token
        self._organization, self._source, self._version = organization, source, version

    def __call__(self, url: SafeURL, operation: Operation) -> None:
        try:
            with self._database.tenant(
                self._token, self._organization, Capability.ACQUIRE_SOURCE
            ) as (connection, _):
                row = current_policy(connection, self._organization, self._source)
                request = Evaluation(
                    expected_version=self._version,
                    operation=operation,
                    host=url.host,
                    path=url.path,
                    execution_mode="fixture",
                )
                if not policy_decision(row, request):
                    raise FetchDenied("source_policy_denied")
        except (AuthorizationDenied, HTTPException) as error:
            raise FetchDenied("source_policy_denied") from error


def live_fetch(url: str) -> bytes:
    raise IsolationUnavailable("live_connection_and_egress_enforcement_unimplemented")


def browser_request(url: str, resource_type: str) -> bytes:
    raise IsolationUnavailable("browser_network_isolation_unverified")

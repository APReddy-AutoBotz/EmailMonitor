"""Test-only protected transport: actual DNS snapshots, literal sockets and TLS.

Trusted composition supplies the closed resolver route, policy adapter and scope.
No connector receives these controls. Production/live entrypoints remain disabled.
"""

import ipaddress
import re
import secrets
import socket
import ssl
import struct
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from emailmonitor.config import Settings
from emailmonitor.fetching.credentials import (
    CredentialLease,
    CredentialResolver,
    UnavailableCredentials,
)
from emailmonitor.fetching.fixture import FetchLimits, require_fixture
from emailmonitor.fetching.plan import HopPlan, HopPlanner, PlanScope
from emailmonitor.fetching.resources import HopResources
from emailmonitor.fetching.safety import FetchDenied, SafeURL, public_addresses
from emailmonitor.fetching.sciencedirect import AcquiredResponse, ProviderBoundary, ProviderResponse
from emailmonitor.fetching.tls_fixture import TLSFixtureGateway
from emailmonitor.sources.policy import Operation


def question(host: str, kind: int) -> bytes:
    labels = host.split(".")
    if (
        kind not in (1, 28)
        or not host.isascii()
        or len(host) > 253
        or any(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None for label in labels
        )
    ):
        raise FetchDenied("dns_question_denied")
    return (
        b"".join(bytes([len(label)]) + label.encode("ascii") for label in labels)
        + b"\0"
        + struct.pack("!HH", kind, 1)
    )


def decode_snapshot(raw: bytes, identifier: int, expected: bytes) -> tuple[str, ...]:
    """Bounded authoritative A/AAAA only; aliases, extra records and truncation refuse.

    This closed acceptance resolver intentionally has no recursive/CNAME fallback.
    Empty authoritative answers are accepted per family; the combined set must be
    nonempty and every address public before any TCP connection can be made.
    """
    if not 12 <= len(raw) <= 512:
        raise FetchDenied("dns_response_denied")
    ident, flags, questions, count, authority, additional = struct.unpack("!HHHHHH", raw[:12])
    if (
        (ident, flags, questions, authority, additional) != (identifier, 0x8400, 1, 0, 0)
        or count > 32
        or raw[12 : 12 + len(expected)] != expected
    ):
        raise FetchDenied("dns_response_denied")
    kind = struct.unpack("!HH", expected[-4:])[0]
    name, offset = expected[:-4], 12 + len(expected)
    records: list[str] = []
    for _ in range(count):
        if raw[offset : offset + 2] == b"\xc0\x0c":
            offset += 2
        elif raw[offset : offset + len(name)] == name:
            offset += len(name)
        else:
            raise FetchDenied("dns_response_denied")
        if len(raw) - offset < 10:
            raise FetchDenied("dns_response_denied")
        rkind, cls, ttl, length = struct.unpack("!HHIH", raw[offset : offset + 10])
        offset += 10
        if (
            rkind != kind
            or cls != 1
            or ttl > 60
            or length != (4 if kind == 1 else 16)
            or len(raw) - offset < length
        ):
            raise FetchDenied("dns_response_denied")
        records.append(str(ipaddress.ip_address(raw[offset : offset + length])))
        offset += length
    if offset != len(raw) or len(set(records)) != len(records):
        raise FetchDenied("dns_response_denied")
    return tuple(records)


@dataclass(frozen=True)
class ResolverRoute:
    address: str
    port: int = 5353

    def __post_init__(self) -> None:
        if (
            public_addresses((self.address,)) != frozenset({self.address})
            or type(self.port) is not int
            or self.port != 5353
        ):
            raise FetchDenied("resolver_route_denied")


class SnapshotResolver:
    """Connected UDP to one trusted literal, no OS name service/cache/retry/proxy."""

    def __init__(self, settings: Settings, route: ResolverRoute) -> None:
        require_fixture(settings)
        if type(route) is not ResolverRoute:
            raise FetchDenied("resolver_route_denied")
        self._route = route

    def resolve(self, url: SafeURL, planner: HopPlanner) -> tuple[str, ...]:
        records: list[str] = []
        family = socket.AF_INET6 if ":" in self._route.address else socket.AF_INET
        for kind in (1, 28):
            expected = question(url.host, kind)
            identifier = secrets.randbits(16)
            payload = struct.pack("!HHHHHH", identifier, 0, 1, 0, 0, 0) + expected
            try:
                with socket.socket(family, socket.SOCK_DGRAM) as stream:
                    stream.settimeout(planner.remaining())
                    stream.connect((self._route.address, self._route.port))
                    if stream.getpeername()[:2] != (self._route.address, self._route.port):
                        raise FetchDenied("dns_peer_denied")
                    stream.send(payload)
                    stream.settimeout(planner.remaining())
                    raw = stream.recv(513)
                    planner.remaining()
                    records.extend(decode_snapshot(raw, identifier, expected))
            except OSError as error:
                raise FetchDenied("dns_connection_denied") from error
        planner.remaining()
        public_addresses(tuple(records))
        return tuple(records)


class ProtectedGateway:
    """One trusted boundary used by HTTP and browser byte mediation, test-only.

    No request headers/body/proxy/custom connector or user-supplied permission
    object is accepted. Resolution is repeated per redirect; exactly one selected
    literal is dialed without fallback. CA/hostname/SNI and actual peers are checked.
    """

    def __init__(
        self,
        settings: Settings,
        resolver: SnapshotResolver,
        ca_file: Path,
        scope: Callable[[Operation], PlanScope],
        authorize: Callable[[PlanScope, SafeURL], None],
        limits: FetchLimits | None = None,
        address_family: int = 4,
        *,
        resources: HopResources,
    ) -> None:
        require_fixture(settings)
        if type(resolver) is not SnapshotResolver:
            raise FetchDenied("resolver_type_denied")
        if type(address_family) is not int or address_family not in (4, 6):
            raise FetchDenied("address_family_denied")
        self._resources = resources
        self._family = address_family
        self._resolver, self._scope, self._authorize = resolver, scope, authorize
        self._limits = limits or FetchLimits()
        self.peer_receipts: list[tuple[str, int, str]] = []
        self._tls = ssl.create_default_context(cafile=str(ca_file))
        self._tls.minimum_version = ssl.TLSVersion.TLSv1_2

    @contextmanager
    def _connection(self, planner: HopPlanner, plan: HopPlan) -> Iterator[ssl.SSLSocket]:
        """The sole TCP/TLS path, shared by HTML and canonical provider requests."""
        if self._tls.verify_mode != ssl.CERT_REQUIRED or not self._tls.check_hostname:
            raise FetchDenied("tls_verification_required")
        family = socket.AF_INET6 if ":" in plan.selected_address else socket.AF_INET
        try:
            with socket.socket(family, socket.SOCK_STREAM) as raw:
                raw.settimeout(planner.before_connect(plan))
                raw.connect((plan.selected_address, 443))
                plan.validate_peer(raw.getpeername()[0])
                raw.settimeout(planner.remaining())
                with self._tls.wrap_socket(raw, server_hostname=plan.url.host) as stream:
                    plan.validate_peer(stream.getpeername()[0])
                    self.peer_receipts.append((stream.getpeername()[0], plan.port, plan.url.host))
                    planner.before_connect(plan)
                    yield stream
        except (OSError, UnicodeError):
            raise FetchDenied("protected_connection_denied") from None

    @staticmethod
    def _receive(stream: ssl.SSLSocket, check: Callable[[], float], maximum: int) -> bytes:
        stream.settimeout(check())
        chunk = stream.recv(maximum)
        check()
        return chunk

    def _response(
        self, stream: ssl.SSLSocket, check: Callable[[], float], maximum: int
    ) -> tuple[int, dict[str, str], Iterator[bytes]]:
        header = bytearray()
        while b"\r\n\r\n" not in header:
            if len(header) >= 8192:
                raise FetchDenied("headers_limit_exceeded")
            chunk = self._receive(stream, check, min(4096, 8192 - len(header)))
            if not chunk:
                raise FetchDenied("response_framing_denied")
            header.extend(chunk)
        raw, _, initial = bytes(header).partition(b"\r\n\r\n")
        status, headers = TLSFixtureGateway._headers(raw + b"\r\n\r\n")
        length = headers.get("content-length", "")
        if "transfer-encoding" in headers or not re.fullmatch(r"[0-9]{1,8}", length):
            raise FetchDenied("response_framing_denied")
        count = int(length)
        if len(initial) > count:
            raise FetchDenied("response_framing_denied")

        def chunks() -> Iterator[bytes]:
            if count > maximum:
                raise FetchDenied("body_limit_exceeded")
            consumed = len(initial)
            if initial:
                check()
                yield initial
            while consumed < count:
                chunk = self._receive(stream, check, min(65536, count - consumed))
                if not chunk:
                    raise FetchDenied("response_framing_denied")
                consumed += len(chunk)
                yield chunk
            # Each request asks Connection: close. Reject surplus/truncated framing,
            # and bound a peer that refuses to close by the same absolute deadline.
            if self._receive(stream, check, 1):
                raise FetchDenied("response_framing_denied")

        return status, headers, chunks()

    def _request(self, planner: HopPlanner, plan: HopPlan) -> tuple[int, dict[str, str], bytes]:
        with self._connection(planner, plan) as stream:
            stream.settimeout(planner.remaining())
            stream.sendall(
                (
                    f"GET {plan.url.path} HTTP/1.1\r\nHost: {plan.url.host}\r\n"
                    "Accept: text/html\r\nConnection: close\r\n\r\n"
                ).encode("ascii")
            )
            status, headers, chunks = self._response(
                stream, planner.remaining, self._limits.max_bytes
            )
            return status, headers, b"".join(chunks)

    def acquire_provider(
        self, boundary: ProviderBoundary, credentials: CredentialResolver | None = None
    ) -> AcquiredResponse:
        """Closed PUT-search/GET-XML dispatch, still test-only and unregistered.

        The boundary's current() is trusted composition, never HTTP/request authority.
        No caller method, URL, headers, proxy, retries or redirect handling is exposed.
        A real source admission adapter and secret-store resolver remain unavailable.
        """
        if type(boundary) is not ProviderBoundary:
            raise FetchDenied("provider_boundary_denied")
        boundary.check_current()
        planner = boundary.planner
        if planner.remaining() > self._limits.total_seconds:
            raise FetchDenied("plan_deadline_denied")
        request, binding = boundary.request, boundary.binding
        canonical = request.plan()
        url = planner.authorize_url(request.url)
        ticket = self._resources.acquire(url, request.operation, binding.deadline)
        status: int | None = None
        headers: dict[str, str] = {}
        try:
            boundary.check_current()
            # Default resolver refuses before DNS or TCP. Scoped handles are never
            # returned, serialized or retained with the acquired response.
            with (credentials or UnavailableCredentials()).open(
                binding.credential, request.fingerprint
            ) as credential:
                if type(credential) is not CredentialLease:
                    raise FetchDenied("provider_credential_scope_denied")
                authentication = credential.header(binding.credential, request.fingerprint)
                boundary.check_current()
                records = self._resolver.resolve(url, planner)
                plan = planner.snapshot(url, records, self._select(records))
                with self._connection(planner, plan) as stream:
                    boundary.check_current()
                    # Revalidate scoped material after resolver/TLS latency.
                    authentication = credential.header(binding.credential, request.fingerprint)
                    packet = (
                        f"{canonical.method} {canonical.path} HTTP/1.1\r\n"
                        f"Host: {url.host}\r\nAccept: {canonical.media_type}\r\n"
                        "Accept-Encoding: identity\r\nConnection: close\r\n"
                    ).encode("ascii") + authentication
                    if request.search is not None:
                        packet += (
                            "Content-Type: application/json\r\n"
                            f"Content-Length: {len(canonical.body)}\r\n"
                        ).encode("ascii")
                    stream.settimeout(planner.before_connect(plan))
                    stream.sendall(packet + b"\r\n" + canonical.body)
                    status, headers, chunks = self._response(
                        stream,
                        lambda: planner.before_connect(plan),
                        min(request.max_bytes, self._limits.max_bytes),
                    )
                    acquired = boundary.read_response(
                        ProviderResponse(
                            request.url,
                            status,
                            headers.get("content-type", ""),
                            chunks,
                            binding,
                            int(headers["content-length"]),
                            headers.get("content-encoding"),
                        )
                    )
        except BaseException as error:
            try:
                self._resources.finish(ticket, status, headers.get("retry-after", ""))
            except Exception:
                error.add_note("Protected resource release failed; server lease remains bounded")
            if isinstance(error, Exception):
                raise FetchDenied("provider_dispatch_denied") from None
            raise
        else:
            try:
                self._resources.finish(ticket, status, headers.get("retry-after", ""))
                boundary.require_response(acquired)
            except Exception:
                raise FetchDenied("provider_release_denied") from None
        return acquired

    def _select(self, records: tuple[str, ...]) -> str:
        addresses = public_addresses(records)
        selected = sorted(
            address
            for address in addresses
            if ipaddress.ip_address(address).version == self._family
        )
        if not selected:
            raise FetchDenied("selected_family_unavailable")
        return selected[0]

    def fetch(self, value: str, operation: Operation = Operation.HTML) -> bytes:
        scope = self._scope(operation)
        if scope.operation != operation or scope.max_redirects > self._limits.max_redirects:
            raise FetchDenied("plan_scope_mismatch")
        planner = HopPlanner(scope, self._authorize)
        if planner.remaining() > self._limits.total_seconds:
            raise FetchDenied("plan_deadline_denied")
        url = planner.authorize_url(value)
        previous: HopPlan | None = None
        location = ""
        while True:
            ticket = self._resources.acquire(url, operation, scope.deadline)
            status: int | None = None
            headers: dict[str, str] = {}
            try:
                planner.remaining()
                records = self._resolver.resolve(url, planner)
                plan = (
                    planner.snapshot(url, records, self._select(records))
                    if previous is None
                    else planner.redirected_snapshot(
                        previous, location, records, self._select(records)
                    )
                )
                status, headers, body = self._request(planner, plan)
            except BaseException as error:
                try:
                    self._resources.finish(ticket, status, headers.get("retry-after", ""))
                except Exception:
                    error.add_note(
                        "Protected resource release failed; server lease remains bounded"
                    )
                raise
            else:
                self._resources.finish(ticket, status, headers.get("retry-after", ""))
            if status in (301, 302, 303, 307, 308):
                location = headers.get("location", "")
                url = planner.redirect(plan, location)
                previous = plan
                continue
            if status != 200:
                raise FetchDenied("source_response_denied")
            if headers.get("content-type", "").split(";", 1)[0].lower() != "text/html":
                raise FetchDenied("content_type_denied")
            if headers.get("content-encoding", "identity") != "identity":
                raise FetchDenied("compressed_response_denied")
            planner.before_release(plan)
            return body

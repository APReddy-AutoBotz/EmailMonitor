"""Network-free dispatch regressions; real HTTPS/parser proof is mandatory controlled CI."""

import json
import socket
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from emailmonitor.config import Settings
from emailmonitor.fetching.credentials import CredentialLease
from emailmonitor.fetching.fixture import FetchLimits
from emailmonitor.fetching.plan import HopPlan, HopPlanner
from emailmonitor.fetching.protected import ProtectedGateway, ResolverRoute, SnapshotResolver
from emailmonitor.fetching.safety import FetchDenied, SafeURL
from emailmonitor.fetching.sciencedirect import (
    CredentialReference,
    ProviderBinding,
    ProviderBoundary,
    ProviderRequest,
)
from emailmonitor.sources.policy import Operation
from emailmonitor.sources.sciencedirect import SearchRequest, normalize_identifier
from pydantic import ValidationError
from tls_fixture_server import certificate

SETTINGS = Settings(environment="test", fixture_mode=True)
BODY = b'{"resultsFound":0,"results":[]}'


class Resources:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.finish_hook: Callable[[], None] = lambda: None
        self.acquire_hook: Callable[[], None] = lambda: None

    def acquire(self, url: SafeURL, operation: Operation, deadline: float) -> object:
        self.events.append("acquire")
        self.acquire_hook()
        return self

    def finish(self, ticket: object, status: int | None, retry_after: str) -> None:
        assert ticket is self
        self.events.append((status, retry_after))
        self.finish_hook()


class Credentials:
    def __init__(self) -> None:
        self.opened = 0
        self.closed = 0
        self.hook: Callable[[], None] = lambda: None
        self.change: dict[str, Any] = {}

    @contextmanager
    def open(self, reference: CredentialReference, fingerprint: str) -> Iterator[CredentialLease]:
        self.opened += 1
        try:
            self.hook()
            yield CredentialLease(
                **{
                    "reference": reference,
                    "request_fingerprint": fingerprint,
                    "api_key": b"fake-fixture-value",
                    **self.change,
                }
            )
        finally:
            self.closed += 1


class Stream:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent: list[bytes] = []
        self.closed = False
        self.timeouts: list[float] = []
        self.receive_hook: Callable[[], None] = lambda: None
        self.fragment = 4096

    def settimeout(self, seconds: float) -> None:
        self.timeouts.append(seconds)

    def sendall(self, packet: bytes) -> None:
        self.sent.append(packet)

    def recv(self, limit: int) -> bytes:
        self.receive_hook()
        n = min(limit, self.fragment)
        result, self.response = self.response[:n], self.response[n:]
        return result


def wire(
    body: bytes = BODY, *, status: int = 200, extra: bytes = b"", length: int | None = None
) -> bytes:
    return (
        (
            f"HTTP/1.1 {status} Synthetic\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body) if length is None else length}\r\n"
        ).encode()
        + extra
        + b"\r\n"
        + body
    )


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "socket", lambda *a, **kw: pytest.fail("Network forbidden"))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: pytest.fail("DNS forbidden"))


def assembly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[
    ProtectedGateway,
    ProviderBoundary,
    Resources,
    Credentials,
    Stream,
    list[ProviderBinding],
    list[str],
]:
    request = ProviderRequest(search=SearchRequest(query='  "Synthetic" AND subject  ', show=10))
    binding = ProviderBinding(
        organization=UUID(int=1),
        job=UUID(int=2),
        item=UUID(int=3),
        lease=UUID(int=4),
        generation=1,
        deletion_generation=1,
        policy_version=1,
        policy_revision=1,
        discovery_revision=1,
        request_fingerprint=request.fingerprint,
        credential=CredentialReference(organization=UUID(int=1), reference=UUID(int=5), revision=1),
        deadline=time.monotonic() + 4,
    )
    current = [binding]
    boundary = ProviderBoundary(request, binding, lambda: current[0])
    resources, credentials, stream = Resources(), Credentials(), Stream(wire())
    cert, _ = certificate(tmp_path)
    target = ProtectedGateway(
        SETTINGS,
        SnapshotResolver(SETTINGS, ResolverRoute("8.8.8.3")),
        cert,
        lambda op: boundary.planner.scope,
        lambda scope, url: boundary.check_current(),
        FetchLimits(total_seconds=5, max_redirects=0),
        resources=resources,
    )
    dns: list[str] = []

    def resolve(self: SnapshotResolver, url: SafeURL, planner: HopPlanner) -> tuple[str, ...]:
        dns.append(url.host)
        return ("8.8.8.3",)

    @contextmanager
    def connection(self: ProtectedGateway, planner: HopPlanner, plan: HopPlan) -> Iterator[Stream]:
        planner.before_connect(plan)
        try:
            yield stream
        finally:
            stream.closed = True

    monkeypatch.setattr(SnapshotResolver, "resolve", resolve)
    monkeypatch.setattr(ProtectedGateway, "_connection", connection)
    return target, boundary, resources, credentials, stream, current, dns


def test_exact_put_packet_and_bound_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, boundary, resources, credentials, stream, _, dns = assembly(tmp_path, monkeypatch)
    acquired = target.acquire_provider(boundary, credentials)
    body = boundary.request.plan().body
    assert stream.sent == [
        b"PUT /content/search/sciencedirect HTTP/1.1\r\nHost: api.elsevier.com\r\n"
        b"Accept: application/json\r\nAccept-Encoding: identity\r\nConnection: close\r\n"
        b"X-ELS-APIKey: fake-fixture-value\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode()
        + body
    ]
    assert json.loads(body)["qs"] == '  "Synthetic" AND subject  '
    assert acquired.binding is boundary.binding and acquired.body == BODY
    assert dns == ["api.elsevier.com"] and stream.closed
    assert credentials.opened == credentials.closed == 1
    assert resources.events == ["acquire", (200, "")]
    assert stream.timeouts and all(0 < seconds <= 5 for seconds in stream.timeouts)
    assert b"fake-fixture-value" not in repr(acquired).encode()


def test_get_xml_has_no_body_or_content_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, initial, _, credentials, stream, current, _ = assembly(tmp_path, monkeypatch)
    request = ProviderRequest(article=normalize_identifier("10.9999/synthetic.1"))
    current[0] = initial.binding.model_copy(update={"request_fingerprint": request.fingerprint})
    boundary = ProviderBoundary(request, current[0], lambda: current[0])
    stream.response = wire(b"<xml/>").replace(b"application/json", b"text/xml")
    assert target.acquire_provider(boundary, credentials).body == b"<xml/>"
    assert stream.sent[0].startswith(b"GET /content/article/doi/10.9999/synthetic.1 HTTP/1.1\r\n")
    assert b"Content-Type:" not in stream.sent[0] and b"Content-Length:" not in stream.sent[0]
    assert stream.sent[0].endswith(b"\r\n\r\n")


@pytest.mark.parametrize("stage", ["admission", "credential", "read", "finish"])
def test_revocation_rechecked_and_owned_resources_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    target, boundary, resources, credentials, stream, current, dns = assembly(tmp_path, monkeypatch)

    def revoke() -> None:
        current[0] = current[0].model_copy(update={"deletion_generation": 2})

    if stage == "admission":
        resources.acquire_hook = revoke
    elif stage == "credential":
        credentials.hook = revoke
    elif stage == "read":
        stream.receive_hook = revoke
    else:
        resources.finish_hook = revoke
    with pytest.raises(FetchDenied):
        target.acquire_provider(boundary, credentials)
    assert len(resources.events) == 2
    assert credentials.closed == credentials.opened
    if stage in ("admission", "credential"):
        assert not dns and not stream.sent
    else:
        assert stream.closed


@pytest.mark.parametrize(
    "change",
    [
        {"api_key": b"bad\r\nHeader: value"},
        {"api_key": b""},
        {"api_key": b"x" * 257},
        {"api_key": "string"},
        {"request_fingerprint": "0" * 64},
        {
            "reference": CredentialReference(
                organization=UUID(int=6), reference=UUID(int=5), revision=1
            )
        },
        {
            "reference": CredentialReference(
                organization=UUID(int=1), reference=UUID(int=6), revision=1
            )
        },
        {
            "reference": CredentialReference(
                organization=UUID(int=1), reference=UUID(int=5), revision=2
            )
        },
    ],
)
def test_credential_scope_and_header_injection_refuse_before_dns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any]
) -> None:
    target, boundary, resources, credentials, stream, _, dns = assembly(tmp_path, monkeypatch)
    credentials.change = change
    with pytest.raises(FetchDenied):
        target.acquire_provider(boundary, credentials)
    assert not dns and not stream.sent and credentials.closed == 1
    assert resources.events == ["acquire", (None, "")]


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308, 401, 403, 429, 500])
def test_status_refused_without_consuming_body_or_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    target, boundary, resources, credentials, stream, _, dns = assembly(tmp_path, monkeypatch)
    stream.response = wire(status=status, extra=b"Retry-After: 3\r\n")
    stream.fragment = len(stream.response) - len(BODY)
    with pytest.raises(FetchDenied):
        target.acquire_provider(boundary, credentials)
    assert stream.response == BODY and stream.closed
    assert resources.events == ["acquire", (status, "3")]
    assert len(stream.sent) == len(dns) == credentials.closed == 1


@pytest.mark.parametrize(
    "response",
    [
        wire(extra=b"Content-Length: 0\r\n"),
        wire(extra=b"Transfer-Encoding: chunked\r\n"),
        wire(length=len(BODY) + 1),
        wire(length=len(BODY) - 1),
        wire() + b"extra",
        wire(length=1_048_577),
        wire(extra=b"Content-Encoding: gzip\r\n"),
        wire().replace(b"application/json", b"text/html"),
        wire().replace(b"application/json", b"application/json; charset=latin1"),
        b"HTTP/1.1 200 OK\r\n" + b"x" * 8192,
    ],
)
def test_hostile_http_framing_media_and_size_close_without_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: bytes
) -> None:
    target, boundary, resources, credentials, stream, _, dns = assembly(tmp_path, monkeypatch)
    stream.response = response
    with pytest.raises(FetchDenied):
        target.acquire_provider(boundary, credentials)
    assert stream.closed and credentials.closed == 1 and len(resources.events) == 2
    assert len(dns) == len(stream.sent) == 1


@pytest.mark.parametrize("stage", ["credential", "read", "finish"])
def test_secret_bearing_exceptions_are_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    target, boundary, resources, credentials, stream, _, _ = assembly(tmp_path, monkeypatch)

    def fail() -> None:
        raise RuntimeError("sentinel-secret-must-not-escape")

    if stage == "credential":
        credentials.hook = fail
    elif stage == "read":
        stream.receive_hook = fail
    else:
        resources.finish_hook = fail
    with pytest.raises(FetchDenied) as caught:
        target.acquire_provider(boundary, credentials)
    assert "sentinel-secret" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert credentials.closed == 1 and len(resources.events) == 2


def test_cancel_closes_and_releases_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target, boundary, resources, credentials, stream, _, _ = assembly(tmp_path, monkeypatch)
    cancelled = KeyboardInterrupt("cancelled")

    def fail() -> None:
        raise cancelled

    stream.receive_hook = fail
    with pytest.raises(KeyboardInterrupt) as caught:
        target.acquire_provider(boundary, credentials)
    assert caught.value is cancelled and stream.closed and credentials.closed == 1
    assert len(resources.events) == 2


def test_missing_credentials_refuses_before_dns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, boundary, resources, _, stream, _, dns = assembly(tmp_path, monkeypatch)
    with pytest.raises(FetchDenied):
        target.acquire_provider(boundary)
    assert not dns and not stream.sent and resources.events == ["acquire", (None, "")]


def test_forged_request_copy_refuses_before_credential_or_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, boundary, resources, credentials, stream, _, dns = assembly(tmp_path, monkeypatch)
    boundary.request = boundary.request.model_copy(
        update={"search": SearchRequest.model_construct(query="x\r\ny")}
    )
    with pytest.raises((FetchDenied, ValidationError)):
        target.acquire_provider(boundary, credentials)
    assert resources.events == [] and credentials.opened == 0 and not dns and not stream.sent


def test_legacy_fragmented_reads_preserve_callback_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, boundary, _, _, stream, _, _ = assembly(tmp_path, monkeypatch)
    stream.response = wire().replace(b"application/json", b"text/html")
    stream.fragment = 1
    checks: list[str] = []
    planner = HopPlanner(boundary.planner.scope, lambda scope, url: checks.append("authority"))
    url = planner.authorize_url(boundary.request.url)
    plan = planner.snapshot(url, ("8.8.8.3",))
    checks.clear()
    status, headers, body = target._request(planner, plan)
    assert status == 200 and body == BODY
    # The fake connection performs one check; per-byte checks remain deadline-only
    # for legacy HTML. Provider reads separately enforce current scope each time.
    assert checks == ["authority"]
    assert len(stream.timeouts) > 100


def test_receipt_validation_preserves_closed_legacy_and_provider_headers() -> None:
    from test_transport_acceptance import validate_receipt

    legacy: dict[str, Any] = {
        "headers": {
            "Host": "synthetic.publisher.example",
            "Accept": "text/html",
            "Connection": "close",
        }
    }
    validate_receipt(legacy)
    provider: dict[str, Any] = {
        "method": "PUT",
        "credential_valid": True,
        "headers": {
            "Host": "api.elsevier.com",
            "Accept": "application/json",
            "Connection": "close",
            "Accept-Encoding": "identity",
            "X-ELS-APIKey": "[synthetic-redacted]",
            "Content-Type": "application/json",
            "Content-Length": "30",
        },
    }
    validate_receipt(provider)
    provider["headers"]["X-ELS-APIKey"] = "must-not-appear"
    with pytest.raises(AssertionError):
        validate_receipt(provider)
    legacy["headers"]["X-ELS-APIKey"] = "must-not-appear"
    with pytest.raises(AssertionError):
        validate_receipt(legacy)

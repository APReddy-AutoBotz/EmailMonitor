"""Real disposable loopback TLS; no public DNS, source or production grants."""

from pathlib import Path

import pytest
from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import FetchLimits
from emailmonitor.fetching.safety import FetchDenied, IsolationUnavailable
from emailmonitor.fetching.tls_fixture import SyntheticEndpoint, TLSFixtureGateway
from tls_fixture_server import Response, certificate, server

HOST = "synthetic.publisher.example"
URL = f"https://{HOST}/article-a.html"
SETTINGS = Settings(environment="test", fixture_mode=True)


def test_actual_verified_tls_pinned_connection_and_redirect_reauthorization(tmp_path: Path) -> None:
    paths: list[str] = []
    with server(
        tmp_path,
        {
            "/article-a.html": Response(302, b"", "/article-b.html"),
            "/article-b.html": Response(),
        },
    ) as (endpoint, calls):
        gateway = TLSFixtureGateway(SETTINGS, endpoint, lambda url, op: paths.append(url.path))
        assert gateway.fetch(URL) == b"<p>synthetic observation</p>"
        assert paths == ["/article-a.html", "/article-b.html", "/article-b.html"]
        assert len(calls) == 2
        assert all(set(c) == {"Host", "Accept", "Connection"} for c in calls)
        assert all(c["Host"] == HOST for c in calls)


def test_wrong_hostname_and_untrusted_ca_fail_actual_tls(tmp_path: Path) -> None:
    with server(tmp_path, {"/article-a.html": Response()}, "wrong.fixture.example") as (
        endpoint,
        calls,
    ):
        with pytest.raises(FetchDenied, match="connection"):
            TLSFixtureGateway(SETTINGS, endpoint, lambda url, op: None).fetch(URL)
        assert calls == []
    other = tmp_path / "other"
    other.mkdir()
    ca, _ = certificate(other)
    with server(tmp_path, {"/article-a.html": Response()}) as (endpoint, calls):
        untrusted = SyntheticEndpoint(endpoint.address, endpoint.port, ca, endpoint.paths)
        with pytest.raises(FetchDenied, match="connection"):
            TLSFixtureGateway(SETTINGS, untrusted, lambda url, op: None).fetch(URL)
        assert calls == []


@pytest.mark.parametrize(
    "response,reason",
    [
        (Response(403), "source_response"),
        (Response(429), "source_response"),
        (Response(302, b"", "https://127.0.0.1/secret"), "literal_address"),
        (Response(302, b"", "https://evil.example/secret"), "host_denied"),
        (Response(302, b"", URL), "redirect_loop"),
        (Response(length=99), "body_limit"),
        (Response(content_type="application/pdf"), "content_type"),
        (Response(encoding="gzip"), "compressed"),
        (Response(delay=0.2), "connection"),
    ],
)
def test_actual_response_denial_has_no_retry(
    tmp_path: Path, response: Response, reason: str
) -> None:
    with server(tmp_path, {"/article-a.html": response}) as (endpoint, calls):
        # Response-shape cases must reach their distinct denial, not race TLS
        # scheduling. Keep the deliberate slow-response deadline case strict.
        limits = FetchLimits(max_bytes=64, total_seconds=0.1 if response.delay else 1)
        with pytest.raises(FetchDenied, match=reason):
            TLSFixtureGateway(SETTINGS, endpoint, lambda url, op: None, limits).fetch(URL)
        assert len(calls) == 1


def test_actual_body_discarded_on_current_permission_revocation(tmp_path: Path) -> None:
    count = 0

    def authorize(url: object, operation: object) -> None:
        nonlocal count
        count += 1
        if count == 2:
            raise FetchDenied("source_policy_denied")

    with server(tmp_path, {"/article-a.html": Response()}) as (endpoint, calls):
        with pytest.raises(FetchDenied, match="policy"):
            TLSFixtureGateway(SETTINGS, endpoint, authorize).fetch(URL)
        assert count == 2 and len(calls) == 1


@pytest.mark.parametrize(
    "raw",
    [
        b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\ncontent-length: 2\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nBad Header: x\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nX: \x01\r\n\r\n",
        b"HTTP/1.1 invalid\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nX: \xff\r\n\r\n",
    ],
)
def test_ambiguous_header_framing_denied(raw: bytes) -> None:
    with pytest.raises(FetchDenied):
        TLSFixtureGateway._headers(raw)


def test_fixture_endpoint_and_gateway_cannot_activate_in_production(tmp_path: Path) -> None:
    ca, _ = certificate(tmp_path)
    for address in ("0.0.0.0", "127.0.0.2", "::1", "8.8.8.8", "example.com"):
        with pytest.raises(ValueError):
            SyntheticEndpoint(address, 443, ca, frozenset({"/article-a.html"}))
    endpoint = SyntheticEndpoint("127.0.0.1", 443, ca, frozenset({"/article-a.html"}))
    for settings in (Settings(), Settings(environment="test")):
        with pytest.raises(IsolationUnavailable):
            TLSFixtureGateway(settings, endpoint, lambda url, op: None)

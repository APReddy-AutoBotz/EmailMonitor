"""Real disposable loopback TLS; no public DNS, source or production grants."""

import ssl
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import FetchLimits
from emailmonitor.fetching.safety import FetchDenied, IsolationUnavailable
from emailmonitor.fetching.tls_fixture import SyntheticEndpoint, TLSFixtureGateway

HOST = "synthetic.publisher.example"
URL = f"https://{HOST}/article-a.html"
SETTINGS = Settings(environment="test", fixture_mode=True)


def certificate(directory: Path, hostname: str = HOST) -> tuple[Path, Path]:
    # Ephemeral test-only key/certificate, never an external account or saved grant.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = directory / "fixture-cert.pem", directory / "fixture-key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_file.chmod(0o600)
    return cert_file, key_file


@dataclass(frozen=True)
class Response:
    status: int = 200
    body: bytes = b"<p>synthetic observation</p>"
    location: str | None = None
    length: int | None = None
    content_type: str = "text/html"
    encoding: str | None = None
    delay: float = 0


@contextmanager
def server(
    tmp_path: Path, responses: dict[str, Response], hostname: str = HOST
) -> Iterator[tuple[SyntheticEndpoint, list[dict[str, str]]]]:
    cert, key = certificate(tmp_path, hostname)
    calls: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            calls.append(dict(self.headers.items()))
            response = responses[self.path]
            time.sleep(response.delay)
            try:
                self.send_response(response.status)
                self.send_header("Content-Type", response.content_type)
                self.send_header(
                    "Content-Length",
                    str(response.length if response.length is not None else len(response.body)),
                )
                if response.location is not None:
                    self.send_header("Location", response.location)
                if response.encoding is not None:
                    self.send_header("Content-Encoding", response.encoding)
                self.end_headers()
                self.wfile.write(response.body)
            except OSError:
                pass  # A denied/expired test connection is deliberately closed.

        def log_message(self, format: str, *args: object) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = SyntheticEndpoint("127.0.0.1", httpd.server_port, cert, frozenset(responses))
        yield endpoint, calls
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


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
        limits = FetchLimits(max_bytes=64, total_seconds=0.1)
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

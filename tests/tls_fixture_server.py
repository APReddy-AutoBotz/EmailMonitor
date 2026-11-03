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

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from emailmonitor.fetching.tls_fixture import SyntheticEndpoint

HOST = "synthetic.publisher.example"


def certificate(
    directory: Path, hostname: str = HOST, *, extra_names: tuple[str, ...] = ()
) -> tuple[Path, Path]:
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
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(name) for name in (hostname, *extra_names)]),
            critical=False,
        )
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

"""Reference API startup/identity boundaries; all certificates are disposable."""

import ipaddress
import ssl
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from emailmonitor.identity.oidc import AuthenticationDenied
from emailmonitor.runtime.api_entrypoint import ReferenceExchange, ReferenceIdentity, loopback_https


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://127.0.0.1:444/token",
        "https://localhost:444/token",
        "https://[::1]:444/token",
        "https://example.com:443/token",
        "https://user@127.0.0.1:444/token",
        "https://127.0.0.1:444/token?secret=1",
        "https://127.0.0.1:444/token#fragment",
        "https://127.0.0.1/token",
        "https://127.0.0.1:0/token",
    ],
)
def test_reference_identity_refuses_unreviewed_endpoints(endpoint: str) -> None:
    with pytest.raises(ValueError):
        loopback_https(endpoint)


def certificate(directory: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "authored-reference")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    public, private = directory / "reference.pem", directory / "reference-key.pem"
    public.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private.chmod(0o600)
    return public, private


@contextmanager
def issuer(directory: Path, mode: str) -> Iterator[ReferenceIdentity]:
    public, private = certificate(directory)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            try:
                if mode == "headers":
                    self.connection.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                    for _ in range(50):
                        self.connection.sendall(b"x")
                        time.sleep(0.1)
                    return
                self.send_response(302 if mode == "redirect" else 200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Location", "https://example.com/token")
                if mode == "body":
                    self.send_header("Content-Length", "100")
                self.end_headers()
                if mode == "body":
                    for _ in range(50):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        time.sleep(0.1)
                elif mode == "oversized":
                    self.wfile.write(b"x" * 65_537)
                else:
                    self.wfile.write(b'{"id_token":"authored-token"}')
            except OSError:
                pass

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(public, private)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"https://127.0.0.1:{server.server_port}"
    try:
        yield ReferenceIdentity(
            issuer=origin,
            client_id="authored-client",
            authorization_endpoint=origin + "/authorize",
            token_endpoint=origin + "/token",
            redirect_uri=origin + "/auth/complete",
            verification_keys={
                "reference": x509.load_pem_x509_certificate(public.read_bytes())
                .public_key()
                .public_bytes(
                    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
                )
                .decode()
            },
            certificate_authority=public,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_reference_exchange_verifies_tls_and_ignores_proxy_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "https://untrusted.example:9999")
    with issuer(tmp_path, "success") as identity:
        assert (
            ReferenceExchange(identity).exchange("code", "verifier", identity.redirect_uri)
            == "authored-token"
        )


@pytest.mark.parametrize("mode", ["redirect", "oversized", "headers", "body"])
def test_reference_exchange_refuses_redirect_size_and_slow_drip(tmp_path: Path, mode: str) -> None:
    with issuer(tmp_path, mode) as identity:
        start = time.monotonic()
        with pytest.raises(AuthenticationDenied):
            ReferenceExchange(identity).exchange(
                "secret-sentinel", "verifier", identity.redirect_uri
            )
        assert time.monotonic() - start < 4.5

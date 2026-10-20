"""Ephemeral authored OIDC issuer: one-use codes, nonce, S256 and pinned RSA/TLS."""

import base64
import hashlib
import json
import secrets
import ssl
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from test_service_api_entrypoint import certificate


@dataclass
class SyntheticIssuer:
    origin: str
    public_key: str
    ca: Path
    key: Path
    authorizations: int = 0
    exchanges: int = 0
    refusals: int = 0
    codes: dict[str, tuple[str, str]] = field(default_factory=dict, repr=False)


@contextmanager
def synthetic_issuer(directory: Path, callback: str, subject: str) -> Iterator[SyntheticIssuer]:
    ca, tls_key = certificate(directory)
    signing = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = signing.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = signing.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status: int, body: bytes, location: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query, strict_parsing=True)
            expected = {
                "response_type",
                "client_id",
                "redirect_uri",
                "scope",
                "state",
                "nonce",
                "code_challenge",
                "code_challenge_method",
            }
            if (
                parsed.path != "/authorize"
                or set(query) != expected
                or any(len(values) != 1 for values in query.values())
                or query["client_id"] != ["installed-operator-test"]
                or query["response_type"] != ["code"]
                or query["redirect_uri"] != [callback]
                or query["scope"] != ["openid"]
                or query["code_challenge_method"] != ["S256"]
                or len(query["code_challenge"][0]) != 43
                or len(self.path) > 4096
            ):
                state.refusals += 1
                self.reply(400, b"{}")
                return
            now = int(time.time())
            token = jwt.encode(
                {
                    "iss": state.origin,
                    "aud": "installed-operator-test",
                    "sub": subject,
                    "exp": now + 120,
                    "iat": now,
                    "nonce": query["nonce"][0],
                },
                private,
                algorithm="RS256",
                headers={"kid": "ephemeral"},
            )
            code = secrets.token_urlsafe(24)
            with lock:
                if len(state.codes) >= 4:
                    raise RuntimeError("Synthetic authorization budget exceeded")
                state.codes[code] = (token, query["code_challenge"][0])
                state.authorizations += 1
            self.reply(
                303, b"{}", callback + "?" + urlencode({"state": query["state"][0], "code": code})
            )

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if self.path != "/token" or not 0 < length <= 16_384:
                self.reply(400, b"{}")
                return
            query = parse_qs(self.rfile.read(length).decode(), strict_parsing=True)
            expected = {"grant_type", "client_id", "code", "code_verifier", "redirect_uri"}
            if set(query) != expected or any(len(values) != 1 for values in query.values()):
                self.reply(400, b"{}")
                return
            with lock:
                grant = state.codes.pop(query["code"][0], None)
            challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(query["code_verifier"][0].encode()).digest()
                )
                .rstrip(b"=")
                .decode()
            )
            if (
                grant is None
                or not secrets.compare_digest(grant[1], challenge)
                or query["grant_type"] != ["authorization_code"]
                or query["client_id"] != ["installed-operator-test"]
                or query["redirect_uri"] != [callback]
            ):
                state.refusals += 1
                self.reply(400, b"{}")
                return
            state.exchanges += 1
            self.reply(200, json.dumps({"id_token": grant[0]}).encode())

        def log_message(self, format: str, *args: object) -> None:
            # Never write authorization codes, nonces or request bodies to logs.
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state = SyntheticIssuer(f"https://127.0.0.1:{server.server_port}", public.decode(), ca, tls_key)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ca, tls_key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if thread.is_alive():
            raise RuntimeError("Owned synthetic issuer did not stop")
        state.codes.clear()

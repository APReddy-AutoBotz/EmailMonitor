"""Closed loopback HTTPS reference API; real identity activation stays separate."""

import http.client
import json
import socket
import ssl
import threading
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode, urlsplit

import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from emailmonitor.config import Settings
from emailmonitor.identity.oidc import AuthenticationDenied, OIDCProvider
from emailmonitor.runtime.assembly import TestRuntimeConfig
from emailmonitor.runtime.delegation import ServiceBindings
from emailmonitor.runtime.service_api import ServiceAPIConfig, service_api


def loopback_https(value: str) -> None:
    if len(value) > 2048:
        raise ValueError("Bounded identity endpoint required")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "127.0.0.1"
        or parsed.port is None
        or not 1 <= parsed.port <= 65535
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Exact loopback HTTPS endpoint required")


class ReferenceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    issuer: str
    client_id: str = Field(min_length=1, max_length=200)
    authorization_endpoint: str
    token_endpoint: str
    redirect_uri: str
    verification_keys: dict[str, str]
    certificate_authority: Path

    @model_validator(mode="after")
    def validate_reference(self) -> "ReferenceIdentity":
        for endpoint in (
            self.issuer,
            self.authorization_endpoint,
            self.token_endpoint,
            self.redirect_uri,
        ):
            loopback_https(endpoint)
        if not 1 <= len(self.verification_keys) <= 4 or any(
            not key or len(key) > 200 or not value or len(value) > 8192 or "PRIVATE KEY" in value
            for key, value in self.verification_keys.items()
        ):
            raise ValueError("Bounded public identity verification keys required")
        for value in self.verification_keys.values():
            key = serialization.load_pem_public_key(value.encode())
            if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
                raise ValueError("Pinned RSA verification key required")
        return self


class ReferenceAPI(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    environment: Literal["test"]
    runtime_database_url: str = Field(repr=False)
    authentication_database_url: str = Field(repr=False)
    bindings: ServiceBindings
    identity: ReferenceIdentity
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    certificate: Path
    private_key: Path = Field(repr=False)

    @model_validator(mode="after")
    def runtime_boundary(self) -> "ReferenceAPI":
        self.runtime()
        if self.identity.redirect_uri != (f"https://127.0.0.1:{self.port}/auth/complete"):
            raise ValueError("Same-origin API callback required")
        if not self.bindings.tenants:
            raise ValueError("Explicit service bindings required")
        return self

    def runtime(self) -> TestRuntimeConfig:
        return TestRuntimeConfig(
            settings=Settings(environment="test", fixture_mode=True, identity_stub=True),
            runtime_database_url=self.runtime_database_url,
            authentication_database_url=self.authentication_database_url,
        )


class DeadlineHTTPS(http.client.HTTPSConnection):
    """Three-second total connection/exchange deadline, including slow-drip I/O."""

    def __init__(self, port: int, context: ssl.SSLContext) -> None:
        super().__init__("127.0.0.1", port, timeout=3, context=context)
        self.deadline = time.monotonic() + 3
        self.context = context
        self.watchdog: threading.Timer | None = None
        self.owned_socket: ssl.SSLSocket | None = None

    def remaining(self) -> float:
        value = self.deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("Identity exchange deadline")
        return value

    def connect(self) -> None:
        raw = socket.create_connection(("127.0.0.1", self.port), timeout=self.remaining())
        try:
            raw.settimeout(self.remaining())
            secured = self.context.wrap_socket(
                raw,
                server_hostname="127.0.0.1",
                do_handshake_on_connect=False,
            )
        except BaseException:
            raw.close()
            raise
        self.sock = secured
        self.owned_socket = secured
        self.watchdog = threading.Timer(self.remaining(), self.expire)
        self.watchdog.daemon = True
        self.watchdog.start()
        secured.do_handshake()
        self.remaining()

    def expire(self) -> None:
        if self.owned_socket is not None:
            try:
                self.owned_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.owned_socket.close()

    def finish(self) -> None:
        if self.watchdog is not None:
            self.watchdog.cancel()
            self.watchdog.join()
            self.watchdog = None
        try:
            super().close()
        finally:
            if self.owned_socket is not None:
                self.owned_socket.close()
                self.owned_socket = None


class ReferenceExchange:
    """Public-client PKCE exchange, only to the validated local test issuer.

    TLS verification is mandatory. No credential forwarding, redirects, retries,
    cookies or arbitrary endpoint selection from a request is supported.
    """

    def __init__(self, identity: ReferenceIdentity) -> None:
        self.identity = identity

    def exchange(self, code: str, verifier: str, redirect_uri: str) -> str:
        connection = None
        try:
            if (
                redirect_uri != self.identity.redirect_uri
                or not 1 <= len(code) <= 4096
                or not 1 <= len(verifier) <= 256
            ):
                raise AuthenticationDenied()
            endpoint = urlsplit(self.identity.token_endpoint)
            context = ssl.create_default_context(cafile=str(self.identity.certificate_authority))
            connection = DeadlineHTTPS(endpoint.port or 443, context)
            body = urlencode(
                {
                    "grant_type": "authorization_code",
                    "client_id": self.identity.client_id,
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": redirect_uri,
                }
            )
            if len(body.encode()) > 16_384:
                raise AuthenticationDenied()
            connection.request(
                "POST",
                endpoint.path or "/",
                body=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            encoded = response.read(65_537)
            if response.status != 200 or len(encoded) > 65_536:
                raise AuthenticationDenied()
            document = json.loads(encoded)
            token = document.get("id_token")
            if not isinstance(token, str) or not 1 <= len(token) <= 32_768:
                raise AuthenticationDenied()
            return token
        except Exception:
            raise AuthenticationDenied() from None
        finally:
            if connection is not None:
                connection.finish()


def run_api(config: ReferenceAPI) -> None:
    identity = config.identity
    provider = OIDCProvider(
        issuer=identity.issuer,
        client_id=identity.client_id,
        authorization_endpoint=identity.authorization_endpoint,
        redirect_uri=identity.redirect_uri,
        verification_keys=identity.verification_keys,
        exchange_adapter=ReferenceExchange(identity),
        test_only=True,
    )
    root = Path(__file__).resolve().parents[5]
    web = root / "static-web"
    if (
        not web.is_dir()
        or web.is_symlink()
        or not (web / "index.html").is_file()
        or (web / "index.html").is_symlink()
    ):
        raise ValueError("Installed static web artifact required")
    with service_api(ServiceAPIConfig(config.runtime(), config.bindings), provider) as application:

        @application.get("/auth/complete", include_in_schema=False)
        def complete() -> FileResponse:
            return FileResponse(web / "index.html", headers={"Cache-Control": "no-store"})

        application.mount("/", StaticFiles(directory=web, html=True), name="operator")
        uvicorn.run(
            application,
            host=config.host,
            port=config.port,
            ssl_certfile=str(config.certificate),
            ssl_keyfile=str(config.private_key),
            access_log=False,
            log_level="critical",
        )

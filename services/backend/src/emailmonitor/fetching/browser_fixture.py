"""Bounded test-only browser IPC. No browser launch or production entrypoint."""

import base64
import os
import selectors
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.fetching.tls_fixture import TLSFixtureGateway
from emailmonitor.sources.policy import Operation


class BrowserFixtureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: Literal["request"]
    identifier: int = Field(ge=1, le=64)
    url: str = Field(min_length=1, max_length=2048)
    method: Literal["GET"]
    resource: Literal["document", "fetch", "xhr"]


class BrowserFixtureMediator:
    """A compromised guest can request only bounded authorized synthetic HTML.

    No incoming headers/body/credentials, raw socket, resolver, arbitrary method,
    gateway settings or mutation commands are available through this protocol.
    """

    def __init__(self, settings: Settings, gateway: TLSFixtureGateway) -> None:
        require_fixture(settings)
        if type(gateway) is not TLSFixtureGateway:
            raise FetchDenied("fixture_gateway_type_denied")
        self._gateway = gateway
        self.requests = 0
        self.accepted = 0
        self.denied = 0

    def reply(self, raw: bytes) -> bytes:
        self.requests += 1
        if len(raw) > 8192 or self.requests > 64:
            raise FetchDenied("browser_ipc_limit_exceeded")
        try:
            request = BrowserFixtureRequest.model_validate_json(raw)
            body = self._gateway.fetch(request.url, Operation.BROWSER)
            if len(body) > 32768:
                raise FetchDenied("browser_ipc_body_limit_exceeded")
        except (ValidationError, FetchDenied):
            self.denied += 1
            return b'{"status":"denied"}\n'
        self.accepted += 1
        return b'{"status":"ok","body":"' + base64.b64encode(body) + b'","type":"text/html"}\n'


def validate_applied_profile(options: list[str], expected: dict[str, object]) -> None:
    """Docker CLI sends compact profile JSON to the daemon, not a file path."""
    import json

    if len(options) != 2 or "no-new-privileges" not in options:
        raise FetchDenied("browser_profile_denied")
    profiles = [value[len("seccomp=") :] for value in options if value.startswith("seccomp=")]
    if len(profiles) != 1:
        raise FetchDenied("browser_profile_denied")
    try:
        applied = json.loads(profiles[0])
    except ValueError:
        raise FetchDenied("browser_profile_denied") from None
    if applied != expected:
        raise FetchDenied("browser_profile_denied")


def write_bounded_reply(descriptor: int, payload: bytes, deadline: float) -> None:
    """Write one bounded IPC reply without trusting the guest to consume it.

    The descriptor remains nonblocking; the caller owns and closes it. A stalled
    consumer consumes only the remaining absolute conversation deadline.
    """
    if len(payload) > 65536:
        raise RuntimeError("Gateway reply limit exceeded")
    os.set_blocking(descriptor, False)
    pending = memoryview(payload)
    with selectors.DefaultSelector() as selector:
        selector.register(descriptor, selectors.EVENT_WRITE)
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise RuntimeError("Browser diagnostic deadline exceeded")
            if time.monotonic() >= deadline:
                raise RuntimeError("Browser diagnostic deadline exceeded")
            try:
                written = os.write(descriptor, pending)
            except BlockingIOError:
                continue
            if written <= 0:
                raise RuntimeError("Guest reply pipe closed")
            pending = pending[written:]

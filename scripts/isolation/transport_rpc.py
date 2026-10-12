"""Bounded owned-pipe control, with host-only current tenant authorization."""

import base64
import json
import os
import selectors
import subprocess
import time
from collections.abc import Callable
from typing import Any

from emailmonitor.fetching.browser_fixture import BrowserFixtureRequest, write_bounded_reply
from emailmonitor.fetching.plan import PlanScope
from emailmonitor.fetching.safety import FetchDenied, SafeURL, classify_url
from emailmonitor.sources.policy import Operation
from pydantic import ValidationError
from transport_gateway import scope_fields


class OwnedProcess:
    def __init__(self, identifier: str) -> None:
        if len(identifier) != 64 or any(c not in "0123456789abcdef" for c in identifier):
            raise RuntimeError("Invalid owned container identifier")
        self.process = subprocess.Popen(
            ["docker", "start", "--attach", "--interactive", identifier],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        assert (
            self.process.stdin is not None
            and self.process.stdout is not None
            and self.process.stderr is not None
        )
        self._buffer = bytearray()
        self._errors = bytearray()
        self._total = 0
        self.poisoned = False

    def send(self, value: dict[str, object], deadline: float) -> None:
        if self.poisoned:
            raise RuntimeError("Owned channel is poisoned")
        assert self.process.stdin is not None
        try:
            write_bounded_reply(
                self.process.stdin.fileno(), json.dumps(value).encode() + b"\n", deadline
            )
        except Exception:
            self.poisoned = True
            raise

    def receive(self, deadline: float) -> dict[str, Any]:
        if self.poisoned:
            raise RuntimeError("Owned channel is poisoned")
        assert self.process.stdout is not None and self.process.stderr is not None
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(self.process.stderr, selectors.EVENT_READ, "stderr")
                while True:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Owned channel deadline exceeded")
                    if b"\n" in self._buffer:
                        raw, _, tail = self._buffer.partition(b"\n")
                        self._buffer[:] = tail
                        if len(raw) > 65536:
                            raise RuntimeError("Owned frame limit exceeded")
                        frame = json.loads(raw)
                        if type(frame) is not dict:
                            raise RuntimeError("Invalid owned frame")
                        return frame
                    events = selector.select(deadline - time.monotonic())
                    if not events:
                        raise RuntimeError("Owned channel deadline exceeded")
                    for key, _ in events:
                        chunk = os.read(key.fd, 4096)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            if not selector.get_map() and b"\n" not in self._buffer:
                                raise RuntimeError("Owned process exited before a frame")
                            continue
                        self._total += len(chunk)
                        if self._total > 524288:
                            raise RuntimeError("Owned output limit exceeded")
                        target = self._buffer if key.data == "stdout" else self._errors
                        target.extend(chunk)
                        if len(target) > (65536 if key.data == "stdout" else 16384):
                            raise RuntimeError("Owned output buffer exceeded")
        except Exception:
            self.poisoned = True
            raise

    def close(self) -> None:
        self.poisoned = True
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


class GatewayProxy:
    def __init__(
        self,
        process: OwnedProcess,
        scope: Callable[[Operation], PlanScope],
        authorize: Callable[[PlanScope, SafeURL], None],
        family: int = 4,
        ca: str = "fixture",
    ) -> None:
        if type(family) is not int or family not in (4, 6):
            raise RuntimeError("Invalid literal family")
        if ca not in ("fixture", "untrusted"):
            raise RuntimeError("Invalid trusted CA selection")
        self._ca = ca
        self._process, self._scope, self._authorize, self._family = (
            process,
            scope,
            authorize,
            family,
        )
        self.authorizations = 0
        self.peers: list[list[object]] = []

    def fetch(self, value: str, operation: Operation = Operation.HTML) -> bytes:
        self.peers = []
        bound = self._scope(operation)
        if bound.operation != operation or not 0 < bound.deadline - time.monotonic() <= 5:
            raise FetchDenied("plan_scope_mismatch")
        url = classify_url(value, bound.allowed_hosts)
        self._authorize(bound, url)
        deadline = bound.deadline
        self._process.send(
            {
                "kind": "fetch",
                "url": value,
                "scope": scope_fields(bound),
                "family": self._family,
                "ca": self._ca,
            },
            deadline,
        )
        for _ in range(32):
            frame = self._process.receive(deadline)
            if frame.get("kind") == "authorize":
                if (
                    set(frame) != {"kind", "scope", "url"}
                    or frame["scope"] != scope_fields(bound)
                    or type(frame["url"]) is not str
                ):
                    self._process.poisoned = True
                    raise RuntimeError("Gateway policy scope mismatch")
                try:
                    approved = classify_url(frame["url"], bound.allowed_hosts)
                    self._authorize(bound, approved)
                    if time.monotonic() >= deadline:
                        raise FetchDenied("plan_deadline_denied")
                except FetchDenied:
                    self._process.send({"authorized": False}, deadline)
                else:
                    self.authorizations += 1
                    self._process.send({"authorized": True}, deadline)
                continue
            if frame == {"kind": "result", "status": "denied"}:
                raise FetchDenied("protected_fetch_denied")
            if (
                set(frame) == {"kind", "status", "body", "peers"}
                and frame["kind"] == "result"
                and frame["status"] == "ok"
                and type(frame["body"]) is str
            ):
                if type(frame["peers"]) is not list or not 1 <= len(frame["peers"]) <= 3:
                    raise RuntimeError("Missing actual peer receipts")
                self.peers = frame["peers"]
                body = base64.b64decode(frame["body"], validate=True)
                if len(body) > 32768:
                    raise RuntimeError("Gateway body cap exceeded")
                # Host policy remains authoritative even if a guest lies about a
                # successful result. Redirect callbacks already covered final URL.
                self._authorize(bound, url)
                if time.monotonic() >= deadline:
                    raise FetchDenied("plan_deadline_denied")
                return body
            self._process.poisoned = True
            raise RuntimeError("Invalid gateway result")
        self._process.poisoned = True
        raise RuntimeError("Gateway callback cap exceeded")


class BrowserProxyMediator:
    """Untrusted browser has only bounded byte requests; no gateway controls."""

    def __init__(self, proxy: GatewayProxy) -> None:
        self.proxy = proxy
        self.requests = self.accepted = self.denied = 0

    def reply(self, raw: bytes) -> bytes:
        self.requests += 1
        if len(raw) > 8192 or self.requests > 64:
            raise FetchDenied("browser_ipc_limit_exceeded")
        try:
            request = BrowserFixtureRequest.model_validate_json(raw)
            body = self.proxy.fetch(request.url, Operation.BROWSER)
        except (ValidationError, FetchDenied):
            self.denied += 1
            return b'{"status":"denied"}\n'
        self.accepted += 1
        return b'{"status":"ok","body":"' + base64.b64encode(body) + b'","type":"text/html"}\n'

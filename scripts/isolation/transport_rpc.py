"""Bounded owned-pipe control, with host-only current tenant authorization."""

import base64
import json
import os
import selectors
import subprocess
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from emailmonitor.fetching.browser_fixture import BrowserFixtureRequest, write_bounded_reply
from emailmonitor.fetching.plan import PlanScope
from emailmonitor.fetching.resources import HopResources
from emailmonitor.fetching.safety import FetchDenied, SafeURL, classify_url
from emailmonitor.organizations.database import AuthorizationDenied
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
        resources: HopResources | None = None,
        diagnostic_transport_only: bool = False,
    ) -> None:
        if type(family) is not int or family not in (4, 6):
            raise RuntimeError("Invalid literal family")
        if ca not in ("fixture", "untrusted"):
            raise RuntimeError("Invalid trusted CA selection")
        if type(diagnostic_transport_only) is not bool or (
            resources is None and not diagnostic_transport_only
        ):
            raise FetchDenied("source_resource_boundary_required")
        self._resources = resources
        self._active_resources: dict[str, object] = {}
        self._inflight = False
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
        if self._active_resources:
            raise RuntimeError("Previous resource state remains active")
        try:
            return self._fetch(value, operation)
        except BaseException as error:
            if self._inflight:
                self._process.poisoned = True
            try:
                self._abandon_resources()
            except Exception:
                error.add_note("Owned resource abandonment failed; server lease remains bounded")
            raise
        finally:
            # Normal successful protocol requires all per-hop completion frames.
            if self._active_resources:
                self._process.poisoned = True

    def _abandon_resources(self) -> None:
        tickets = tuple(self._active_resources.values())
        self._active_resources.clear()
        if self._resources is not None:
            for ticket in tickets:
                self._resources.finish(ticket, None, "")

    def _fetch(self, value: str, operation: Operation = Operation.HTML) -> bytes:
        self.peers = []
        bound = self._scope(operation)
        if bound.operation != operation or not 0 < bound.deadline - time.monotonic() <= 20:
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
        self._inflight = True
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
            if frame.get("kind") == "resource_acquire":
                if (
                    set(frame) != {"kind", "scope", "url", "id"}
                    or frame["scope"] != scope_fields(bound)
                    or type(frame["url"]) is not str
                    or type(frame["id"]) is not str
                    or self._active_resources
                ):
                    self._process.poisoned = True
                    raise RuntimeError("Invalid bounded resource scope")
                try:
                    identifier = str(UUID(frame["id"]))
                except ValueError as error:
                    self._process.poisoned = True
                    raise RuntimeError("Invalid resource identifier") from error
                if identifier != frame["id"]:
                    raise RuntimeError("Noncanonical resource identifier")
                approved = classify_url(frame["url"], bound.allowed_hosts)
                try:
                    self._authorize(bound, approved)
                    ticket = (
                        self._resources.acquire(approved, bound.operation, deadline)
                        if self._resources is not None
                        else object()
                    )
                    self._active_resources[identifier] = ticket
                except (FetchDenied, AuthorizationDenied):
                    self._process.send({"admitted": False}, deadline)
                else:
                    self._process.send({"admitted": True}, deadline)
                continue
            if frame.get("kind") == "resource_finish":
                if (
                    set(frame) != {"kind", "scope", "id", "status", "retry_after"}
                    or frame["scope"] != scope_fields(bound)
                    or type(frame["id"]) is not str
                    or frame["id"] not in self._active_resources
                    or (
                        frame["status"] is not None
                        and (type(frame["status"]) is not int or not 100 <= frame["status"] <= 599)
                    )
                    or type(frame["retry_after"]) is not str
                    or len(frame["retry_after"]) > 11
                    or (
                        frame["retry_after"]
                        and frame["retry_after"] != "unsupported"
                        and not (
                            len(frame["retry_after"]) <= 5
                            and frame["retry_after"].isascii()
                            and frame["retry_after"].isdecimal()
                        )
                    )
                ):
                    self._process.poisoned = True
                    raise RuntimeError("Invalid resource completion")
                ticket = self._active_resources.pop(frame["id"])
                try:
                    if self._resources is not None:
                        self._resources.finish(ticket, frame["status"], frame["retry_after"])
                except (FetchDenied, AuthorizationDenied):
                    self._process.send({"finished": False}, deadline)
                else:
                    self._process.send({"finished": True}, deadline)
                continue
            if frame == {"kind": "result", "status": "denied"}:
                self._inflight = False
                raise FetchDenied("protected_fetch_denied")
            if (
                set(frame) == {"kind", "status", "body", "peers"}
                and frame["kind"] == "result"
                and frame["status"] == "ok"
                and type(frame["body"]) is str
            ):
                if type(frame["peers"]) is not list or not 1 <= len(frame["peers"]) <= 3:
                    raise RuntimeError("Missing actual peer receipts")
                if self._active_resources:
                    self._process.poisoned = True
                    raise RuntimeError("Resource completion missing before byte release")
                self.peers = frame["peers"]
                body = base64.b64decode(frame["body"], validate=True)
                if len(body) > 32768:
                    raise RuntimeError("Gateway body cap exceeded")
                self._inflight = False
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
        self._selected_peers: tuple[tuple[object, ...], ...] = ()

    @property
    def selected_peers(self) -> tuple[tuple[object, ...], ...]:
        return self._selected_peers

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
        # A denied later request clears proxy-local receipts. Preserve only
        # successful byte-release observations as independent copied records.
        self._selected_peers += tuple(tuple(peer) for peer in self.proxy.peers)
        return b'{"status":"ok","body":"' + base64.b64encode(body) + b'","type":"text/html"}\n'

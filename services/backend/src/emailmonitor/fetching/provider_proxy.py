"""Packaged controlled gateway proxy; the supervisor owns endpoint/topology verification."""

import base64
import hashlib
import json
import sys
from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

from pydantic import ValidationError

from emailmonitor.fetching.plan import PlanScope
from emailmonitor.fetching.resources import HopResources
from emailmonitor.fetching.safety import FetchDenied, classify_url
from emailmonitor.fetching.sciencedirect import (
    AcquiredResponse,
    ProviderBinding,
    ProviderBoundary,
    ProviderResponse,
)


class GatewayPipe(Protocol):
    poisoned: bool

    def send(self, value: dict[str, object], deadline: float) -> None: ...
    def receive(self, deadline: float) -> dict[str, Any]: ...


def scope_fields(scope: PlanScope) -> dict[str, object]:
    return {
        "organization": str(scope.organization),
        "source": scope.source,
        "policy_version": scope.policy_version,
        "operation": scope.operation.value,
        "allowed_hosts": sorted(scope.allowed_hosts),
        "deadline": scope.deadline,
        "max_redirects": scope.max_redirects,
    }


ENDPOINTS = {"fixture-a": ("8.8.8.3", "2001:4860:ffff:ee00::3")}


def exact_binding(value: object, expected: ProviderBinding) -> bool:
    try:
        return ProviderBinding.model_validate_json(json.dumps(value)) == expected
    except (ValueError, TypeError, ValidationError):
        return False


class ProviderProxy:
    """Protected composition owns current state and each resource ticket."""

    def __init__(self, process: GatewayPipe) -> None:
        self.process = process
        self.peers: list[list[object]] = []
        self.finished: list[tuple[int | None, str]] = []

    def acquire(
        self,
        boundary: ProviderBoundary,
        *,
        resources: HopResources | None = None,
        family: int = 4,
        ca: str = "fixture",
        after_finish: Callable[[], None] = lambda: None,
    ) -> AcquiredResponse:
        if type(family) is not int or family not in (4, 6) or ca not in ("fixture", "untrusted"):
            raise FetchDenied("controlled_provider_route_denied")
        boundary.check_current()
        request, binding = boundary.request, boundary.binding
        scope = scope_fields(boundary.planner.scope)
        active: str | None = None
        inflight = False
        ticket: object | None = None
        resource_admitted = False
        resource_finished = False
        self.peers = []
        try:
            self.process.send(
                {
                    "kind": "provider",
                    "request": request.model_dump(mode="json"),
                    "binding": binding.model_dump(mode="json"),
                    "family": family,
                    "ca": ca,
                },
                binding.deadline,
            )
            inflight = True
            for _ in range(128):
                frame: dict[str, Any] = self.process.receive(binding.deadline)
                kind = frame.get("kind")
                if kind == "provider_current":
                    if set(frame) != {"kind", "binding"} or not exact_binding(
                        frame["binding"], binding
                    ):
                        raise RuntimeError("Provider callback binding mismatch")
                    try:
                        boundary.check_current()
                    except FetchDenied:
                        approved = False
                    else:
                        approved = True
                    self.process.send({"authorized": approved}, binding.deadline)
                elif kind == "resource_acquire":
                    identifier = frame.get("id")
                    if (
                        type(identifier) is not str
                        or str(UUID(identifier)) != identifier
                        or active is not None
                        or (resources is not None and resource_admitted)
                        or frame
                        != {
                            "kind": kind,
                            "id": identifier,
                            "scope": scope,
                            "url": request.url,
                        }
                    ):
                        raise RuntimeError("Provider resource scope mismatch")
                    boundary.check_current()
                    try:
                        if resources is not None:
                            ticket = resources.acquire(
                                classify_url(request.url, frozenset({"api.elsevier.com"})),
                                request.operation,
                                binding.deadline,
                            )
                            if ticket is None:
                                raise RuntimeError("Owned provider resource ticket required")
                            resource_admitted = True
                    except FetchDenied:
                        self.process.send({"admitted": False}, binding.deadline)
                    else:
                        active = identifier
                        self.process.send({"admitted": True}, binding.deadline)
                elif kind == "resource_finish":
                    status, retry = frame.get("status"), frame.get("retry_after")
                    if (
                        active is None
                        or set(frame) != {"kind", "id", "scope", "status", "retry_after"}
                        or frame["id"] != active
                        or frame["scope"] != scope
                        or not (status is None or type(status) is int and 100 <= status <= 599)
                        or type(retry) is not str
                        or len(retry) > 11
                    ):
                        raise RuntimeError("Provider resource release mismatch")
                    self.finished.append((status, retry))
                    if resources is not None and ticket is not None:
                        owned, ticket = ticket, None
                        resources.finish(owned, status, retry)
                        resource_finished = True
                    active = None
                    after_finish()
                    self.process.send({"finished": True}, binding.deadline)
                elif kind == "provider_result":
                    if active is not None:
                        raise RuntimeError("Provider resource remains active")
                    if frame == {"kind": kind, "status": "denied"}:
                        inflight = False
                        raise FetchDenied("controlled_provider_denied")
                    if (
                        set(frame)
                        != {
                            "kind",
                            "status",
                            "request",
                            "binding",
                            "body",
                            "digest",
                            "peers",
                        }
                        or frame["status"] != "ok"
                        or frame["request"] != request.model_dump(mode="json")
                        or not exact_binding(frame["binding"], binding)
                        or type(frame["body"]) is not str
                        or frame["peers"]
                        != [
                            [
                                ENDPOINTS["fixture-a"][0 if family == 4 else 1],
                                443,
                                "api.elsevier.com",
                            ]
                        ]
                    ):
                        raise RuntimeError("Provider dispatch response mismatch")
                    if resources is not None and not (resource_admitted and resource_finished):
                        raise RuntimeError("Provider resource lifecycle incomplete")
                    data = base64.b64decode(frame["body"], validate=True)
                    if hashlib.sha256(data).hexdigest() != frame["digest"]:
                        raise RuntimeError("Provider response digest mismatch")
                    inflight = False
                    acquired = boundary.read_response(
                        ProviderResponse(
                            request.url,
                            200,
                            request.plan().media_type,
                            (data,),
                            binding,
                            len(data),
                        )
                    )
                    self.peers = frame["peers"]
                    return acquired
                else:
                    raise RuntimeError("Unexpected provider protocol frame")
            raise RuntimeError("Provider callback limit exceeded")
        finally:
            # Uncertain pipes are poisoned even if SQL cleanup itself is denied.
            if inflight or active is not None:
                self.process.poisoned = True
            if resources is not None and ticket is not None:
                owned, ticket = ticket, None
                original_error = sys.exception()
                try:
                    resources.finish(owned, None, "")
                except Exception:
                    if original_error is None:
                        raise
                    original_error.add_note(
                        "Owned provider resource cleanup failed; lease remains bounded"
                    )

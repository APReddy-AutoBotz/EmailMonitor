"""Controlled provider dispatch over existing owned pipes, never production admission.

Only fixed fake material is available in the guest. Host binding callbacks are test
state, explicitly not a synthetic-policy grant for a real provider. No secret value
crosses this protocol. Existing frame, network and process bounds are unchanged.
"""

import base64
import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from emailmonitor.config import Settings
from emailmonitor.fetching.credentials import CredentialLease
from emailmonitor.fetching.fixture import FetchLimits
from emailmonitor.fetching.protected import ProtectedGateway, SnapshotResolver
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.fetching.sciencedirect import (
    AcquiredResponse,
    CredentialReference,
    ProviderBinding,
    ProviderBoundary,
    ProviderRequest,
    ProviderResponse,
)
from pydantic import ValidationError
from transport_gateway import HostResources, scope_fields
from transport_manifest import ENDPOINTS

if TYPE_CHECKING:
    from transport_rpc import OwnedProcess


class SyntheticCredentials:
    """Fixed fake fixture value, no environment/secret-store route or real key."""

    @contextmanager
    def open(self, reference: CredentialReference, fingerprint: str) -> Iterator[CredentialLease]:
        yield CredentialLease(reference, fingerprint, b"em-synthetic-provider-only")


def serve_provider(
    frame: dict[str, object],
    settings: Settings,
    resolver: SnapshotResolver,
    emit: Callable[[dict[str, object]], None],
    read: Callable[[], dict[str, object]],
) -> None:
    if set(frame) != {"kind", "request", "binding", "family", "ca"}:
        raise RuntimeError("Invalid controlled provider command")
    request = ProviderRequest.model_validate_json(json.dumps(frame["request"]))
    binding = ProviderBinding.model_validate_json(json.dumps(frame["binding"]))
    family, ca = frame["family"], frame["ca"]
    if type(family) is not int or family not in (4, 6) or ca not in ("fixture", "untrusted"):
        raise RuntimeError("Invalid controlled provider route")

    def current() -> ProviderBinding:
        emit({"kind": "provider_current", "binding": binding.model_dump(mode="json")})
        if read() != {"authorized": True}:
            raise FetchDenied("provider_current_binding_denied")
        return binding

    try:
        boundary = ProviderBoundary(request, binding, current)
        gateway = ProtectedGateway(
            settings,
            resolver,
            Path("/app/fixture-cert.pem" if ca == "fixture" else "/app/untrusted-cert.pem"),
            lambda operation: boundary.planner.scope,
            lambda scope, url: boundary.check_current(),
            FetchLimits(max_bytes=request.max_bytes, total_seconds=20, max_redirects=0),
            family,
            resources=HostResources(boundary.planner.scope),
        )
        acquired = gateway.acquire_provider(boundary, SyntheticCredentials())
        emit(
            {
                "kind": "provider_result",
                "status": "ok",
                "request": acquired.request.model_dump(mode="json"),
                "binding": acquired.binding.model_dump(mode="json"),
                "body": base64.b64encode(acquired.body).decode("ascii"),
                "digest": acquired.content_digest,
                "peers": gateway.peer_receipts,
            }
        )
    except FetchDenied:
        emit({"kind": "provider_result", "status": "denied"})


def exact_binding(value: object, expected: ProviderBinding) -> bool:
    try:
        return ProviderBinding.model_validate_json(json.dumps(value)) == expected
    except (ValueError, TypeError, ValidationError):
        return False


class ProviderProxy:
    """Host test composition owns current state and each resource ticket."""

    def __init__(self, process: "OwnedProcess") -> None:
        self.process = process
        self.peers: list[list[object]] = []
        self.finished: list[tuple[int | None, str]] = []

    def acquire(
        self,
        boundary: ProviderBoundary,
        *,
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
                        or frame
                        != {"kind": kind, "id": identifier, "scope": scope, "url": request.url}
                    ):
                        raise RuntimeError("Provider resource scope mismatch")
                    boundary.check_current()
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
                        != {"kind", "status", "request", "binding", "body", "digest", "peers"}
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
                    data = base64.b64decode(frame["body"], validate=True)
                    if hashlib.sha256(data).hexdigest() != frame["digest"]:
                        raise RuntimeError("Provider response digest mismatch")
                    inflight = False
                    acquired = boundary.read_response(
                        ProviderResponse(
                            request.url, 200, request.plan().media_type, (data,), binding, len(data)
                        )
                    )
                    self.peers = frame["peers"]
                    return acquired
                else:
                    raise RuntimeError("Unexpected provider protocol frame")
            raise RuntimeError("Provider callback limit exceeded")
        finally:
            if inflight or active is not None:
                self.process.poisoned = True

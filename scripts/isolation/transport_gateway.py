"""Closed trusted gateway process: owned-pipe requests and host policy callbacks."""

import base64
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import FetchLimits
from emailmonitor.fetching.plan import PlanScope
from emailmonitor.fetching.protected import (
    ProtectedGateway,
    ResolverRoute,
    SnapshotResolver,
)
from emailmonitor.fetching.safety import FetchDenied, SafeURL
from emailmonitor.sources.policy import Operation
from transport_manifest import ENDPOINTS, HOST
from transport_routes import escape_evidence, evidence


def read_frame() -> dict[str, object]:
    raw = sys.stdin.buffer.readline(8194)
    if len(raw) > 8192 or not raw.endswith(b"\n"):
        raise RuntimeError("Missing bounded trusted-host frame")
    value = json.loads(raw)
    if type(value) is not dict:
        raise RuntimeError("Invalid trusted-host frame")
    return value


def emit(value: dict[str, object]) -> None:
    raw = json.dumps(value, separators=(",", ":"))
    if len(raw) > 65536:
        raise RuntimeError("Gateway output limit exceeded")
    print(raw, flush=True)


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


class HostResources:
    """No credentials or database route in guest; host owns current admission."""

    def __init__(self, bound: PlanScope) -> None:
        self.bound = bound

    def acquire(self, url: SafeURL, operation: Operation, deadline: float) -> object:
        if operation != self.bound.operation or deadline != self.bound.deadline:
            raise FetchDenied("plan_scope_mismatch")
        identifier = str(uuid4())
        emit(
            {
                "kind": "resource_acquire",
                "scope": scope_fields(self.bound),
                "url": url.normalized,
                "id": identifier,
            }
        )
        if read_frame() != {"admitted": True}:
            raise FetchDenied("source_resource_denied")
        return identifier

    def finish(self, ticket: object, status: int | None, retry_after: str) -> None:
        if type(ticket) is not str or str(UUID(ticket)) != ticket:
            raise FetchDenied("source_resource_denied")
        safe_retry = (
            retry_after
            if retry_after.isascii() and retry_after.isdecimal() and len(retry_after) <= 5
            else "unsupported"
            if retry_after
            else ""
        )
        emit(
            {
                "kind": "resource_finish",
                "scope": scope_fields(self.bound),
                "id": ticket,
                "status": status,
                "retry_after": safe_retry,
            }
        )
        if read_frame() != {"finished": True}:
            raise FetchDenied("source_resource_denied")


def main() -> None:
    emit({"kind": "ready", "evidence": evidence("gateway")})
    settings = Settings(environment="test", fixture_mode=True)
    resolver = SnapshotResolver(settings, ResolverRoute(ENDPOINTS["fixture-a"][0]))
    for _ in range(64):
        frame = read_frame()
        if set(frame) == {"kind", "peer"} and frame["kind"] == "escape":
            emit(
                {
                    "kind": "escape",
                    "evidence": escape_evidence("gateway", frame["peer"]),
                }
            )
            continue
        if frame == {"kind": "inspect"}:
            emit({"kind": "inspected", "evidence": evidence("gateway")})
            continue
        if frame == {"kind": "stop"}:
            emit({"kind": "stopped"})
            return
        if (
            set(frame) != {"kind", "url", "scope", "family", "ca"}
            or frame["kind"] != "fetch"
            or type(frame["url"]) is not str
            or type(frame["scope"]) is not dict
        ):
            raise RuntimeError("Invalid gateway command")
        ca = frame["ca"]
        if ca not in ("fixture", "untrusted"):
            raise RuntimeError("Invalid trusted CA selection")
        ca_file = Path("/app/fixture-cert.pem" if ca == "fixture" else "/app/untrusted-cert.pem")
        family = frame["family"]
        if type(family) is not int or family not in (4, 6):
            raise RuntimeError("Invalid selected family")
        fields = frame["scope"]
        if (
            set(fields)
            != {
                "organization",
                "source",
                "policy_version",
                "operation",
                "allowed_hosts",
                "deadline",
                "max_redirects",
            }
            or fields["allowed_hosts"] != [HOST]
            or fields["source"] != "synthetic-publisher"
            or fields["operation"] not in ("fetch_html", "browser")
        ):
            raise RuntimeError("Invalid trusted scope")
        bound = PlanScope(
            UUID(str(fields["organization"])),
            str(fields["source"]),
            fields["policy_version"],
            Operation(str(fields["operation"])),
            frozenset({HOST}),
            fields["deadline"],
            fields["max_redirects"],
        )

        def authorize(scope: PlanScope, url: SafeURL) -> None:
            emit(
                {
                    "kind": "authorize",
                    "scope": scope_fields(scope),
                    "url": url.normalized,
                }
            )
            if read_frame() != {"authorized": True}:
                raise FetchDenied("source_policy_denied")

        def supply(operation: Operation, current: PlanScope = bound) -> PlanScope:
            if operation != current.operation:
                raise FetchDenied("plan_scope_mismatch")
            return current

        try:
            gateway = ProtectedGateway(
                settings,
                resolver,
                ca_file,
                supply,
                authorize,
                FetchLimits(max_bytes=32768, total_seconds=20, max_redirects=2),
                family,
                resources=HostResources(bound),
            )
            body = gateway.fetch(frame["url"], bound.operation)
            emit(
                {
                    "kind": "result",
                    "status": "ok",
                    "body": base64.b64encode(body).decode("ascii"),
                    "peers": gateway.peer_receipts,
                }
            )
        except FetchDenied:
            emit({"kind": "result", "status": "denied"})
    raise RuntimeError("Gateway command limit exceeded")


if __name__ == "__main__":
    main()

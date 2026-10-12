"""Network-free protocol/stage regressions; actual I/O requires isolated CI."""

import ipaddress
import socket
import struct
import time
from pathlib import Path
from uuid import UUID

import pytest
from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import FetchLimits
from emailmonitor.fetching.plan import HopPlan, HopPlanner, PlanScope
from emailmonitor.fetching.protected import (
    ProtectedGateway,
    ResolverRoute,
    SnapshotResolver,
    decode_snapshot,
    question,
)
from emailmonitor.fetching.safety import FetchDenied, SafeURL
from emailmonitor.sources.policy import Operation
from tls_fixture_server import certificate

SETTINGS = Settings(environment="test", fixture_mode=True)
HOST = "synthetic.publisher.example"
URL = f"https://{HOST}/article-a.html"
V4, V6 = "8.8.8.3", "2001:4860:ffff:ee00::3"


def answer(records: tuple[str, ...], kind: int = 1) -> bytes:
    expected = question(HOST, kind)
    raw = struct.pack("!HHHHHH", 42, 0x8400, 1, len(records), 0, 0) + expected
    for record in records:
        address = ipaddress.ip_address(record).packed
        raw += b"\xc0\x0c" + struct.pack("!HHIH", kind, 1, 0, len(address)) + address
    return raw


@pytest.mark.parametrize("kind,records", [(1, (V4,)), (28, (V6,)), (1, ()), (28, ())])
def test_complete_authoritative_family_snapshot(kind: int, records: tuple[str, ...]) -> None:
    assert decode_snapshot(answer(records, kind), 42, question(HOST, kind)) == records


@pytest.mark.parametrize(
    "change",
    [
        "id",
        "flags",
        "question",
        "extra",
        "count",
        "alias",
        "ttl",
        "length",
        "trailing",
        "short",
        "duplicate",
        "oversize",
    ],
)
def test_dns_wire_refuses_ambiguous_or_incomplete_snapshot(change: str) -> None:
    raw = bytearray(answer((V4,)))
    offset = 12 + len(question(HOST, 1))
    if change == "id":
        raw[1] = 43
    elif change == "flags":
        raw[2] |= 2
    elif change == "question":
        raw[14] = ord("x")
    elif change == "extra":
        raw[11] = 1
    elif change == "count":
        raw[7] = 33
    elif change == "alias":
        raw[offset + 3] = 5
    elif change == "ttl":
        raw[offset + 9] = 61
    elif change == "length":
        raw[offset + 11] = 16
    elif change == "trailing":
        raw += b"x"
    elif change == "short":
        raw = raw[:-1]
    elif change == "duplicate":
        raw = bytearray(answer((V4, V4)))
    else:
        raw += b"x" * 513
    with pytest.raises(FetchDenied):
        decode_snapshot(bytes(raw), 42, question(HOST, 1))


@pytest.mark.parametrize(
    "host", ["", "EXAMPLE.test", "a..test", "-a.test", "a_.test", "x" * 64 + ".test", "é.test"]
)
def test_dns_question_shape_denied(host: str) -> None:
    with pytest.raises(FetchDenied):
        question(host, 1)


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "::1", "10.0.0.1", "169.254.169.254", "fc00::1", "::ffff:8.8.8.3", "bad"],
)
def test_resolver_has_no_private_route_exception(address: str) -> None:
    with pytest.raises(FetchDenied):
        ResolverRoute(address)


def test_production_and_default_mode_refuse_before_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("No I/O permitted")

    monkeypatch.setattr(socket, "socket", forbidden)
    for settings in (Settings(), Settings(environment="development"), Settings(environment="test")):
        with pytest.raises(FetchDenied):
            SnapshotResolver(settings, ResolverRoute(V4))


def gateway(tmp_path: Path, authorize: object = None) -> ProtectedGateway:
    cert, _ = certificate(tmp_path)

    def scope(operation: Operation) -> PlanScope:
        return PlanScope(
            UUID("11111111-1111-4111-8111-111111111111"),
            "synthetic-publisher",
            1,
            operation,
            frozenset({HOST}),
            time.monotonic() + 4,
            2,
        )

    def allow(bound: PlanScope, url: SafeURL) -> None:
        if callable(authorize):
            authorize(bound, url)

    return ProtectedGateway(
        SETTINGS,
        SnapshotResolver(SETTINGS, ResolverRoute(V4)),
        cert,
        scope,
        allow,
        FetchLimits(total_seconds=5, max_redirects=2),
    )


def test_transport_stage_order_and_redirect_freshness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    target = gateway(tmp_path, lambda bound, url: events.append("authorize:" + url.path))
    snapshots = iter([(V4, V6), ("8.8.8.4", "2001:4860:ffff:ee00::4")])

    def resolve(self: SnapshotResolver, url: SafeURL, planner: HopPlanner) -> tuple[str, ...]:
        events.append("dns:" + url.path)
        return next(snapshots)

    peers: list[str] = []

    def request(
        self: ProtectedGateway, planner: HopPlanner, plan: HopPlan
    ) -> tuple[int, dict[str, str], bytes]:
        planner.before_connect(plan)
        peers.append(plan.selected_address)
        if len(peers) == 1:
            return 302, {"location": "/article-b.html"}, b""
        return 200, {"content-type": "text/html"}, b"synthetic"

    monkeypatch.setattr(SnapshotResolver, "resolve", resolve)
    monkeypatch.setattr(ProtectedGateway, "_request", request)
    assert target.fetch(URL) == b"synthetic"
    assert peers == [V4, "8.8.8.4"]
    assert events[0:2] == ["authorize:/article-a.html", "dns:/article-a.html"]
    assert events[-1] == "authorize:/article-b.html"
    assert events.count("dns:/article-b.html") == 1


@pytest.mark.parametrize("records", [(V4, "127.0.0.1"), (V6, "fc00::1"), (V6,), ()])
def test_entire_set_or_missing_selected_family_refuses_tcp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, records: tuple[str, ...]
) -> None:
    target = gateway(tmp_path)
    monkeypatch.setattr(SnapshotResolver, "resolve", lambda *args: records)
    monkeypatch.setattr(
        ProtectedGateway, "_request", lambda *args: pytest.fail("TCP must not start")
    )
    with pytest.raises(FetchDenied):
        target.fetch(URL)


def test_release_rechecks_revocation_and_no_forbidden_redirect_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revoked = [False]

    def allow(bound: PlanScope, url: SafeURL) -> None:
        if revoked[0]:
            raise FetchDenied("source_policy_denied")

    target = gateway(tmp_path, allow)
    monkeypatch.setattr(SnapshotResolver, "resolve", lambda *args: (V4, V6))

    def request(*args: object) -> tuple[int, dict[str, str], bytes]:
        revoked[0] = True
        return 200, {"content-type": "text/html"}, b"unreleased"

    monkeypatch.setattr(ProtectedGateway, "_request", request)
    with pytest.raises(FetchDenied, match="source_policy"):
        target.fetch(URL)
    revoked[0] = False
    monkeypatch.setattr(
        ProtectedGateway,
        "_request",
        lambda *args: (302, {"location": "https://denied.fixture.example/"}, b""),
    )
    calls: list[str] = []

    def resolve(self: SnapshotResolver, url: SafeURL, planner: HopPlanner) -> tuple[str, ...]:
        calls.append(url.host)
        return (V4, V6)

    monkeypatch.setattr(SnapshotResolver, "resolve", resolve)
    with pytest.raises(FetchDenied):
        target.fetch(URL)
    assert calls == [HOST]

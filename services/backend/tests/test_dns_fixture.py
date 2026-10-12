"""Actual synthetic loopback DNS/TLS; no external network or production activation."""

import socket
import struct
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from dns_fixture_server import answer
from dns_fixture_server import server as dns_server
from emailmonitor.config import Settings
from emailmonitor.fetching.dns_fixture import QNAME, DNSFixtureResolver, SyntheticDNSRoute
from emailmonitor.fetching.fixture import FetchLimits
from emailmonitor.fetching.safety import FetchDenied, IsolationUnavailable
from emailmonitor.fetching.tls_fixture import TLSFixtureGateway
from tls_fixture_server import Response
from tls_fixture_server import server as tls_server

SETTINGS = Settings(environment="test", fixture_mode=True)
URL = "https://synthetic.publisher.example/article-a.html"
QUERY = struct.pack("!HHHHHH", 19, 0, 1, 0, 0, 0) + QNAME + struct.pack("!HH", 1, 1)


def test_actual_dns_gate_verified_tls_and_no_os_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("OS name service must not be used")

    with (
        tls_server(tmp_path, {"/article-a.html": Response()}) as (endpoint, calls),
        dns_server() as (route, queries),
    ):
        for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex"):
            monkeypatch.setattr(socket, name, forbidden)
        authorization: list[str] = []
        gateway = TLSFixtureGateway(
            SETTINGS,
            endpoint,
            lambda url, op: authorization.append(url.path),
            resolver=DNSFixtureResolver(SETTINGS, route),
        )
        assert gateway.fetch(URL) == b"<p>synthetic observation</p>"
        assert len(calls) == 1 and len(queries) == 2
        assert [struct.unpack("!H", q[-4:-2])[0] for q in queries] == [1, 28]
        assert authorization == ["/article-a.html"] * 3
        assert set(calls[0]) == {"Host", "Accept", "Connection"}


def test_actual_changed_dns_does_not_change_pinned_peer(tmp_path: Path) -> None:
    def changing(query: bytes, count: int) -> bytes:
        kind = struct.unpack("!H", query[-4:-2])[0]
        return answer(query, ("127.0.0.2",) if count > 2 and kind == 1 else None)

    with (
        tls_server(tmp_path, {"/article-a.html": Response()}) as (endpoint, calls),
        dns_server(changing) as (route, queries),
    ):
        gateway = TLSFixtureGateway(
            SETTINGS, endpoint, lambda url, op: None, resolver=DNSFixtureResolver(SETTINGS, route)
        )
        assert gateway.fetch(URL) == b"<p>synthetic observation</p>"
        with pytest.raises(FetchDenied, match="manifest"):
            gateway.fetch(URL)
        assert len(calls) == 1 and len(queries) == 4


@pytest.mark.parametrize(
    "records,kind",
    [
        (("127.0.0.2",), 1),
        (("127.0.0.1", "8.8.8.8"), 1),
        (("127.0.0.1", "127.0.0.1"), 1),
        ((), 1),
        (("::1",), 28),
        (("::ffff:127.0.0.1",), 28),
        (("2606:4700:4700::1111",), 28),
    ],
)
def test_actual_mixed_or_unlisted_dns_never_reaches_tls(
    tmp_path: Path, records: tuple[str, ...], kind: int
) -> None:
    def reply(query: bytes, count: int) -> bytes:
        return answer(query, records if struct.unpack("!H", query[-4:-2])[0] == kind else None)

    with (
        tls_server(tmp_path, {"/article-a.html": Response()}) as (endpoint, calls),
        dns_server(reply) as (route, queries),
    ):
        gateway = TLSFixtureGateway(
            SETTINGS, endpoint, lambda url, op: None, resolver=DNSFixtureResolver(SETTINGS, route)
        )
        with pytest.raises(FetchDenied):
            gateway.fetch(URL)
        assert calls == [] and 1 <= len(queries) <= 2


def test_authorization_denied_before_dns_and_revoked_after_dns(tmp_path: Path) -> None:
    with (
        tls_server(tmp_path, {"/article-a.html": Response()}) as (endpoint, calls),
        dns_server() as (route, queries),
    ):
        count = 0
        limit = 0

        def authorize(url: object, operation: object) -> None:
            nonlocal count
            count += 1
            if count > limit:
                raise FetchDenied("source_policy_denied")

        gateway = TLSFixtureGateway(
            SETTINGS, endpoint, authorize, resolver=DNSFixtureResolver(SETTINGS, route)
        )
        with pytest.raises(FetchDenied, match="policy"):
            gateway.fetch(URL)
        assert queries == [] and calls == []
        count, limit = 0, 1
        with pytest.raises(FetchDenied, match="policy"):
            gateway.fetch(URL)
        assert len(queries) == 2 and calls == []


def test_actual_dns_deadline_has_no_retry_or_tls_fallback(tmp_path: Path) -> None:
    with (
        tls_server(tmp_path, {"/article-a.html": Response()}) as (endpoint, calls),
        dns_server(lambda query, count: None) as (route, queries),
    ):
        gateway = TLSFixtureGateway(
            SETTINGS,
            endpoint,
            lambda url, op: None,
            FetchLimits(total_seconds=0.05),
            DNSFixtureResolver(SETTINGS, route),
        )
        start = time.monotonic()
        with pytest.raises(FetchDenied, match="connection"):
            gateway.fetch(URL)
        assert time.monotonic() - start < 1
        assert len(queries) == 1 and calls == []


@pytest.mark.parametrize(
    "index,value", [(1, 18), (2, 0x86), (3, 1), (5, 2), (7, 33), (9, 1), (11, 1), (12, 0xC0)]
)
def test_malformed_dns_header_or_question_denied(index: int, value: int) -> None:
    raw = bytearray(answer(QUERY))
    raw[index] = value
    with pytest.raises(FetchDenied):
        DNSFixtureResolver.decode(bytes(raw), 19, 1)


def test_dns_exact_owner_lengths_types_and_complete_consumption() -> None:
    valid = answer(QUERY)
    offset = 12 + len(QNAME) + 4
    pointer = valid[:offset] + b"\xc0\x0c" + valid[offset + len(QNAME) :]
    assert DNSFixtureResolver.decode(pointer, 19, 1) == ("127.0.0.1",)
    variants = [
        valid[:-1],
        valid + b"x",
        valid + b"x" * 512,
        valid[:offset] + b"\xc0\x00" + valid[offset + len(QNAME) :],
    ]
    for field, value in ((0, 5), (2, 2), (4, 61), (8, 16)):
        raw = bytearray(valid)
        position = offset + len(QNAME) + field
        raw[position : position + 2] = struct.pack("!H", value)
        variants.append(bytes(raw))
    for wire in variants:
        with pytest.raises(FetchDenied):
            DNSFixtureResolver.decode(wire, 19, 1)


def test_fixture_resolver_and_manifest_are_unavailable_in_production() -> None:
    route = SyntheticDNSRoute(53)
    for settings in (Settings(), Settings(environment="test")):
        with pytest.raises(IsolationUnavailable):
            DNSFixtureResolver(settings, route)
    for address in ("0.0.0.0", "127.0.0.2", "::1", "8.8.8.8"):
        with pytest.raises(ValueError):
            SyntheticDNSRoute(53, address)
    for port in (0, 65536, True):
        with pytest.raises(ValueError):
            SyntheticDNSRoute(port)
    with pytest.raises(ValueError):
        SyntheticDNSRoute(53, hostname="denied.fixture.example")
    with pytest.raises(FrozenInstanceError):
        attribute = "address"
        setattr(route, attribute, "127.0.0.2")
    resolver = DNSFixtureResolver(SETTINGS, route)
    with pytest.raises(FetchDenied, match="host"):
        resolver.resolve("denied.fixture.example", time.monotonic() + 1)


def test_actual_redirect_rechecks_dns_snapshot_before_next_tls(tmp_path: Path) -> None:
    def changing(query: bytes, count: int) -> bytes:
        kind = struct.unpack("!H", query[-4:-2])[0]
        return answer(query, ("127.0.0.2",) if count > 2 and kind == 1 else None)

    with (
        tls_server(
            tmp_path,
            {
                "/article-a.html": Response(302, b"", "/article-b.html"),
                "/article-b.html": Response(),
            },
        ) as (endpoint, calls),
        dns_server(changing) as (route, queries),
    ):
        gateway = TLSFixtureGateway(
            SETTINGS, endpoint, lambda url, op: None, resolver=DNSFixtureResolver(SETTINGS, route)
        )
        with pytest.raises(FetchDenied, match="manifest"):
            gateway.fetch(URL)
        assert len(queries) == 4 and len(calls) == 1


def test_actual_dns_questions_share_the_gateway_deadline(tmp_path: Path) -> None:
    def delayed(query: bytes, count: int) -> bytes:
        time.sleep(0.04)
        return answer(query)

    with (
        tls_server(tmp_path, {"/article-a.html": Response()}) as (endpoint, calls),
        dns_server(delayed) as (route, queries),
    ):
        gateway = TLSFixtureGateway(
            SETTINGS,
            endpoint,
            lambda url, op: None,
            FetchLimits(total_seconds=0.06),
            DNSFixtureResolver(SETTINGS, route),
        )
        with pytest.raises(FetchDenied, match="connection|deadline"):
            gateway.fetch(URL)
        assert len(queries) == 2 and calls == []


def test_actual_oversized_datagram_is_not_an_accepted_prefix(tmp_path: Path) -> None:
    with (
        tls_server(tmp_path, {"/article-a.html": Response()}) as (endpoint, calls),
        dns_server(lambda query, count: answer(query) + b"x" * 600) as (route, queries),
    ):
        gateway = TLSFixtureGateway(
            SETTINGS, endpoint, lambda url, op: None, resolver=DNSFixtureResolver(SETTINGS, route)
        )
        with pytest.raises(FetchDenied, match="response"):
            gateway.fetch(URL)
        assert len(queries) == 1 and calls == []


def test_actual_connected_udp_refuses_other_owned_source_port(tmp_path: Path) -> None:
    with (
        tls_server(tmp_path, {"/article-a.html": Response()}) as (endpoint, calls),
        dns_server(wrong_source=True) as (route, queries),
    ):
        gateway = TLSFixtureGateway(
            SETTINGS,
            endpoint,
            lambda url, op: None,
            FetchLimits(total_seconds=0.05),
            DNSFixtureResolver(SETTINGS, route),
        )
        with pytest.raises(FetchDenied, match="connection"):
            gateway.fetch(URL)
        assert len(queries) == 1 and calls == []


def test_dns_negative_authority_and_fixed_question_are_required() -> None:
    query6 = QUERY[:-4] + struct.pack("!HH", 28, 1)
    valid = answer(query6)
    assert DNSFixtureResolver.decode(valid, 19, 28) == ()
    for malformed in (
        valid[:-1],
        valid + b"x",
        valid[:9] + b"\x00" + valid[10:],
        valid[:12] + QNAME + struct.pack("!HH", 1, 1) + valid[12 + len(QNAME) + 4 :],
    ):
        with pytest.raises(FetchDenied):
            DNSFixtureResolver.decode(malformed, 19, 28)
    raw = answer(QUERY)
    offset = 12 + len(QNAME) + 4
    for pointer in (b"\xc0\x00", b"\xc0" + bytes([offset]), b"\xc0\xff"):
        with pytest.raises(FetchDenied):
            DNSFixtureResolver.decode(raw[:offset] + pointer + raw[offset + len(QNAME) :], 19, 1)

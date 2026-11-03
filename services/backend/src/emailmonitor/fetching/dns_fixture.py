"""Fixed synthetic DNS wire diagnostic, never a general or production resolver.

DNS answers only validate the immutable loopback TLS route. They cannot select a
new connection target. No OS resolver, external DNS, cache, retries or fallback.
"""

import ipaddress
import secrets
import socket
import struct
import time
from dataclasses import dataclass

from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.fetching.safety import FetchDenied

HOST = "synthetic.publisher.example"
QNAME = b"\x09synthetic\x09publisher\x07example\x00"
# One immutable zero-negative-TTL authority record; never used to derive a route.
SOA_DATA = b"\x02ns" + QNAME + b"\x0ahostmaster" + QNAME + struct.pack("!IIIII", 1, 0, 0, 0, 0)
SOA = QNAME + struct.pack("!HHIH", 6, 1, 0, len(SOA_DATA)) + SOA_DATA


@dataclass(frozen=True)
class SyntheticDNSRoute:
    port: int
    address: str = "127.0.0.1"
    hostname: str = HOST

    def __post_init__(self) -> None:
        if (
            self.address != "127.0.0.1"
            or self.hostname != HOST
            or type(self.port) is not int
            or not 1 <= self.port <= 65535
        ):
            raise ValueError("Only the fixed synthetic loopback DNS route is available")


class DNSFixtureResolver:
    def __init__(self, settings: Settings, route: SyntheticDNSRoute) -> None:
        require_fixture(settings)
        if type(route) is not SyntheticDNSRoute:
            raise FetchDenied("dns_fixture_route_denied")
        self._route = route

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchDenied("total_deadline_exceeded")
        return remaining

    @staticmethod
    def decode(raw: bytes, identifier: int, kind: int) -> tuple[str, ...]:
        """Accept only the fixture's complete bounded A/AAAA wire grammar."""
        question = QNAME + struct.pack("!HH", kind, 1)
        if kind not in (1, 28) or not 12 <= len(raw) <= 512:
            raise FetchDenied("dns_response_denied")
        ident, flags, questions, answers, authorities, extra = struct.unpack("!HHHHHH", raw[:12])
        if (
            ident != identifier
            or flags != 0x8400
            or questions != 1
            or answers > 32
            or extra != 0
            or raw[12 : 12 + len(question)] != question
        ):
            raise FetchDenied("dns_response_denied")
        offset = 12 + len(question)
        if answers == 0:
            if kind != 28 or authorities != 1 or raw[offset:] != SOA:
                raise FetchDenied("dns_response_denied")
            return ()
        if authorities != 0:
            raise FetchDenied("dns_response_denied")
        records: list[str] = []
        for _ in range(answers):
            if raw[offset : offset + 2] == b"\xc0\x0c":
                offset += 2  # Only the already validated fixed question may be referenced.
            elif raw[offset : offset + len(QNAME)] == QNAME:
                offset += len(QNAME)
            else:
                raise FetchDenied("dns_response_denied")
            if len(raw) - offset < 10:
                raise FetchDenied("dns_response_denied")
            answer_kind, answer_class, ttl, length = struct.unpack(
                "!HHIH", raw[offset : offset + 10]
            )
            offset += 10
            if (
                answer_kind != kind
                or answer_class != 1
                or ttl > 60
                or length != (4 if kind == 1 else 16)
            ):
                raise FetchDenied("dns_response_denied")
            address = raw[offset : offset + length]
            if len(address) != length:
                raise FetchDenied("dns_response_denied")
            records.append(str(ipaddress.ip_address(address)))
            offset += length
        if offset != len(raw) or len(set(records)) != len(records):
            raise FetchDenied("dns_response_denied")
        return tuple(records)

    def _query(self, kind: int, deadline: float) -> tuple[str, ...]:
        identifier = secrets.randbits(16)
        query = (
            struct.pack("!HHHHHH", identifier, 0, 1, 0, 0, 0) + QNAME + struct.pack("!HH", kind, 1)
        )
        try:
            # Connected UDP filters peer replies, and its target is always this
            # exact test-composed literal. No name-service lookup occurs here.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as stream:
                stream.bind(("127.0.0.1", 0))
                stream.settimeout(self._remaining(deadline))
                stream.connect((self._route.address, self._route.port))
                if stream.getpeername() != (self._route.address, self._route.port):
                    raise FetchDenied("dns_peer_denied")
                stream.send(query)
                stream.settimeout(self._remaining(deadline))
                raw = stream.recv(513)
                self._remaining(deadline)
                result = self.decode(raw, identifier, kind)
                self._remaining(deadline)
                return result
        except OSError as error:
            raise FetchDenied("dns_fixture_connection_denied") from error

    def resolve(self, hostname: str, deadline: float) -> frozenset[str]:
        if hostname != self._route.hostname:
            raise FetchDenied("dns_host_denied")
        addresses = self._query(1, deadline)
        ipv6 = self._query(28, deadline)
        if addresses != ("127.0.0.1",) or ipv6:
            raise FetchDenied("dns_fixture_manifest_denied")
        return frozenset(addresses)

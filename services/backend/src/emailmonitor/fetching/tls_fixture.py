"""Actual TLS I/O to one explicit synthetic loopback server, never a live connector.

This diagnostic transport is test-only. Production public DNS/egress enforcement is
not inferred from the deliberately different, immutable loopback fixture route.
"""

import ipaddress
import re
import socket
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from emailmonitor.config import Settings
from emailmonitor.fetching.fixture import HOSTS, FetchLimits, require_fixture
from emailmonitor.fetching.safety import FetchDenied, SafeURL, classify_url
from emailmonitor.sources.policy import Operation


@dataclass(frozen=True)
class SyntheticEndpoint:
    address: str
    port: int
    ca_file: Path
    paths: frozenset[str]

    def __post_init__(self) -> None:
        if self.address != "127.0.0.1" or type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("Only a fixed IPv4 loopback synthetic endpoint is available")
        if not self.paths or any(
            classify_url(f"https://synthetic.publisher.example{path}", HOSTS).path != path
            for path in self.paths
        ):
            raise ValueError("Explicit canonical synthetic paths are required")


class TLSFixtureGateway:
    """No caller headers, proxies, cookies, DNS lookup, retries or arbitrary target."""

    def __init__(
        self,
        settings: Settings,
        endpoint: SyntheticEndpoint,
        authorize: Callable[[SafeURL, Operation], None],
        limits: FetchLimits | None = None,
    ) -> None:
        require_fixture(settings)
        self._endpoint, self._authorize = endpoint, authorize
        self._limits = limits or FetchLimits()
        self._context = ssl.create_default_context(cafile=str(endpoint.ca_file))
        self._context.minimum_version = ssl.TLSVersion.TLSv1_2

    @staticmethod
    def _remaining(deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchDenied("total_deadline_exceeded")
        return remaining

    def _request(self, url: SafeURL, deadline: float) -> tuple[int, dict[str, str], bytes]:
        endpoint = self._endpoint
        if url.path not in endpoint.paths:
            raise FetchDenied("fixture_route_unavailable")
        if self._context.verify_mode != ssl.CERT_REQUIRED or not self._context.check_hostname:
            raise FetchDenied("tls_verification_required")
        # Literal connect avoids re-resolution between validation and connection.
        # The endpoint is an explicit test composition, not a user-controlled URL.
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
                raw.settimeout(self._remaining(deadline))
                raw.connect((endpoint.address, endpoint.port))
                if ipaddress.ip_address(raw.getpeername()[0]) != ipaddress.ip_address(
                    endpoint.address
                ):
                    raise FetchDenied("connection_peer_denied")
                raw.settimeout(self._remaining(deadline))
                with self._context.wrap_socket(raw, server_hostname=url.host) as stream:
                    if stream.getpeername()[0] != endpoint.address:
                        raise FetchDenied("connection_peer_denied")
                    stream.settimeout(self._remaining(deadline))
                    request = (
                        f"GET {url.path} HTTP/1.1\r\nHost: {url.host}\r\n"
                        "Accept: text/html\r\nConnection: close\r\n\r\n"
                    )
                    stream.sendall(request.encode("ascii"))
                    # Bound every byte read by one absolute deadline, including slow headers.
                    header = bytearray()
                    while not header.endswith(b"\r\n\r\n"):
                        if len(header) >= 8192:
                            raise FetchDenied("headers_limit_exceeded")
                        stream.settimeout(self._remaining(deadline))
                        chunk = stream.recv(1)
                        if not chunk:
                            raise FetchDenied("response_framing_denied")
                        header.extend(chunk)
                    status, headers = self._headers(bytes(header))
                    if "transfer-encoding" in headers:
                        raise FetchDenied("response_framing_denied")
                    length = headers.get("content-length", "")
                    if not re.fullmatch(r"[0-9]{1,8}", length):
                        raise FetchDenied("response_framing_denied")
                    count = int(length)
                    if count > self._limits.max_bytes:
                        raise FetchDenied("body_limit_exceeded")
                    body = bytearray()
                    while len(body) < count:
                        stream.settimeout(self._remaining(deadline))
                        chunk = stream.recv(min(65536, count - len(body)))
                        if not chunk:
                            raise FetchDenied("response_framing_denied")
                        body.extend(chunk)
                    self._remaining(deadline)
                    return status, headers, bytes(body)
        except (OSError, UnicodeError) as error:
            raise FetchDenied("fixture_connection_denied") from error

    @staticmethod
    def _headers(raw: bytes) -> tuple[int, dict[str, str]]:
        try:
            lines = raw.decode("ascii").split("\r\n")
        except UnicodeDecodeError:
            raise FetchDenied("response_framing_denied") from None
        match = re.fullmatch(r"HTTP/1\.[01] ([0-9]{3}) [\x20-\x7e]*", lines[0])
        if match is None or len(lines) > 35:
            raise FetchDenied("response_framing_denied")
        headers: dict[str, str] = {}
        for line in lines[1:-2]:
            name, separator, value = line.partition(":")
            if not separator or not re.fullmatch(r"[A-Za-z0-9-]+", name):
                raise FetchDenied("response_framing_denied")
            name = name.lower()
            if name in headers or any(ord(c) < 32 or ord(c) > 126 for c in value):
                raise FetchDenied("response_framing_denied")
            headers[name] = value.strip()
        return int(match[1]), headers

    def fetch(self, value: str, operation: Operation = Operation.HTML) -> bytes:
        deadline = time.monotonic() + self._limits.total_seconds
        seen: set[str] = set()
        for hop in range(self._limits.max_redirects + 1):
            self._remaining(deadline)
            url = classify_url(value, HOSTS)
            if url.normalized in seen:
                raise FetchDenied("redirect_loop_denied")
            seen.add(url.normalized)
            self._authorize(url, operation)
            status, headers, body = self._request(url, deadline)
            if status in (301, 302, 303, 307, 308):
                if hop == self._limits.max_redirects or not headers.get("location"):
                    raise FetchDenied("redirect_limit_denied")
                value = urljoin(url.normalized, headers["location"])
                continue
            if status != 200:
                raise FetchDenied("source_response_denied")
            if headers.get("content-type", "").split(";", 1)[0].lower() != "text/html":
                raise FetchDenied("content_type_denied")
            if headers.get("content-encoding", "identity") != "identity":
                raise FetchDenied("compressed_fixture_denied")
            self._authorize(url, operation)
            self._remaining(deadline)
            return body
        raise FetchDenied("redirect_limit_denied")

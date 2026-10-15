"""Synthetic closed authoritative DNS and literal dual-stack HTTPS receipts."""

import json
import os
import socket
import ssl
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

from transport_manifest import ENDPOINTS
from transport_routes import escape_evidence, evidence

# Both family answers in each snapshot; every redirect gets fresh A+AAAA queries.
# The first two queries select fixture A; subsequent pairs select fixture B.
QNAME = b"\x09synthetic\x09publisher\x07example\0"
PROVIDER_QNAME = b"\x03api\x08elsevier\x03com\0"


@dataclass
class State:
    mode: str = "normal"
    count: int = 0
    release: threading.Event = field(default_factory=threading.Event, compare=False, repr=False)


def fixture_command(
    frame: object,
    state: State,
    calls: list[dict[str, object]],
    queries: list[dict[str, object]],
    failures: list[str],
    inspect: Callable[[], dict[str, Any]],
) -> tuple[dict[str, object], bool]:
    """Owned control grammar; pure dispatch is independently regression tested."""
    if frame == {"kind": "release"}:
        state.release.set()
        return {"kind": "released"}, False
    if frame == {"kind": "stop"}:
        state.release.set()
        return {
            "kind": "stopped",
            "calls": list(calls),
            "queries": list(queries),
            "failures": list(failures),
        }, True
    if frame == {"kind": "snapshot"}:
        return {
            "kind": "snapshot",
            "calls": list(calls),
            "queries": list(queries),
            "failures": list(failures),
        }, False
    if frame == {"kind": "inspect"}:
        return {"kind": "inspected", "evidence": inspect()}, False
    if (
        type(frame) is not dict
        or set(frame) != {"mode"}
        or frame["mode"]
        not in (
            "normal",
            "redirect",
            "mixed",
            "private",
            "rebinding",
            "wrong_name",
            "slow",
            "provider_redirect",
            "provider_forbidden",
            "provider_throttle",
            "provider_html",
            "provider_duplicate",
            "provider_short",
            "provider_extra",
            "provider_large",
        )
    ):
        raise RuntimeError("Invalid fixture control")
    state.mode, state.count = frame["mode"], 0
    if state.mode == "slow":
        state.release.clear()
    else:
        state.release.set()
    calls.clear()
    queries.clear()
    return {"kind": "configured"}, False


class IPv6Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        super().server_bind()


def main() -> None:
    role = os.environ["EM_TRANSPORT_ROLE"]
    if role not in ("fixture-a", "fixture-b"):
        raise RuntimeError("Invalid fixture role")
    isolation = evidence(role)
    calls: list[dict[str, object]] = []
    queries: list[dict[str, object]] = []
    lock = threading.Lock()
    state = State()
    stop = threading.Event()
    failures: list[str] = []
    observed_sni: dict[int, str | None] = {}
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain("/app/fixture-cert.pem", "/app/fixture-key.pem")
    wrong_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    wrong_context.minimum_version = ssl.TLSVersion.TLSv1_2
    wrong_context.load_cert_chain("/app/wrong-name-cert.pem", "/app/wrong-name-key.pem")

    def record_sni(
        stream: ssl.SSLSocket | ssl.SSLObject, hostname: str | None, initial: object
    ) -> None:
        with lock:
            observed_sni[id(stream)] = hostname
            if state.mode == "wrong_name":
                stream.context = wrong_context

    context.set_servername_callback(record_sni)
    page = Path("/app/synthetic-page.html").read_bytes()
    xml = Path("/app/synthetic-article.xml").read_bytes()
    pii_xml = Path("/app/provider-pii.xml").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            provider = self.headers.get("Host") == "api.elsevier.com"
            content_length = self.headers.get("Content-Length", "0")
            if not content_length.isdecimal() or not 0 <= int(content_length) <= 4096:
                self.send_error(400)
                return
            data = self.rfile.read(int(content_length))
            with lock:
                if len(calls) >= 64:
                    raise RuntimeError("Synthetic HTTP receipt cap exceeded")
                calls.append(
                    {
                        "role": role,
                        "received_monotonic": time.monotonic(),
                        "family": cast(socket.socket, self.connection).family,
                        "path": self.path,
                        "headers": {
                            name: "[synthetic-redacted]"
                            if name.lower() == "x-els-apikey"
                            else value
                            for name, value in self.headers.items()
                        },
                        "method": self.command,
                        "body": data.decode("ascii"),
                        "credential_valid": self.headers.get("X-ELS-APIKey")
                        == "em-synthetic-provider-only",
                        "sni": observed_sni.pop(id(self.connection), None),
                    }
                )
            with lock:
                slow = state.mode == "slow"
            if slow:
                # Fixed bounded synthetic refusal-delay case, not arbitrary source input.
                state.release.wait(timeout=15)
            status, body, location = 200, page, None
            if self.path == "/redirect.html":
                status, body, location = 302, b"", "/tooltip.html"
            elif self.path == "/forbidden.html":
                status, body = 403, b"synthetic forbidden"
            elif self.path == "/off-domain.html":
                status, body, location = 302, b"", "https://denied.fixture.example/"
            elif self.path == "/large.html":
                status, body = 200, b"x" * 32769
            elif self.path != "/tooltip.html":
                status, body = 404, b""
            media = "text/html"
            if provider:
                media = "application/json" if self.command == "PUT" else "text/xml"
                allowed = (
                    self.command == "PUT"
                    and self.path == "/content/search/sciencedirect"
                    or self.command == "GET"
                    and self.path
                    in (
                        "/content/article/doi/10.9999/synthetic.1",
                        "/content/article/doi/10.9999/synthetic.1?view=FULL",
                        "/content/article/pii/S0000000000000002?view=FULL",
                    )
                    and not data
                )
                status = (
                    200
                    if allowed and self.headers.get("X-ELS-APIKey") == "em-synthetic-provider-only"
                    else 403
                )
                body = (
                    json.dumps({"resultsFound": 0, "results": []}, separators=(",", ":")).encode()
                    if self.command == "PUT"
                    else pii_xml
                    if self.path == "/content/article/pii/S0000000000000002?view=FULL"
                    else xml
                )
                if self.command == "PUT":
                    try:
                        query = json.loads(data)
                    except (ValueError, UnicodeError):
                        query = None
                    if query == {
                        "qs": "Controlled provider journey",
                        "display": {"offset": 0, "show": 10, "sortBy": "relevance"},
                    }:
                        body = json.dumps(
                            {
                                "resultsFound": 3,
                                "results": [
                                    {
                                        "doi": "10.9999/synthetic.1",
                                        "title": "Synthetic observations",
                                    },
                                    {
                                        "doi": "10.9999/synthetic.1",
                                        "pii": "S0000000000000001",
                                        "title": "Synthetic observations duplicate",
                                    },
                                    {
                                        "pii": "S0000000000000002",
                                        "title": "Second controlled synthetic document",
                                    },
                                ],
                            },
                            separators=(",", ":"),
                        ).encode()
                if state.mode == "provider_redirect":
                    status, location = 307, "https://denied.fixture.example/"
                elif state.mode == "provider_forbidden":
                    status = 403
                elif state.mode == "provider_throttle":
                    status = 429
                elif state.mode == "provider_html":
                    media, body = "text/html", b"challenge"
                elif state.mode == "provider_large":
                    body = b"x" * 2_097_153
            self.send_response(status)
            self.send_header("Content-Type", media)
            length = len(body)
            if provider and state.mode == "provider_short":
                length += 1
            elif provider and state.mode == "provider_extra":
                length -= 1
            self.send_header("Content-Length", str(length))
            if provider and state.mode == "provider_duplicate":
                self.send_header("Content-Length", str(length))
            if provider and state.mode == "provider_throttle":
                self.send_header("Retry-After", "3")
            if location:
                self.send_header("Location", location)
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def log_message(self, format: str, *args: object) -> None:
            pass

    servers: list[ThreadingHTTPServer] = []
    threads: list[threading.Thread] = []
    for address, cls in zip(ENDPOINTS[role], (ThreadingHTTPServer, IPv6Server), strict=True):
        server = cls((address, 443), Handler)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        servers.append(server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)

    dns: socket.socket | None = None
    if role == "fixture-a":
        dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        dns.bind((ENDPOINTS[role][0], 5353))
        dns.settimeout(0.1)

        def serve_dns() -> None:
            assert dns is not None
            while not stop.is_set():
                try:
                    raw, peer = dns.recvfrom(513)
                except TimeoutError:
                    continue
                except OSError:
                    break
                try:
                    ident, flags, questions, answers, authorities, additional = struct.unpack(
                        "!HHHHHH", raw[:12]
                    )
                    kind, cls = struct.unpack("!HH", raw[-4:])
                    if (
                        (flags, questions, answers, authorities, additional) != (0, 1, 0, 0, 0)
                        or raw[12:-4] not in (QNAME, PROVIDER_QNAME)
                        or kind not in (1, 28)
                        or cls != 1
                    ):
                        raise RuntimeError("Unexpected synthetic DNS query")
                    with lock:
                        if len(queries) >= 128:
                            raise RuntimeError("Synthetic DNS query cap exceeded")
                        state.count += 1
                        mode, count = state.mode, state.count
                        queries.append({"kind": kind, "mode": mode, "count": count})
                    selected = "fixture-b" if mode == "redirect" and count > 2 else "fixture-a"
                    address = ENDPOINTS[selected][0 if kind == 1 else 1]
                    values = [address]
                    if mode == "mixed":
                        values.append("127.0.0.1" if kind == 1 else "fc00::1")
                    elif mode == "private" or (mode == "rebinding" and count > 2):
                        values = ["169.254.169.254" if kind == 1 else "fe80::1"]
                    resources = b""
                    import ipaddress

                    for value in values:
                        data = ipaddress.ip_address(value).packed
                        resources += (
                            b"\xc0\x0c" + struct.pack("!HHIH", kind, 1, 0, len(data)) + data
                        )
                    response = (
                        struct.pack("!HHHHHH", ident, 0x8400, 1, len(values), 0, 0)
                        + raw[12:]
                        + resources
                    )
                    dns.sendto(response, peer)
                except Exception:
                    failures.append("dns_fixture_failed")
                    stop.set()

        thread = threading.Thread(target=serve_dns, daemon=True)
        thread.start()
        threads.append(thread)
    print(json.dumps({"kind": "ready", "evidence": isolation}), flush=True)
    try:
        import sys

        for _ in range(128):
            raw = sys.stdin.buffer.readline(1025)
            if len(raw) > 1024 or not raw.endswith(b"\n"):
                raise RuntimeError("Invalid fixture control frame")
            frame = json.loads(raw)
            if type(frame) is dict and set(frame) == {"kind", "peer"} and frame["kind"] == "escape":
                print(
                    json.dumps(
                        {
                            "kind": "escape",
                            "evidence": escape_evidence(role, frame["peer"]),
                        }
                    ),
                    flush=True,
                )
                continue
            with lock:
                reply, finished = fixture_command(
                    frame, state, calls, queries, failures, lambda: evidence(role)
                )
            print(json.dumps(reply), flush=True)
            if finished:
                return
        raise RuntimeError("Fixture command cap exceeded")
    finally:
        stop.set()
        for server in servers:
            server.shutdown()
            server.server_close()
        if dns is not None:
            dns.close()
        for thread in threads:
            thread.join(2)
            if thread.is_alive():
                raise RuntimeError("Fixture thread cleanup failed")


if __name__ == "__main__":
    main()

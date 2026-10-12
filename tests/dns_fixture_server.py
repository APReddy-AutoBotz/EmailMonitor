"""Owned disposable loopback DNS-wire fixture, not an external name service."""

import ipaddress
import socket
import struct
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from emailmonitor.fetching.dns_fixture import QNAME, SOA, SyntheticDNSRoute


def answer(query: bytes, records: tuple[str, ...] | None = None) -> bytes:
    identifier, flags, questions, a, n, extra = struct.unpack("!HHHHHH", query[:12])
    kind, cls = struct.unpack("!HH", query[-4:])
    if (
        (flags, questions, a, n, extra) != (0, 1, 0, 0, 0)
        or query[12:-4] != QNAME
        or kind not in (1, 28)
        or cls != 1
    ):
        raise ValueError("Unexpected synthetic query")
    if records is None:
        records = ("127.0.0.1",) if kind == 1 else ()
    authority = SOA if not records and kind == 28 else b""
    header = struct.pack("!HHHHHH", identifier, 0x8400, 1, len(records), bool(authority), 0)
    resource = b""
    for record in records:
        data = ipaddress.ip_address(record).packed
        resource += QNAME + struct.pack("!HHIH", kind, 1, 0, len(data)) + data
    return header + query[12:] + resource + authority


@contextmanager
def server(
    reply: Callable[[bytes, int], bytes | None] = lambda query, count: answer(query),
    wrong_source: bool = False,
) -> Iterator[tuple[SyntheticDNSRoute, list[bytes]]]:
    queries: list[bytes] = []
    errors: list[Exception] = []
    stop = threading.Event()
    stream = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stream.bind(("127.0.0.1", 0))
    stream.settimeout(0.05)
    route = SyntheticDNSRoute(stream.getsockname()[1])

    def run() -> None:
        while not stop.is_set():
            try:
                query, peer = stream.recvfrom(513)
            except TimeoutError:
                continue
            except OSError:
                if not stop.is_set():
                    errors.append(RuntimeError("Fixture socket unexpectedly closed"))
                break
            try:
                queries.append(query)
                result = reply(query, len(queries))
                if result is not None:
                    if wrong_source:
                        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:
                            other.bind(("127.0.0.1", 0))
                            other.sendto(result, peer)
                    else:
                        stream.sendto(result, peer)
            except Exception as error:
                errors.append(error)
                break

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield route, queries
    finally:
        stop.set()
        thread.join(timeout=1)
        stream.close()
        if thread.is_alive() or errors:
            raise RuntimeError("Owned DNS fixture cleanup or responder failed")

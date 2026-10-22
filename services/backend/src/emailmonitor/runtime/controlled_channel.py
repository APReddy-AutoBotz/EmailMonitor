"""One owned anonymous socket capability; no imports, images or URLs are selectors."""

import base64
import json
import math
import socket
import struct
import sys
import threading
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from emailmonitor.runtime.controlled_pipes import FramedPipes
from uuid import uuid4

from emailmonitor.config import Settings
from emailmonitor.extraction.sciencedirect import MAX_BYTES, XmlObservation
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.fetching.provider_proxy import exact_binding
from emailmonitor.fetching.resources import HopResources
from emailmonitor.fetching.safety import FetchDenied, classify_url
from emailmonitor.fetching.sciencedirect import AcquiredResponse, ProviderBoundary, ProviderRequest
from emailmonitor.parsing.xml_protocol import XmlExpectation
from emailmonitor.runtime.controlled_diagnostics import bucket_elapsed
from emailmonitor.sources.provider_documents import QUERY
from emailmonitor.sources.sciencedirect import ArticleIdentifier, SearchRequest

MAX_FRAME = 4 * ((MAX_BYTES + 2) // 3) + 65536
MAX_CALLBACKS = 128
SESSION_COMMANDS = 64


def expectations() -> tuple[XmlExpectation, ...]:
    """Immutable authored identities; never populate this from worker or SQL input."""
    return (
        XmlExpectation(
            requested_identifier=ArticleIdentifier(kind="doi", value="10.9999/synthetic.1"),
            content_digest="ecffa55455f07f6205a1bb2ab6bc30f7e2528845eae757a17c32d88c5fa4ec30",
            source_profile="article_retrieval_response",
        ),
        XmlExpectation(
            requested_identifier=ArticleIdentifier(kind="pii", value="S0000000000000002"),
            content_digest="183c0dd3f9a17199ed3ce5fd4de7b0eccfb912d636c7a84395077d5c29bb3aa8",
            source_profile="xocs_document",
        ),
    )


def require_request(request: ProviderRequest) -> None:
    checked = ProviderRequest.model_validate(request.model_dump())
    allowed = (
        ProviderRequest(search=SearchRequest(query=QUERY, show=10)),
        *(ProviderRequest(article=e.requested_identifier, view="FULL") for e in expectations()),
    )
    if checked not in allowed:
        raise FetchDenied("controlled_provider_route_denied")


def require_expectation(expected: XmlExpectation, data: bytes) -> None:
    checked = XmlExpectation.model_validate(expected.model_dump())
    if checked not in expectations():
        raise FetchDenied("controlled_parser_expectation_denied")
    checked.check_bytes(data)


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("Invalid controlled frame")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("Invalid controlled number")


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Invalid controlled number")
    return number


class FramedSocket:
    def __init__(self, connection: socket.socket) -> None:
        self.connection = connection
        self.poisoned = False

    def _remaining(self, deadline: float) -> None:
        if self.poisoned or not math.isfinite(deadline) or deadline <= time.monotonic():
            raise RuntimeError("Controlled channel unavailable")
        self.connection.settimeout(deadline - time.monotonic())

    def send(self, value: dict[str, Any], deadline: float) -> None:
        try:
            raw = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("ascii")
            if not 1 <= len(raw) <= MAX_FRAME:
                raise ValueError
            self._remaining(deadline)
            self.connection.sendall(struct.pack("!I", len(raw)) + raw)
        except Exception:
            self.poisoned = True
            raise RuntimeError("Controlled channel failed") from None

    def _read(self, length: int, deadline: float) -> bytes:
        output = bytearray()
        while len(output) < length:
            self._remaining(deadline)
            chunk = self.connection.recv(min(65536, length - len(output)))
            if not chunk:
                raise ValueError
            output.extend(chunk)
        return bytes(output)

    def receive(self, deadline: float) -> dict[str, Any]:
        try:
            length = struct.unpack("!I", self._read(4, deadline))[0]
            if not 1 <= length <= MAX_FRAME:
                raise ValueError
            value = json.loads(
                self._read(length, deadline),
                object_pairs_hook=_pairs,
                parse_constant=_constant,
                parse_float=_float,
            )
            if type(value) is not dict:
                raise ValueError
            return value
        except Exception:
            self.poisoned = True
            raise RuntimeError("Controlled channel failed") from None

    def close(self) -> None:
        self.poisoned = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()


class ControlledChannel:
    def __init__(self, connection: socket.socket) -> None:
        self.pipe: FramedSocket | FramedPipes = FramedSocket(connection)
        self._lock = threading.Lock()
        self._commands = 0

    @classmethod
    def from_fd(cls, fd: int) -> "ControlledChannel":
        if type(fd) is not int or fd < 3:
            raise ValueError("Dedicated controlled descriptor required")
        connection = socket.socket(fileno=fd)
        connection.set_inheritable(False)
        if connection.family != socket.AF_UNIX or connection.type != socket.SOCK_STREAM:
            connection.close()
            raise ValueError("Anonymous socket capability required")
        if connection.getsockname() or connection.getpeername():
            connection.close()
            raise ValueError("Anonymous socket capability required")
        return cls(connection)

    @classmethod
    def from_pipes(cls, incoming: int, outgoing: int) -> "ControlledChannel":
        from emailmonitor.runtime.controlled_pipes import FramedPipes

        channel = cls.__new__(cls)
        channel.pipe = FramedPipes(incoming, outgoing)
        channel._lock = threading.Lock()
        channel._commands = 0
        return channel

    def _start(self) -> str:
        if not self._lock.acquire(blocking=False):
            self.pipe.poisoned = True
            raise RuntimeError("Controlled channel already active")
        self._commands += 1
        if self.pipe.poisoned or self._commands > SESSION_COMMANDS:
            self.pipe.poisoned = True
            self._lock.release()
            raise RuntimeError("Controlled session exhausted")
        return uuid4().hex

    def acquire(self, boundary: ProviderBoundary, *, resources: HopResources) -> AcquiredResponse:
        require_request(boundary.request)
        boundary.check_current()
        identifier = self._start()
        ticket: object | None = None
        admitted = finished = False
        deadline = min(boundary.binding.deadline, time.monotonic() + 20)
        # Observational initial budget, repeated unchanged; never a deadline input.
        initial_remaining = bucket_elapsed(max(0.0, boundary.binding.deadline - time.monotonic()))
        try:
            self.pipe.send(
                {
                    "kind": "acquire",
                    "id": identifier,
                    "request": boundary.request.model_dump(mode="json"),
                    "binding": boundary.binding.model_dump(mode="json"),
                },
                deadline,
            )
            for sequence in range(MAX_CALLBACKS):
                frame = self.pipe.receive(deadline)
                if frame.get("id") != identifier:
                    raise ValueError
                kind = frame.get("kind")
                if kind == "acquired":
                    if (
                        set(frame) != {"kind", "id", "body", "digest"}
                        or ticket is not None
                        or not (admitted and finished)
                    ):
                        raise ValueError
                    data = base64.b64decode(frame["body"], validate=True)
                    if len(data) > 65536:
                        raise ValueError
                    result = AcquiredResponse(
                        boundary.request, boundary.binding, data, frame["digest"]
                    )
                    boundary.require_response(result)
                    return result
                if (
                    set(frame) != {"kind", "id", "sequence", "binding", "arguments"}
                    or frame["sequence"] != sequence
                    or type(frame["sequence"]) is not int
                    or not exact_binding(frame["binding"], boundary.binding)
                ):
                    raise ValueError
                arguments = frame["arguments"]
                callback_started = time.monotonic()
                boundary.check_current()
                if kind == "current" and arguments == {}:
                    pass
                elif (
                    kind == "resource_acquire"
                    and not admitted
                    and ticket is None
                    and arguments
                    == {
                        "url": boundary.request.url,
                        "operation": boundary.request.operation.value,
                        "deadline": boundary.binding.deadline,
                    }
                ):
                    ticket = resources.acquire(
                        classify_url(boundary.request.url, frozenset({"api.elsevier.com"})),
                        boundary.request.operation,
                        boundary.binding.deadline,
                    )
                    if ticket is None:
                        raise ValueError
                    admitted = True
                elif (
                    kind == "resource_finish"
                    and ticket is not None
                    and type(arguments) is dict
                    and set(arguments) == {"status", "retry_after"}
                ):
                    status, retry = arguments["status"], arguments["retry_after"]
                    if (
                        not (status is None or type(status) is int and 100 <= status <= 599)
                        or type(retry) is not str
                        or len(retry) > 11
                    ):
                        raise ValueError
                    owned, ticket = ticket, None
                    resources.finish(owned, status, retry)
                    finished = True
                else:
                    raise ValueError
                self.pipe.send(
                    {
                        "kind": "callback",
                        "id": identifier,
                        "sequence": sequence,
                        "ok": True,
                        "elapsed_bucket": bucket_elapsed(time.monotonic() - callback_started).value,
                        "initial_acquire_remaining_bucket": initial_remaining.value,
                    },
                    deadline,
                )
            raise ValueError
        except Exception:
            self.pipe.poisoned = True
            raise FetchDenied("controlled_channel_failed") from None
        finally:
            try:
                if ticket is not None:
                    original = sys.exception()
                    try:
                        resources.finish(ticket, None, "")
                    except Exception:
                        if original is None:
                            raise FetchDenied("controlled_resource_cleanup_failed") from None
                        original.add_note("Controlled resource cleanup failed")
            finally:
                self._lock.release()

    def parse(self, settings: Settings, data: bytes, *, expected: XmlExpectation) -> XmlObservation:
        require_fixture(settings)
        require_expectation(expected, data)
        identifier = self._start()
        deadline = time.monotonic() + 120
        try:
            self.pipe.send(
                {
                    "kind": "parse",
                    "id": identifier,
                    "expected": expected.model_dump(mode="json"),
                    "body": base64.b64encode(data).decode("ascii"),
                },
                deadline,
            )
            frame = self.pipe.receive(deadline)
            if (
                set(frame) != {"kind", "id", "observation"}
                or frame["kind"] != "parsed"
                or frame["id"] != identifier
            ):
                raise ValueError
            observed = XmlObservation.model_validate(frame["observation"])
            expected.check_observation(observed)
            return observed
        except Exception:
            self.pipe.poisoned = True
            raise FetchDenied("controlled_channel_failed") from None
        finally:
            self._lock.release()

    def close(self) -> None:
        self.pipe.close()

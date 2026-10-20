"""Offline socketpair contracts, without SQL, network, or container infrastructure."""

import base64
import hashlib
import socket
import struct
import threading
import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from emailmonitor.fetching.provider_proxy import scope_fields
from emailmonitor.fetching.safety import FetchDenied, SafeURL
from emailmonitor.fetching.sciencedirect import (
    CredentialReference,
    ProviderBinding,
    ProviderBoundary,
    ProviderRequest,
)
from emailmonitor.runtime.controlled_channel import (
    MAX_FRAME,
    ControlledChannel,
    FramedSocket,
    expectations,
    require_request,
)
from emailmonitor.runtime.controlled_launcher import serve_request
from emailmonitor.sources.policy import Operation
from emailmonitor.sources.provider_documents import QUERY
from emailmonitor.sources.sciencedirect import SearchRequest

IMAGE = "sha256:" + "a" * 64
BODY = b'{"resultsFound":0,"results":[]}'


def boundary() -> ProviderBoundary:
    request = ProviderRequest(search=SearchRequest(query=QUERY, show=10))
    binding = ProviderBinding(
        organization=UUID(int=1),
        job=UUID(int=2),
        item=UUID(int=3),
        lease=UUID(int=4),
        generation=1,
        deletion_generation=1,
        policy_version=1,
        policy_revision=1,
        discovery_revision=1,
        request_fingerprint=request.fingerprint,
        credential=CredentialReference(organization=UUID(int=1), reference=UUID(int=5), revision=1),
        deadline=time.monotonic() + 10,
    )
    return ProviderBoundary(request, binding, lambda: binding)


class Gateway:
    def __init__(self, bound: ProviderBoundary) -> None:
        self.poisoned = False
        self.sent: list[dict[str, object]] = []
        scope = scope_fields(bound.planner.scope)
        self.frames: Iterator[dict[str, Any]] = iter(
            [
                {"kind": "provider_current", "binding": bound.binding.model_dump(mode="json")},
                {
                    "kind": "resource_acquire",
                    "id": str(UUID(int=9)),
                    "scope": scope,
                    "url": bound.request.url,
                },
                {
                    "kind": "resource_finish",
                    "id": str(UUID(int=9)),
                    "scope": scope,
                    "status": 200,
                    "retry_after": "",
                },
                {
                    "kind": "provider_result",
                    "status": "ok",
                    "request": bound.request.model_dump(mode="json"),
                    "binding": bound.binding.model_dump(mode="json"),
                    "body": base64.b64encode(BODY).decode(),
                    "digest": hashlib.sha256(BODY).hexdigest(),
                    "peers": [["8.8.8.3", 443, "api.elsevier.com"]],
                },
            ]
        )

    def send(self, value: dict[str, object], deadline: float) -> None:
        self.sent.append(value)

    def receive(self, deadline: float) -> dict[str, Any]:
        return next(self.frames)


class Resources:
    def __init__(self) -> None:
        self.ticket = object()
        self.events: list[object] = []

    def acquire(self, url: SafeURL, operation: Operation, deadline: float) -> object:
        self.events.append("acquire")
        return self.ticket

    def finish(self, ticket: object, status: int | None, retry_after: str) -> None:
        assert ticket is self.ticket
        self.events.append((status, retry_after))


def test_acquisition_roundtrips_current_authority_and_worker_owned_ticket() -> None:
    left, right = socket.socketpair()
    client, server = ControlledChannel(left), FramedSocket(right)
    bound = boundary()
    gateway, resources = Gateway(bound), Resources()
    failures: list[Exception] = []

    def host() -> None:
        try:
            serve_request(server, gateway, IMAGE)
        except Exception as error:
            failures.append(error)

    thread = threading.Thread(target=host)
    thread.start()
    try:
        assert client.acquire(bound, resources=resources).body == BODY
        thread.join(2)
        assert not thread.is_alive() and not failures
        assert resources.events == ["acquire", (200, "")]
        assert gateway.sent[0]["kind"] == "provider"
        assert not gateway.poisoned
    finally:
        client.close()
        server.close()
        thread.join(2)


@pytest.mark.parametrize(
    "raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b"[]", b'{"a":1}{}']
)
def test_strict_frames_poison_duplicate_nonfinite_or_nonobject_json(raw: bytes) -> None:
    left, right = socket.socketpair()
    receiver = FramedSocket(left)
    try:
        right.sendall(struct.pack("!I", len(raw)) + raw)
        with pytest.raises(RuntimeError, match="Controlled channel failed"):
            receiver.receive(time.monotonic() + 1)
        assert receiver.poisoned
    finally:
        receiver.close()
        right.close()


def test_oversize_header_rejected_without_allocating_body() -> None:
    left, right = socket.socketpair()
    receiver = FramedSocket(left)
    try:
        right.sendall(struct.pack("!I", MAX_FRAME + 1))
        with pytest.raises(RuntimeError):
            receiver.receive(time.monotonic() + 1)
        assert receiver.poisoned
    finally:
        receiver.close()
        right.close()


def test_only_three_exact_requests_are_admitted() -> None:
    require_request(boundary().request)
    for expected in expectations():
        require_request(ProviderRequest(article=expected.requested_identifier, view="FULL"))
        with pytest.raises(FetchDenied):
            require_request(ProviderRequest(article=expected.requested_identifier))
    with pytest.raises(FetchDenied):
        require_request(ProviderRequest(search=SearchRequest(query=QUERY, show=25)))


def test_unregistered_request_rejected_before_gateway_bytes() -> None:
    left, right = socket.socketpair()
    client, server = FramedSocket(left), FramedSocket(right)
    bound = boundary()
    gateway = Gateway(bound)
    try:
        client.send(
            {
                "kind": "acquire",
                "id": "b" * 32,
                "request": ProviderRequest(search=SearchRequest(query="not registered")).model_dump(
                    mode="json"
                ),
                "binding": bound.binding.model_dump(mode="json"),
            },
            time.monotonic() + 1,
        )
        with pytest.raises(RuntimeError):
            serve_request(server, gateway, IMAGE)
        assert not gateway.sent and server.poisoned and gateway.poisoned
    finally:
        client.close()
        server.close()


def test_session_exhaustion_does_not_restart_or_reopen_channel() -> None:
    left, right = socket.socketpair()
    channel = ControlledChannel(left)
    channel._commands = 64
    try:
        with pytest.raises(RuntimeError, match="exhausted"):
            channel.acquire(boundary(), resources=Resources())
        assert channel.pipe.poisoned
    finally:
        channel.close()
        right.close()


def test_parser_uses_supervisor_image_and_registered_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    from emailmonitor.config import Settings
    from emailmonitor.extraction.sciencedirect import XmlObservation, parse_article
    from emailmonitor.parsing.xml_protocol import XmlExpectation
    from emailmonitor.runtime import controlled_launcher

    expected = expectations()[0]
    # The immutable digest must match repository-authored fixture material.
    root = Path(__file__).resolve().parents[3] / "fixtures/xml"
    data = next(
        path.read_bytes()
        for path in root.glob("*.xml")
        if hashlib.sha256(path.read_bytes()).hexdigest() == expected.content_digest
    )
    calls: list[str] = []

    def parser(
        settings: Settings, body: bytes, *, expected: XmlExpectation, image_id: str
    ) -> XmlObservation:
        calls.append(image_id)
        return parse_article(body, expected.requested_identifier)

    monkeypatch.setattr(controlled_launcher, "parse_pinned", parser)
    left, right = socket.socketpair()
    client, server = ControlledChannel(left), FramedSocket(right)
    gateway = Gateway(boundary())
    thread = threading.Thread(target=serve_request, args=(server, gateway, IMAGE))
    thread.start()
    try:
        result = client.parse(
            Settings(environment="test", fixture_mode=True), data, expected=expected
        )
        assert result.content_digest == expected.content_digest
        thread.join(2)
        assert not thread.is_alive() and calls == [IMAGE] and not gateway.sent
    finally:
        client.close()
        server.close()
        thread.join(2)


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_sequence",
        "out_of_order",
        "binding",
        "binding_bool",
        "binding_float",
        "id",
        "operation",
        "deadline",
        "extra",
        "finish_without_ticket",
        "unknown",
        "eof",
        "truncated",
        "unsolicited_result",
        "digest",
        "duplicate_acquire",
        "revoked",
        "revoked_result",
        "cleanup_failure",
    ],
)
def test_hostile_callback_exchanges_poison_and_release_owned_resource(fault: str) -> None:
    left, right = socket.socketpair()
    client, host = ControlledChannel(left), FramedSocket(right)
    bound = boundary()
    resources = Resources()
    thread_errors: list[BaseException] = []

    def attack() -> None:
        try:
            request = host.receive(time.monotonic() + 2)
            identifier = request["id"]
            deadline = time.monotonic() + 2

            def callback(kind: str, sequence: int, arguments: dict[str, object]) -> dict[str, Any]:
                return {
                    "kind": kind,
                    "id": identifier,
                    "sequence": sequence,
                    "binding": bound.binding.model_dump(mode="json"),
                    "arguments": arguments,
                }

            arguments: dict[str, object] = {
                "url": bound.request.url,
                "operation": bound.request.operation.value,
                "deadline": bound.binding.deadline,
            }
            # Obtain exactly one worker-owned ticket first, except the orphan finish case.
            if fault != "finish_without_ticket":
                host.send(callback("resource_acquire", 0, arguments), deadline)
                assert host.receive(deadline)["ok"] is True
            frame = callback("current", 1, {})
            if fault == "duplicate_sequence":
                frame["sequence"] = 0
            elif fault == "out_of_order":
                frame["sequence"] = 2
            elif fault == "binding":
                frame["binding"]["policy_revision"] = 2
            elif fault in ("binding_bool", "binding_float"):
                frame["binding"]["generation"] = True if fault == "binding_bool" else 1.0
            elif fault == "id":
                frame["id"] = "c" * 32
            elif fault in ("operation", "deadline", "duplicate_acquire"):
                if fault == "operation":
                    arguments["operation"] = "xml"
                if fault == "deadline":
                    arguments["deadline"] = bound.binding.deadline + 1
                frame = callback("resource_acquire", 1, arguments)
            elif fault == "extra":
                frame["extra"] = "no"
            elif fault == "finish_without_ticket":
                frame = callback("resource_finish", 0, {"status": 200, "retry_after": ""})
            elif fault in ("unknown", "cleanup_failure"):
                frame["kind"] = "unknown"
                if fault == "cleanup_failure":

                    def fail(ticket: object, status: int | None, retry_after: str) -> None:
                        raise RuntimeError("private cleanup content must not escape")

                    resources.finish = fail  # type: ignore[method-assign]
            elif fault == "eof":
                host.close()
                return
            elif fault == "truncated":
                right.sendall(struct.pack("!I", 100) + b"{")
                host.close()
                return
            elif fault == "unsolicited_result":
                frame = {
                    "kind": "acquired",
                    "id": identifier,
                    "body": base64.b64encode(BODY).decode(),
                    "digest": hashlib.sha256(BODY).hexdigest(),
                }
            elif fault in ("digest", "revoked_result"):
                if fault == "revoked_result":
                    original_finish = resources.finish

                    def revoke_after_finish(
                        ticket: object, status: int | None, retry_after: str
                    ) -> None:
                        original_finish(ticket, status, retry_after)

                        def deny() -> ProviderBinding:
                            raise FetchDenied("current_authority_revoked")

                        bound._current = deny

                    resources.finish = revoke_after_finish  # type: ignore[method-assign]
                host.send(
                    callback("resource_finish", 1, {"status": 200, "retry_after": ""}), deadline
                )
                assert host.receive(deadline)["ok"] is True
                frame = {
                    "kind": "acquired",
                    "id": identifier,
                    "body": base64.b64encode(BODY).decode(),
                    "digest": "a" * 64 if fault == "digest" else hashlib.sha256(BODY).hexdigest(),
                }
            elif fault == "revoked":

                def denied() -> ProviderBinding:
                    raise FetchDenied("current_authority_revoked")

                bound._current = denied
            host.send(frame, deadline)
        except BaseException as error:
            thread_errors.append(error)

    thread = threading.Thread(target=attack)
    thread.start()
    try:
        with pytest.raises(FetchDenied, match="controlled_channel_failed") as error:
            client.acquire(bound, resources=resources)
        assert client.pipe.poisoned
        if fault == "cleanup_failure":
            assert error.value.__notes__ == ["Controlled resource cleanup failed"]
        elif fault == "finish_without_ticket":
            assert resources.events == []
        elif fault in ("digest", "revoked_result"):
            assert resources.events == ["acquire", (200, "")]
        else:
            assert resources.events == ["acquire", (None, "")]
        thread.join(3)
        assert not thread.is_alive() and not thread_errors
    finally:
        client.close()
        host.close()
        thread.join(3)


def test_revocation_before_acquisition_never_sends_request() -> None:
    left, right = socket.socketpair()
    client = ControlledChannel(left)
    bound, resources = boundary(), Resources()

    def denied() -> ProviderBinding:
        raise FetchDenied("current_authority_revoked")

    bound._current = denied
    try:
        with pytest.raises(FetchDenied, match="revoked"):
            client.acquire(bound, resources=resources)
        right.setblocking(False)
        with pytest.raises(BlockingIOError):
            right.recv(1)
        assert not resources.events
    finally:
        client.close()
        right.close()

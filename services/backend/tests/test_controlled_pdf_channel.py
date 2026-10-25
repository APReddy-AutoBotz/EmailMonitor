"""Closed PDF capability composition; actual parser coverage is explicitly opt-in."""

import base64
import os
import socket
import threading
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from emailmonitor.config import Settings
from emailmonitor.extraction.pdf import PdfObservation, parse_pdf
from emailmonitor.extraction.pdf_fixture import DIGESTS, pdf_bytes
from emailmonitor.fetching.provider_proxy import GatewayPipe
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.parsing.pdf_protocol import PdfExpectation
from emailmonitor.runtime import controlled_launcher
from emailmonitor.runtime.controlled_channel import ControlledChannel, FramedSocket
from emailmonitor.runtime.controlled_launcher import serve_request

SETTINGS = Settings(environment="test", fixture_mode=True)
IMAGE = "sha256:" + "a" * 64


@pytest.mark.parametrize("name", sorted(DIGESTS))
@pytest.mark.parametrize("actual", [False, True])
def test_pdf_byte_capability_uses_supervisor_image_without_gateway(
    monkeypatch: pytest.MonkeyPatch, name: str, actual: bool
) -> None:
    image = IMAGE
    calls: list[str] = []
    if actual:
        image = os.environ.get("EM_TEST_PDF_IMAGE_ID") or os.environ.get(
            "EM_EXPECTED_XML_IMAGE_ID", ""
        )
        if not image:
            if os.environ.get("EM_REQUIRE_XML_ISOLATION") == "true":
                pytest.fail("Required pinned parser image unavailable")
            pytest.skip("Actual pinned parser image required")
    else:

        def parser(
            settings: Settings, data: bytes, *, expected: PdfExpectation, image_id: str
        ) -> PdfObservation:
            calls.append(image_id)
            expected.check_bytes(data)
            return parse_pdf(settings, expected.url, data)

        monkeypatch.setattr(controlled_launcher, "parse_pdf_pinned", parser)
    expected = PdfExpectation(
        url="https://synthetic.publisher.example/" + name, content_digest=DIGESTS[name]
    )
    left, right = socket.socketpair()
    client, server = ControlledChannel(left), FramedSocket(right)
    gateway = Mock(spec=GatewayPipe)
    errors: list[str] = []

    def host() -> None:
        try:
            serve_request(server, gateway, image)
        except Exception as error:
            errors.append(type(error).__name__)
            server.close()

    thread = threading.Thread(target=host)
    thread.start()
    try:
        observed = client.parse_pdf(SETTINGS, pdf_bytes(name), expected=expected)
        expected.check_observation(observed)
        assert observed == parse_pdf(SETTINGS, expected.url, pdf_bytes(name))
        thread.join(2)
        assert not thread.is_alive() and errors == []
        assert actual or calls == [IMAGE]
        assert gateway.mock_calls == []
    finally:
        client.close()
        server.close()
        thread.join(2)


@pytest.mark.parametrize(
    "mutation", ["image", "command", "tenant", "extra", "unknown", "digest", "body", "kind"]
)
def test_supervisor_rejects_unregistered_pdf_requests_before_parser(
    monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    frame: dict[str, Any] = {
        "kind": "parse_pdf",
        "id": "b" * 32,
        "expected": PdfExpectation(
            url="https://synthetic.publisher.example/article-a.pdf",
            content_digest=DIGESTS["article-a.pdf"],
        ).model_dump(mode="json"),
        "body": base64.b64encode(pdf_bytes("article-a.pdf")).decode(),
    }
    if mutation in {"image", "command", "tenant", "extra"}:
        frame[mutation] = "not-a-selector"
    elif mutation == "unknown":
        frame["expected"]["url"] = "https://synthetic.publisher.example/unknown.pdf"
    elif mutation == "digest":
        frame["expected"]["content_digest"] = "0" * 64
    elif mutation == "body":
        frame["body"] = base64.b64encode(b"different").decode()
    else:
        frame["kind"] = "parse"
    parser = Mock(side_effect=AssertionError("Parser must not be reached"))
    monkeypatch.setattr(controlled_launcher, "parse_pdf_pinned", parser)
    monkeypatch.setattr(controlled_launcher, "parse_pinned", parser)
    pipe = SimpleNamespace(receive=lambda deadline: frame, poisoned=False)
    gateway = Mock(spec=GatewayPipe)
    with pytest.raises(RuntimeError, match="Controlled capability failed"):
        serve_request(cast(FramedSocket, pipe), gateway, IMAGE)
    parser.assert_not_called()
    assert pipe.poisoned and gateway.poisoned
    assert gateway.mock_calls == []


@pytest.mark.parametrize("mutation", ["id", "kind", "observation"])
def test_pdf_client_rejects_cross_request_or_cross_profile_response(mutation: str) -> None:
    expected = PdfExpectation(
        url="https://synthetic.publisher.example/article-a.pdf",
        content_digest=DIGESTS["article-a.pdf"],
    )
    left, right = socket.socketpair()
    client, server = ControlledChannel(left), FramedSocket(right)

    def respond() -> None:
        import time

        request = server.receive(time.monotonic() + 2)
        name = "article-b.pdf" if mutation == "observation" else "article-a.pdf"
        observation = parse_pdf(
            SETTINGS, "https://synthetic.publisher.example/" + name, pdf_bytes(name)
        )
        server.send(
            {
                "kind": "parsed" if mutation == "kind" else "pdf_parsed",
                "id": "0" * 32 if mutation == "id" else request["id"],
                "observation": observation.model_dump(mode="json"),
            },
            time.monotonic() + 2,
        )

    thread = threading.Thread(target=respond)
    thread.start()
    try:
        with pytest.raises(FetchDenied, match="controlled_channel_failed"):
            client.parse_pdf(SETTINGS, pdf_bytes("article-a.pdf"), expected=expected)
        assert client.pipe.poisoned
        thread.join(2)
        assert not thread.is_alive()
    finally:
        client.close()
        server.close()
        thread.join(2)

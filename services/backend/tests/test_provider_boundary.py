"""Controlled bytes test reusable provider checks, never acquire from a publisher."""

import hashlib
import io
import json
import os
import socket
from dataclasses import replace
from typing import Any
from uuid import UUID
from xml.etree import ElementTree as ET

import pytest
from emailmonitor.config import Settings
from emailmonitor.extraction import provider_xml
from emailmonitor.extraction.sciencedirect import NS, XmlObservation
from emailmonitor.extraction.xml_retained import XML_IDENTIFIER, retain_xml
from emailmonitor.extraction.xml_service import fixture_bytes
from emailmonitor.fetching.safety import FetchDenied, IsolationUnavailable
from emailmonitor.fetching.sciencedirect import (
    CredentialReference,
    ProviderBinding,
    ProviderBoundary,
    ProviderRequest,
    ProviderResponse,
    acquire_live,
)
from emailmonitor.parsing.xml_channel import decode_output
from emailmonitor.parsing.xml_protocol import XmlExpectation, encode_input, parse_input, read_input
from emailmonitor.sources.policy import PolicyProposal
from emailmonitor.sources.sciencedirect import SearchRequest, normalize_identifier
from pydantic import ValidationError
from test_sciencedirect_adapter import payload, row
from test_source_foundation import policy_body
from test_xml_pipeline import retained

SETTINGS = Settings(environment="test", fixture_mode=True)


def request(*, article: bool = False) -> ProviderRequest:
    return (
        ProviderRequest(article=normalize_identifier("10.9999/synthetic.2"))
        if article
        else ProviderRequest(search=SearchRequest(query="synthetic", show=10))
    )


def binding(req: ProviderRequest | None = None) -> ProviderBinding:
    return ProviderBinding(
        organization=UUID(int=1),
        job=UUID(int=2),
        item=UUID(int=3),
        lease=UUID(int=4),
        generation=1,
        deletion_generation=1,
        policy_version=1,
        policy_revision=1,
        discovery_revision=1,
        request_fingerprint=(req or request()).fingerprint,
        credential=CredentialReference(organization=UUID(int=1), reference=UUID(int=5), revision=1),
        deadline=60.0,
    )


def boundary(req: ProviderRequest | None = None) -> ProviderBoundary:
    req = req or request()
    scope = binding(req)
    return ProviderBoundary(req, scope, lambda: scope, lambda: 1.0)


def response(req: ProviderRequest | None = None, data: bytes | None = None) -> ProviderResponse:
    req = req or request()
    data = data if data is not None else payload([row()])
    return ProviderResponse(req.url, 200, req.plan().media_type, (data,), binding(req), len(data))


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("Provider prerequisite must not use network")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def test_canonical_requests_share_hop_planner_and_preserve_query() -> None:
    search = ProviderRequest(search=SearchRequest(query='  "Case" AND topic  ', offset=10, show=10))
    plan = search.plan()
    assert (plan.method, plan.path, plan.media_type) == (
        "PUT",
        "/content/search/sciencedirect",
        "application/json",
    )
    assert json.loads(plan.body)["qs"] == '  "Case" AND topic  '
    assert not plan.execution_enabled
    gate = boundary(search)
    safe = gate.planner.authorize_url(search.url)
    hop = gate.planner.snapshot(safe, ("8.8.8.8",))
    gate.planner.before_connect(hop)
    gate.planner.before_release(hop)
    with pytest.raises(FetchDenied, match="redirect_limit"):
        gate.planner.redirect(hop, search.url)
    article = request(article=True)
    assert article.plan().method == "GET" and article.plan().body == b""
    assert article.url == "https://api.elsevier.com/content/article/doi/10.9999/synthetic.2"
    assert article.fingerprint != search.fingerprint


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"search": {"query": "x"}, "article": {"kind": "doi", "value": "10.9999/x"}},
        {"search": {"query": "x"}, "method": "GET"},
        {"search": {"query": "x"}, "path": "/anything"},
        {"search": {"query": "x"}, "media_type": "text/html"},
        {"search": {"query": "x"}, "body": "arbitrary"},
        {"search": {"query": "x"}, "headers": {"Authorization": "not-accepted"}},
        {"search": {"query": "x"}, "origin": "https://other.example"},
        {"search": {"query": "x" * 251}},
        {"article": {"kind": "pii", "value": "10.9999/x"}},
        {"article": {"kind": "doi", "value": "10.9999/UPPER"}},
    ],
)
def test_no_arbitrary_request_authority(document: dict[str, object]) -> None:
    with pytest.raises((ValidationError, FetchDenied)):
        ProviderRequest.model_validate_json(json.dumps(document))


def test_percent_encoded_identifier_remains_shared_gateway_refusal() -> None:
    req = ProviderRequest(article=normalize_identifier("10.9999/example(2)"))
    with pytest.raises(FetchDenied, match="path_denied"):
        boundary(req)


def test_default_authority_and_live_acquisition_are_unavailable() -> None:
    with pytest.raises(IsolationUnavailable, match="live_admission_unimplemented"):
        ProviderBoundary(request(), binding(), clock=lambda: 1.0)
    with pytest.raises(IsolationUnavailable, match="protected_transport_unimplemented"):
        acquire_live(boundary())


@pytest.mark.parametrize(
    "field,value",
    [
        ("organization", UUID(int=100)),
        ("job", UUID(int=100)),
        ("item", UUID(int=100)),
        ("lease", UUID(int=100)),
        ("generation", 2),
        ("deletion_generation", 2),
        ("policy_version", 2),
        ("policy_revision", 2),
        ("discovery_revision", 2),
        ("request_fingerprint", "a" * 64),
        ("source", "synthetic-publisher"),
        ("purpose", "other"),
        ("deadline", 59.0),
        (
            "credential",
            CredentialReference(organization=UUID(int=1), reference=UUID(int=6), revision=1),
        ),
        (
            "credential",
            CredentialReference(organization=UUID(int=1), reference=UUID(int=5), revision=2),
        ),
    ],
)
def test_every_changed_authority_field_refuses_before_response_read(field: str, value: Any) -> None:
    original = binding()
    current = original
    gate = ProviderBoundary(request(), original, lambda: current, lambda: 1.0)
    current = original.model_copy(update={field: value})
    consumed = False

    def chunks() -> Any:
        nonlocal consumed
        consumed = True
        yield b"must not read"

    with pytest.raises(FetchDenied, match="current_binding"):
        gate.read_response(replace(response(), chunks=chunks()))
    assert not consumed


def test_credential_reference_has_exact_tenant_source_origin_and_no_plaintext() -> None:
    document = binding().model_dump(mode="json")
    credential = document["credential"]
    for field, value in (
        ("organization", str(UUID(int=2))),
        ("source", "other"),
        ("origin", "https://other.example"),
        ("reference", "secret-manager://arbitrary"),
        ("api_key", "not-accepted"),
        ("revision", 0),
    ):
        with pytest.raises(ValidationError):
            ProviderBinding.model_validate_json(
                json.dumps({**document, "credential": {**credential, field: value}})
            )


def test_copied_invalid_request_or_binding_cannot_enter_boundary() -> None:
    bad = request().model_copy(update={"article": XML_IDENTIFIER})
    with pytest.raises(ValidationError):
        ProviderBoundary(bad, binding(), clock=lambda: 1.0)
    with pytest.raises(ValidationError):
        ProviderBoundary(
            request(), binding().model_copy(update={"generation": 0}), clock=lambda: 1.0
        )
    with pytest.raises(FetchDenied, match="request_binding"):
        ProviderBoundary(request(article=True), binding(), clock=lambda: 1.0)


@pytest.mark.parametrize(
    "field",
    [
        "generation",
        "deletion_generation",
        "policy_version",
        "policy_revision",
        "discovery_revision",
    ],
)
def test_invalid_copied_boolean_binding_is_not_an_equal_integer(field: str) -> None:
    scope = binding()
    current = scope
    gate = ProviderBoundary(request(), scope, lambda: current, lambda: 1.0)
    invalid = scope.model_copy(update={field: True})
    with pytest.raises(FetchDenied, match="response_binding"):
        gate.read_response(replace(response(), binding=invalid))
    current = invalid
    with pytest.raises(FetchDenied, match="current_binding"):
        gate.read_response(response())


@pytest.mark.parametrize("status", [True, 201, 204, 301, 302, 303, 307, 308, 401, 403, 429, 500])
def test_status_redirect_auth_challenge_never_retries_or_consumes(status: int) -> None:
    def chunks() -> Any:
        raise AssertionError("Denied status must not consume body")
        yield b""

    with pytest.raises(FetchDenied, match="source_response"):
        boundary().read_response(replace(response(), status=status, chunks=chunks()))


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("url", "https://other.example/content/search/sciencedirect", "origin"),
        ("url", "https://api.elsevier.com/content/search/sciencedirect?key=not-accepted", "origin"),
        ("url", "https://api.elsevier.com/other", "origin"),
        ("content_type", "text/html", "content_type"),
        ("content_type", "application/problem+json", "content_type"),
        ("content_type", "application/json; charset=latin1", "content_type"),
        ("content_encoding", "gzip", "compressed"),
        ("content_length", -1, "body_limit"),
        ("content_length", 0, "body_limit"),
        ("content_length", True, "body_limit"),
        ("content_length", 1_048_577, "body_limit"),
        ("content_length", 1, "framing"),
        ("chunks", (None,), "chunk_denied"),
        ("chunks", (bytearray(b"x"),), "chunk_denied"),
        ("chunks", (b"x" * 1_048_577,), "body_limit"),
        ("chunks", (), "framing"),
        ("chunks", (b"",) * 4097, "chunk_limit"),
    ],
)
def test_response_refusals(field: str, value: Any, reason: str) -> None:
    with pytest.raises(FetchDenied, match=reason):
        boundary().read_response(replace(response(), **{field: value}))


def test_late_stream_error_and_timeout_never_release_partial_bytes() -> None:
    class FailedIterable:
        def __iter__(self) -> Any:
            raise OSError("untrusted iterator text must not escape")

    with pytest.raises(FetchDenied, match="^provider_stream_denied$"):
        boundary().read_response(replace(response(), chunks=FailedIterable()))

    def failed() -> Any:
        yield b"x"
        raise OSError("untrusted response text must not escape")

    with pytest.raises(FetchDenied, match="^provider_stream_denied$"):
        boundary().read_response(replace(response(), chunks=failed(), content_length=None))
    now = 1.0
    scope = binding()
    gate = ProviderBoundary(request(), scope, lambda: scope, lambda: now)

    def slow() -> Any:
        nonlocal now
        now = 60.0
        yield b"x"

    with pytest.raises(FetchDenied, match="deadline"):
        gate.read_response(replace(response(), chunks=slow()))


def test_revocation_during_stream_and_after_acquisition_refuses() -> None:
    scope = binding()
    current = scope
    gate = ProviderBoundary(request(), scope, lambda: current, lambda: 1.0)
    acquired = gate.read_response(response())
    assert gate.parse_search(acquired).articles[0].payload_sha256 == acquired.content_digest

    def changed() -> Any:
        nonlocal current
        yield b"x"
        current = scope.model_copy(update={"lease": UUID(int=99)})
        yield b"y"

    with pytest.raises(FetchDenied, match="current_binding"):
        gate.read_response(replace(response(), chunks=changed(), content_length=2))
    with pytest.raises(FetchDenied, match="current_binding"):
        gate.parse_search(acquired)


def test_streamed_search_preserves_exact_body_digest_and_request() -> None:
    data = payload([row()])
    gate = boundary()
    acquired = gate.read_response(
        replace(response(), chunks=(data[:20], b"", data[20:]), content_length=None)
    )
    assert acquired.request == request() and acquired.binding == binding()
    assert acquired.content_digest == hashlib.sha256(data).hexdigest()
    assert gate.parse_search(acquired).request == request().search
    with pytest.raises(FetchDenied, match="binding"):
        replace(acquired, body=b"changed")
    other = request().model_copy(update={"search": SearchRequest(query="other")})
    with pytest.raises(FetchDenied, match="binding"):
        boundary(other).require_response(acquired)


@pytest.mark.parametrize("field", ["organization", "job", "item", "lease", "request_fingerprint"])
def test_same_url_response_cannot_swap_dispatch_context(field: str) -> None:
    value: object = (
        ProviderRequest(search=SearchRequest(query="different query")).fingerprint
        if field == "request_fingerprint"
        else UUID(int=99)
    )
    original = response()
    wrong = original.binding.model_copy(update={field: value})

    def forbidden() -> Any:
        raise AssertionError("Wrong dispatch context must refuse before consuming bytes")
        yield b""

    with pytest.raises(FetchDenied, match="response_binding"):
        boundary().read_response(replace(original, binding=wrong, chunks=forbidden()))


def changed_xml() -> bytes:
    return fixture_bytes().replace(b"10.9999/synthetic.1", b"10.9999/synthetic.2")


def expectation(data: bytes | None = None) -> XmlExpectation:
    return XmlExpectation(
        requested_identifier=normalize_identifier("10.9999/synthetic.2"),
        content_digest=hashlib.sha256(data if data is not None else changed_xml()).hexdigest(),
        source_profile="article_retrieval_response",
    )


def test_generalized_protocol_roundtrip_and_output_acceptance() -> None:
    data, expected = changed_xml(), expectation()
    encoded = encode_input(data, expected)
    assert read_input(io.BytesIO(encoded)) == (data, expected)
    observed = parse_input(io.BytesIO(encoded))
    assert observed.requested_identifier != XML_IDENTIFIER
    assert len(observed.authors) == 3 and len(observed.candidates) == 2
    output = (
        json.dumps(
            {"profile": "network-none-parser-v1", "observation": observed.model_dump(mode="json")}
        ).encode()
        + b"\n"
    )
    assert decode_output(output, data, expected) == observed
    with pytest.raises(ValueError, match="provenance"):
        decode_output(output, data)
    with pytest.raises(ValidationError, match="synthetic"):
        retain_xml(observed, retained().binding, True)


@pytest.mark.parametrize(
    "header",
    [
        b"{}\n",
        b"[]\n",
        b"null\n",
        b"x" * 1025 + b"\n",
        b'{"protocol":"xml-input-v1","protocol":"xml-input-v1"}\n',
        b'{"protocol":NaN}\n',
        b'{"protocol":Infinity}\n',
        b"{}{}\n",
    ],
)
def test_parser_header_refusals(header: bytes) -> None:
    with pytest.raises(ValueError):
        read_input(io.BytesIO(header + changed_xml()))


@pytest.mark.parametrize(
    "change",
    [
        {"protocol": "xml-input-v2"},
        {"requested_identifier": {"kind": "doi", "value": "10.9999/UPPER"}},
        {"content_digest": "0" * 64},
        {"source_profile": "unknown"},
        {"tenant": str(UUID(int=1))},
        {"credential": str(UUID(int=5))},
        {"lease": str(UUID(int=4))},
        {"acquisition_url": "https://arbitrary.example/"},
    ],
)
def test_input_cannot_inject_authority_or_mismatch_digest(change: dict[str, Any]) -> None:
    header = json.dumps({**expectation().model_dump(), **change}, separators=(",", ":")).encode()
    with pytest.raises((ValueError, FetchDenied)):
        parse_input(io.BytesIO(header + b"\n" + changed_xml()))


@pytest.mark.parametrize("data", [b"", b"x" * 2_097_153, changed_xml() + b" "])
def test_protocol_bounded_exact_input_bytes(data: bytes) -> None:
    with pytest.raises(ValueError):
        encode_input(data, expectation())


def test_xml_source_profile_and_requested_identity_mismatches_refuse() -> None:
    expected = expectation().model_copy(update={"source_profile": "xocs_document"})
    with pytest.raises(ValueError, match="provenance"):
        parse_input(io.BytesIO(encode_input(changed_xml(), expected)))
    wrong = expectation().model_copy(update={"requested_identifier": XML_IDENTIFIER})
    with pytest.raises(FetchDenied, match="article_mismatch"):
        parse_input(io.BytesIO(encode_input(changed_xml(), wrong)))


def test_bound_response_uses_isolated_channel_and_fences_after_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req = request(article=True)
    scope = binding(req)
    current = scope
    gate = ProviderBoundary(req, scope, lambda: current, lambda: 1.0)
    acquired = gate.read_response(response(req, changed_xml()))
    called = 0

    def controlled_parser(
        settings: Settings, data: bytes, *, expected: XmlExpectation
    ) -> XmlObservation:
        nonlocal called
        called += 1
        assert settings == SETTINGS and expected.requested_identifier == req.article
        return parse_input(io.BytesIO(encode_input(data, expected)))

    monkeypatch.setattr(provider_xml, "parse_isolated", controlled_parser)
    value = provider_xml.parse_response(
        SETTINGS, gate, acquired, profile="article_retrieval_response"
    )
    assert (
        value.acquisition is acquired
        and value.observation.content_digest == acquired.content_digest
    )
    assert called == 1

    def revoking_parser(
        settings: Settings, data: bytes, *, expected: XmlExpectation
    ) -> XmlObservation:
        nonlocal current
        observed = controlled_parser(settings, data, expected=expected)
        current = scope.model_copy(update={"deletion_generation": 2})
        return observed

    monkeypatch.setattr(provider_xml, "parse_isolated", revoking_parser)
    with pytest.raises(FetchDenied, match="current_binding"):
        provider_xml.parse_response(SETTINGS, gate, acquired, profile="article_retrieval_response")


def test_provider_policy_cannot_be_approved_or_enable_live_settings() -> None:
    for update in (
        {"allowed_hosts": ["api.elsevier.com"]},
        {"execution_mode": "live"},
        {"credential_reference": str(UUID(int=5))},
    ):
        with pytest.raises(ValidationError):
            PolicyProposal.model_validate({**policy_body(), **update})
    with pytest.raises(ValidationError):
        Settings(environment="production", fixture_mode=True)
    with pytest.raises(ValidationError):
        Settings(live_sources_enabled=True)


def test_native_pii_profile_and_wrong_route_refusal() -> None:
    tree = ET.fromstring(changed_xml())
    native = tree.find(".//xocs:doc", NS)
    assert native is not None
    data = ET.tostring(native, encoding="utf-8")
    expected = XmlExpectation(
        requested_identifier=normalize_identifier("S0000000000000001"),
        content_digest=hashlib.sha256(data).hexdigest(),
        source_profile="xocs_document",
    )
    assert parse_input(io.BytesIO(encode_input(data, expected))).source_profile == "xocs_document"
    gate = boundary(request(article=True))
    acquired = gate.read_response(response(request(article=True), changed_xml()))
    with pytest.raises(FetchDenied, match="route"):
        gate.parse_search(acquired)


@pytest.mark.parametrize("kind", ["doi", "pii"])
def test_actual_generalized_source_bound_network_none_channel(kind: str) -> None:
    if os.environ.get("EM_REQUIRE_XML_ISOLATION") != "true":
        pytest.skip("Actual reviewed Docker parser image required for generalized XML channel")
    req = request(article=True)
    if kind == "pii":
        req = ProviderRequest(article=normalize_identifier("S0000000000000001"))
    gate = boundary(req)
    acquired = gate.read_response(response(req, changed_xml()))
    value = provider_xml.parse_response(
        SETTINGS, gate, acquired, profile="article_retrieval_response"
    )
    assert value.observation.requested_identifier == req.article
    assert value.observation.content_digest == acquired.content_digest
    assert len(value.observation.authors) == 3 and len(value.observation.candidates) == 2
    with pytest.raises(ValidationError, match="synthetic"):
        retain_xml(value.observation, retained().binding, True)


def test_actual_child_rejects_expected_identifier_mismatch() -> None:
    if os.environ.get("EM_REQUIRE_XML_ISOLATION") != "true":
        pytest.skip("Actual reviewed Docker parser image required for XML child refusal")
    req = ProviderRequest(article=XML_IDENTIFIER)
    gate = boundary(req)
    acquired = gate.read_response(response(req, changed_xml()))
    with pytest.raises(IsolationUnavailable, match="xml_parser_failed"):
        provider_xml.parse_response(SETTINGS, gate, acquired, profile="article_retrieval_response")

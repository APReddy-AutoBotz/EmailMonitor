"""Network-free authored observations, conservative identities and normalization."""

import json
import socket
from uuid import UUID

import pytest
from emailmonitor.associations.mapping import map_observation
from emailmonitor.associations.models import Bundle
from emailmonitor.associations.normalization import normalize
from emailmonitor.config import Settings
from emailmonitor.extraction.fixture import article_bytes
from emailmonitor.extraction.html import parse_article
from emailmonitor.extraction.pdf import parse_pdf
from emailmonitor.extraction.pdf_fixture import pdf_bytes
from emailmonitor.fetching.safety import FetchDenied
from pydantic import ValidationError

SETTINGS = Settings(environment="test", fixture_mode=True)
ORG = UUID("a0000000-0000-4000-8000-000000000001")
ORIGIN = "https://synthetic.publisher.example/"


@pytest.mark.parametrize(
    "raw,normalized",
    [
        ("Case+tag.Name@EXAMPLE.ORG", "Case+tag.Name@example.org"),
        ("case.name@example.org", "case.name@example.org"),
        ("a@bücher.example", "a@xn--bcher-kva.example"),
        ("a@faß.example", "a@xn--fa-hia.example"),
        ("a@xn--fa-hia.example", "a@xn--fa-hia.example"),
    ],
)
def test_conservative_local_part_and_nontransitional_idna(raw: str, normalized: str) -> None:
    value = normalize(raw)
    assert value.raw_address == raw and value.normalized_address == normalized
    assert value.comparison_key == normalized and value.syntax_status == "valid"
    assert value.domain_status == "not_checked" and value.delivery_status == "unverified"
    assert value.outreach_eligibility == "not_assessed"


@pytest.mark.parametrize(
    "raw,status",
    [
        ("ü@example.org", "unsupported"),
        ('"quoted"@example.org', "unsupported"),
        ("a@[127.0.0.1]", "unsupported"),
        ("a@@example.org", "invalid"),
        ("a..b@example.org", "invalid"),
        ("a@.example.org", "invalid"),
        ("a@bad_domain.org", "invalid"),
        ("a@example.org\n", "invalid"),
        ("a@localhost", "invalid"),
        ("a@example.org.", "invalid"),
        ("a@💩.example", "invalid"),
        ("a" * 65 + "@example.org", "invalid"),
        ("a@examp\x00le.org", "invalid"),
    ],
)
def test_unsupported_or_invalid_never_becomes_valid_ascii(raw: str, status: str) -> None:
    value = normalize(raw)
    assert value.syntax_status == status and value.normalized_address is None
    assert value.comparison_key.startswith("raw:")
    assert value.raw_address == raw


def html(name: str, *, org: UUID = ORG, data: bytes | None = None) -> Bundle:
    observation = parse_article(
        SETTINGS, ORIGIN + name, article_bytes(name) if data is None else data
    )
    return map_observation(SETTINGS, org, observation)


def pdf(name: str) -> Bundle:
    return map_observation(SETTINGS, ORG, parse_pdf(SETTINGS, ORIGIN + name, pdf_bytes(name)))


def test_html_first_corresponding_and_multiple_contacts_stay_separate() -> None:
    a = html("article-a.html")
    assert [(v.first, v.corresponding) for v in a.authors] == [(True, None), (False, True)]
    assert len(a.associations) == 1 and a.associations[0].state == "accepted"
    assert a.associations[0].author_id == a.authors[1].id
    b = html("article-b.html")
    assert len(b.associations) == 2 and all(v.state == "accepted" for v in b.associations)
    assert [v.first for v in b.authors] == [True, False]
    assert all(v.corresponding for v in b.authors)
    assert all(
        v.heuristic_score is None and v.calibrated_probability is None for v in b.associations
    )
    assert all(v.address.domain_status == "not_checked" for v in b.candidates)


def test_pdf_actual_roles_columns_wrap_and_unresolved_same_names() -> None:
    a = pdf("article-a.pdf")
    assert a.associations[0].state == "accepted" and a.associations[0].author_id == a.authors[1].id
    assert any(e.page == 2 and e.anchor == (50, 110) for e in a.evidence)
    assert len(pdf("article-b.pdf").associations) == 2
    wrapped = pdf("wrapped.pdf")
    assert wrapped.candidates[0].address.raw_address == "eva.mueller@example.org"
    assert wrapped.associations[0].state == "accepted"
    ambiguous = pdf("ambiguous.pdf")
    assert len(ambiguous.authors) == 2 and ambiguous.authors[0].id != ambiguous.authors[1].id
    assert all(a.identity_state == "article_local_unresolved" for a in ambiguous.authors)
    assert all(a.state != "accepted" for a in ambiguous.associations)


def test_same_name_html_never_automatically_merges_or_accepts() -> None:
    data = article_bytes("article-a.html").replace(b"Mira Rao", b"Alex Chen")
    value = html("article-a.html", data=data)
    assert value.authors[0].id != value.authors[1].id
    assert len(value.associations) == 2
    assert all(
        a.state == "needs_review" and a.reason == "ambiguous_identity" for a in value.associations
    )


def test_tenant_local_dedup_preserves_case_tags_dots_and_raw_variants() -> None:
    original = article_bytes("article-b.html")
    data = original.replace(b"ravi.das@example.org", b"Shared+tag@EXAMPLE.ORG").replace(
        b"noor.ibrahim@example.org", b"Shared+tag@example.org"
    )
    value = html("article-b.html", data=data)
    assert len(value.candidates) == 1
    assert value.candidates[0].normalization_collision
    assert len(value.candidates[0].raw_variants) == 2
    assert all(a.state != "accepted" for a in value.associations)
    assert (
        html("article-b.html", data=data, org=UUID(int=2)).candidates[0].id
        != value.candidates[0].id
    )
    assert (
        normalize("A.B+tag@example.org").comparison_key
        != normalize("a.b@example.org").comparison_key
    )
    assert (
        map_observation(SETTINGS, ORG, parse_article(SETTINGS, ORIGIN + "article-b.html", data))
        == value
    )


@pytest.mark.parametrize("name", ["no-contact.pdf", "encrypted.pdf", "corrupt.pdf", "scanned.pdf"])
def test_empty_or_refused_pdf_has_no_associations(name: str) -> None:
    assert pdf(name).associations == ()


def test_no_contact_and_partial_remain_explicit() -> None:
    assert html("no-contact.html").observation_status == "no_contact"
    assert html("no-contact.html").associations == ()
    assert pdf("page-cap.pdf").observation_status == "partial"


def test_retained_locator_without_excerpt_cannot_auto_accept() -> None:
    observation = parse_article(
        SETTINGS, ORIGIN + "article-a.html", article_bytes("article-a.html")
    )
    document = observation.model_dump()
    for author in document["authors"]:
        for evidence in author["evidence"]:
            evidence["excerpt"] = ""
    for candidate in document["candidates"]:
        candidate["evidence"]["excerpt"] = ""
    from emailmonitor.extraction.html import ArticleObservation

    value = map_observation(SETTINGS, ORG, ArticleObservation.model_validate(document))
    assert value.associations[0].state == "needs_review"
    assert value.associations[0].reason == "retained_locator_only"


@pytest.mark.parametrize(
    "mutation",
    ["missing_evidence", "unknown_author", "probability", "mailbox", "bool_zero", "forged_key"],
)
def test_relational_and_unavailable_claims_refuse(mutation: str) -> None:
    document = json.loads(html("article-a.html").model_dump_json())
    if mutation == "missing_evidence":
        document["associations"][0]["evidence_ids"] = []
    elif mutation == "unknown_author":
        document["associations"][0]["author_id"] = str(UUID(int=3))
    elif mutation == "probability":
        document["associations"][0]["calibrated_probability"] = 0.99
    elif mutation == "mailbox":
        document["candidates"][0]["address"]["delivery_status"] = "verified"
    elif mutation == "bool_zero":
        document["technical_network_checks"] = 0
    else:
        document["candidates"][0]["address"]["comparison_key"] = "made.up@example.org"
    with pytest.raises(ValidationError):
        Bundle.model_validate_json(json.dumps(document))


def test_pure_mapping_has_no_io_and_production_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    observation = parse_article(
        SETTINGS, ORIGIN + "article-a.html", article_bytes("article-a.html")
    )

    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("No network validation")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    assert map_observation(SETTINGS, ORG, observation).associations[0].state == "accepted"
    with pytest.raises(FetchDenied):
        map_observation(Settings(environment="production"), ORG, observation)


def test_nonunicode_surrogate_input_is_refused_at_model_boundary() -> None:
    with pytest.raises(ValueError):
        normalize("\ud800@example.org")


def test_unobserved_address_cannot_enter_mapping_even_from_copied_worker_model() -> None:
    observation = parse_article(
        SETTINGS, ORIGIN + "article-a.html", article_bytes("article-a.html")
    )
    candidate = observation.candidates[0].model_copy(update={"raw_address": "invented@example.org"})
    forged = observation.model_copy(update={"candidates": [candidate]})
    with pytest.raises(ValueError, match="retained literally"):
        map_observation(SETTINGS, ORG, forged)

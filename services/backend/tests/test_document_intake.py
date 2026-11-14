"""Single-document intake across PDF, JATS and landing-page HTML (OA-016)."""

import csv
import io
from pathlib import Path

import pytest
from emailmonitor.dev_server import ORG_ID, app
from emailmonitor.discovery.document_intake import extract_document, sniff_document
from emailmonitor.fetching.safety import FetchDenied
from fastapi.testclient import TestClient
from pdf_fixture_builder import document

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
HTML = (FIXTURES / "publisher-html" / "highwire-article.html").read_bytes()
JATS = (FIXTURES / "jats" / "usher-base-editing.xml").read_bytes()
URL = f"/api/v1/organizations/{ORG_ID}/open-access/documents"


def _pdf() -> bytes:
    lines = [
        "Coastal sediment carbon budgets",
        "Amara Diallo1, Pieter de Vries2*",
        "*Correspondence: Pieter de Vries, p.devries@marine.delft.example",
        "doi: 10.5555/csc.2026.77",
    ]
    return document([[(72.0, 740.0 - 14 * i, 9.0, t) for i, t in enumerate(lines)]])


def test_sniffing() -> None:
    assert sniff_document(_pdf()) == "pdf"
    assert sniff_document(JATS) == "jats_xml"
    assert sniff_document(HTML) == "html"
    with pytest.raises(FetchDenied, match="unsupported_document_type"):
        sniff_document(b"just some text")


def test_jats_document() -> None:
    result = extract_document(JATS, reference_year=2026)
    assert result.kind == "jats_xml"
    assert result.doi == "10.1038/s41587-026-01824-x"
    assert result.publication_year == 2026
    assert result.unmatched_candidates == 1
    by_email = {c.email: c for c in result.contacts}
    assert by_email["t.nowak@genetics.krakow.example"].is_corresponding_author is True
    assert by_email["t.nowak@genetics.krakow.example"].source == "document"
    assert by_email["core-lab@genetics.krakow.example"].outreach_eligibility == "needs_review"


def test_html_document_with_role_filter_and_notes() -> None:
    result = extract_document(
        HTML,
        page_url="https://journal.publisher.example/sops/2026/0142",
        target_roles="corresponding",
        reference_year=2026,
    )
    assert result.kind == "html"
    assert {c.email for c in result.contacts} == {
        "saga.lindgren@agri.uppsala.example",
        "y.haddad@arid.amman.example",
    }
    assert result.linked_pdf_url == "https://journal.publisher.example/sops/2026/0142/pdf"
    assert any("obfuscated" in note for note in result.review_notes)
    haddad = next(c for c in result.contacts if c.email.startswith("y.haddad"))
    assert haddad.affiliations == ("Institute of Arid Agriculture, Amman, Jordan",)
    assert haddad.full_text_url == "https://journal.publisher.example/sops/2026/0142"


def test_pdf_document_needs_known_authors_to_link() -> None:
    unlinked = extract_document(_pdf(), reference_year=2026)
    assert unlinked.contacts[0].outreach_eligibility == "needs_review"
    assert any("no known author" in n for n in unlinked.review_notes)

    linked = extract_document(
        _pdf(), known_authors=["Amara Diallo", "Pieter de Vries"], reference_year=2026
    )
    (contact,) = linked.contacts
    assert contact.author_name == "Pieter de Vries"
    assert contact.author_position == 2
    assert contact.is_corresponding_author is True
    assert contact.is_first_author is False
    assert contact.doi == "10.5555/csc.2026.77"
    assert contact.evidence_locator == "page[1]/line[3]"
    assert contact.outreach_eligibility == "eligible"


def test_document_suppression() -> None:
    result = extract_document(JATS, suppressed_domains=["pune.example"], reference_year=2026)
    mehta = next(c for c in result.contacts if c.email == "r.mehta@bio.pune.example")
    assert mehta.outreach_eligibility == "suppressed"
    assert b"r.mehta" not in result.export_instantly_csv()


def test_jats_without_identifier_is_refused() -> None:
    data = b"<?xml version='1.0'?><article><front><article-meta/></front></article>"
    with pytest.raises(FetchDenied, match="jats_identifier_missing"):
        extract_document(data)


def test_endpoint_round_trip() -> None:
    client = TestClient(app)
    response = client.post(
        URL,
        content=_pdf(),
        params={"known_authors": "Amara Diallo; Pieter de Vries"},
        headers={"content-type": "application/pdf"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "pdf"
    assert body["contacts"][0]["author_name"] == "Pieter de Vries"


def test_endpoint_refusals() -> None:
    client = TestClient(app)
    assert client.post(URL, content=b"plain text").status_code == 400
    other = URL.replace(ORG_ID, "00000000-0000-0000-0000-000000000009")
    assert client.post(other, content=HTML).status_code == 404
    too_big = client.post(URL, content=b"x", headers={"content-length": str(30_000_000)})
    assert too_big.status_code in (400, 413)


def test_csv_export_from_document() -> None:
    result = extract_document(HTML, reference_year=2026)
    rows = list(csv.DictReader(io.StringIO(result.export_smartlead_csv().decode())))
    assert {r["Email"] for r in rows} == {
        "saga.lindgren@agri.uppsala.example",
        "y.haddad@arid.amman.example",
    }

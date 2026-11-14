"""Publisher landing-page and PDF contact parsers on supplied bytes (OA-014, OA-015)."""

from pathlib import Path

import pytest
from emailmonitor.extraction.citation_meta import normalize_page_date, parse_citation_page
from emailmonitor.extraction.pdf_contacts import parse_pdf_contacts
from emailmonitor.fetching.safety import FetchDenied
from pdf_fixture_builder import document

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "publisher-html"
PAGE = (FIXTURE / "highwire-article.html").read_bytes()


def test_highwire_page_metadata_and_authors() -> None:
    obs = parse_citation_page(PAGE, "https://journal.publisher.example/sops/2026/0142")
    assert obs.title == "Soil microbiome resilience under prolonged drought"
    assert obs.journal == "Synthetic Open Plant Science"
    assert obs.doi == "10.5555/sops.2026.0142"
    assert obs.publication_date == "2026-05-12"
    assert obs.pdf_url == "https://journal.publisher.example/sops/2026/0142/pdf"
    assert obs.keywords == ("soil microbiome", "drought", "rhizosphere")
    assert [a.display_name for a in obs.authors] == [
        "Chidi Okonkwo",
        "Saga Lindgren",
        "Yusuf Haddad",
    ]
    assert obs.authors[0].orcid == "0000-0002-1825-0097"
    assert obs.authors[2].institutions == ("Institute of Arid Agriculture, Amman, Jordan",)
    assert [a.corresponding for a in obs.authors] == [False, True, True]
    assert obs.obfuscated_address_count == 1


def test_highwire_page_candidates_and_exclusions() -> None:
    obs = parse_citation_page(PAGE)
    found = {c.raw_address: c for c in obs.candidates}
    assert set(found) == {
        "saga.lindgren@agri.uppsala.example",
        "y.haddad@arid.amman.example",
        "datadesk@arid.amman.example",
    }
    assert found["saga.lindgren@agri.uppsala.example"].association_basis == (
        "highwire_author_sequence"
    )
    assert found["saga.lindgren@agri.uppsala.example"].author_positions == (2,)
    haddad = found["y.haddad@arid.amman.example"]
    assert haddad.association_basis == "correspondence_block_surname"
    assert haddad.author_positions == (3,)
    assert "Correspondence" in haddad.evidence.excerpt
    assert found["datadesk@arid.amman.example"].association_status == "unmatched"


@pytest.mark.parametrize(
    "excluded",
    [
        "editorial@publisher.example",  # header
        "nav@publisher.example",  # nav
        "support@publisher.example",  # footer
        "script.only@tracker.example",  # script text
        "style.only@tracker.example",  # style text
        "hidden.author@arid.amman.example",  # hidden block
        "not-correspondence@publisher.example",  # no correspondence wording
        "attacker@evil.example",  # untrusted body instruction
    ],
)
def test_highwire_page_never_reports(excluded: str) -> None:
    assert excluded not in {c.raw_address for c in parse_citation_page(PAGE).candidates}


def test_email_before_any_author_is_unmatched() -> None:
    html = (
        b'<html><head><meta name="citation_title" content="T">'
        b'<meta name="citation_author_email" content="orphan@lab.example">'
        b'<meta name="citation_author" content="Solo, Ana"></head></html>'
    )
    obs = parse_citation_page(html)
    (candidate,) = obs.candidates
    assert candidate.association_basis == "unmatched"
    assert obs.authors[0].corresponding is None


def test_page_without_metadata_is_unsupported() -> None:
    assert parse_citation_page(b"<html><body><p>Hello</p></body></html>").status == "unsupported"


@pytest.mark.parametrize(
    ("data", "url", "reason"),
    [
        (b"", None, "empty_html_payload"),
        (b"<html>", "http://insecure.example/a", "page_url_shape_denied"),
        (b"<html>", "https://a.example/\x00", "page_url_shape_denied"),
    ],
)
def test_page_input_refusals(data: bytes, url: str | None, reason: str) -> None:
    with pytest.raises(FetchDenied, match=reason):
        parse_citation_page(data, url)


def test_page_node_limit() -> None:
    with pytest.raises(FetchDenied, match="html_node_limit_exceeded"):
        parse_citation_page(b"<html>" + b"<b>x</b>" * 70_000 + b"</html>")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026/05/12", "2026-05-12"),
        ("2026-5", "2026-05"),
        ("2026", "2026"),
        ("2026-13-01", None),
        ("May 2026", None),
        ("2026-05-12T10:00:00Z", "2026-05-12"),
    ],
)
def test_page_date_normalization(raw: str, expected: str | None) -> None:
    assert normalize_page_date(raw) == expected


def _pdf(*lines: str) -> bytes:
    return document([[(72.0, 740.0 - 14 * i, 9.0, text) for i, text in enumerate(lines)]])


AUTHORS = ("Amara Diallo", "Pieter de Vries")


def test_pdf_shared_correspondence_line_is_split_by_surname() -> None:
    obs = parse_pdf_contacts(
        _pdf(
            "Coastal sediment carbon budgets",
            "Amara Diallo1, Pieter de Vries2*",
            "*Correspondence: Pieter de Vries, p.devries@marine.delft.example; "
            "Amara Diallo, a.diallo@marine.dakar.example",
            "doi: 10.5555/csc.2026.77",
        ),
        known_authors=AUTHORS,
    )
    assert obs.status == "observed"
    assert obs.doi == "10.5555/csc.2026.77"
    by_address = {c.raw_address: c for c in obs.candidates}
    assert by_address["p.devries@marine.delft.example"].author_name == "Pieter de Vries"
    assert by_address["a.diallo@marine.dakar.example"].author_name == "Amara Diallo"


def test_pdf_bare_marker_labels_next_line_only() -> None:
    obs = parse_pdf_contacts(
        _pdf(
            "Corresponding author:",
            "Diallo A. (amara.d@marine.dakar.example)",
            "Lab website: info@lab.delft.example",
        ),
        known_authors=AUTHORS,
    )
    by_address = {c.raw_address: c for c in obs.candidates}
    assert by_address["amara.d@marine.dakar.example"].region == "pdf_correspondence_line"
    assert by_address["amara.d@marine.dakar.example"].author_name == "Amara Diallo"
    info = by_address["info@lab.delft.example"]
    assert info.region == "pdf_front_matter"
    assert info.association_basis == "unmatched"


def test_pdf_previous_line_name_does_not_leak() -> None:
    obs = parse_pdf_contacts(
        _pdf(
            "*Correspondence: Pieter de Vries, p.devries@marine.delft.example",
            "Contact: info@lab.delft.example",
        ),
        known_authors=AUTHORS,
    )
    by_address = {c.raw_address: c for c in obs.candidates}
    assert by_address["info@lab.delft.example"].author_name is None


def test_pdf_without_known_authors_is_unmatched() -> None:
    obs = parse_pdf_contacts(_pdf("Correspondence: Pieter de Vries, p.devries@x.example"))
    assert obs.candidates[0].association_status == "unmatched"


def test_pdf_grouped_notation_is_counted_not_expanded() -> None:
    obs = parse_pdf_contacts(_pdf("E-mail: {amara, office}@marine.dakar.example"))
    assert obs.candidates == ()
    assert obs.status == "no_contact"
    assert obs.grouped_address_notations == 1


def test_pdf_references_section_is_ignored() -> None:
    obs = parse_pdf_contacts(_pdf("Title", "References", "1. Cited S. cited@ref.example"))
    assert obs.candidates == ()


def test_pdf_wrapped_address_is_counted() -> None:
    obs = parse_pdf_contacts(_pdf("E-mail: p.devries@marine.", "delft.example"))
    assert obs.possibly_wrapped_addresses == 1
    assert all(c.raw_address != "p.devries@marine.delft.example" for c in obs.candidates)


def test_pdf_refusals_and_failures() -> None:
    encrypted = document([[(72.0, 720.0, 9.0, "x@lab.example")]], encrypted=True)
    assert parse_pdf_contacts(encrypted).status == "encrypted_refused"
    assert parse_pdf_contacts(b"%PDF-1.4 truncated").status == "unreadable"
    image = document([[]], image_only=True)
    assert parse_pdf_contacts(image).status == "image_only"
    with pytest.raises(FetchDenied, match="not_a_pdf"):
        parse_pdf_contacts(b"<html></html>")
    with pytest.raises(FetchDenied, match="pdf_page_window_denied"):
        parse_pdf_contacts(_pdf("x"), max_pages=6)


def test_pdf_page_window() -> None:
    pages = [[(72.0, 720.0, 9.0, f"Correspondence: p{i}@lab.example")] for i in range(4)]
    obs = parse_pdf_contacts(document(pages), max_pages=2)
    assert obs.page_count == 4
    assert obs.pages_read == 2
    assert [c.raw_address for c in obs.candidates] == ["p0@lab.example", "p1@lab.example"]

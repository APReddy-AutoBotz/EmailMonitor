"""Regressions for the fifth independent review (2026-11-15): no lost results."""

import pytest
from emailmonitor.extraction.attribution import Person, asserts_correspondence, attribute_spans
from emailmonitor.extraction.citation_meta import parse_citation_page
from emailmonitor.extraction.pdf_contacts import parse_pdf_contacts
from pdf_fixture_builder import document


def _asserts(text: str, needle: str) -> bool:
    return asserts_correspondence(text, text.index(needle))


def _pdf(*lines: str) -> list[tuple[str, str | None, str]]:
    data = document([[(72.0, 740.0 - 14 * i, 9.0, t) for i, t in enumerate(lines)]])
    obs = parse_pdf_contacts(data, known_authors=["John Smith"])
    return [(c.raw_address, c.author_name, c.region) for c in obs.candidates]


@pytest.mark.parametrize(
    "text",
    [
        "Corresponding author: Prof. John Smith, js@ox.example",
        "Correspondence: Dr. John Smith (js@x.example)",
        "Correspondence: John Smith, St. Louis, MO. js@wustl.example",
        "Correspondence: J. Smith, Acme Inc. Tel: 123; js@acme.example",
        "Correspondence to John Smith (e-mail: js@ox.example)",
        "Correspondence to John Smith (email: js@ox.example)",
        "Correspondence: John Smith. Courriel: js@x.example",
        "Correspondence: Royal Mail Group, js@x.example",
    ],
)
def test_abbreviations_inline_labels_and_names_keep_the_clause(text: str) -> None:
    assert _asserts(text, "js@")


def test_email_link_text_is_not_a_label() -> None:
    page = (
        b'<html><head><meta name="citation_title" content="T">'
        b'<meta name="citation_author" content="Brown, Kate">'
        b'<meta name="citation_author" content="Smith, John"></head><body><article>'
        b'<p>Correspondence: Kate Brown <a href="mailto:kb@x.example">Email</a>; '
        b'John Smith <a href="mailto:js@x.example">Email</a></p></article></body></html>'
    )
    obs = parse_citation_page(page)
    assert [a.corresponding for a in obs.authors] == [True, True]
    assert {c.association_basis for c in obs.candidates} == {"correspondence_block_surname"}


def test_lowercase_particles_inside_names() -> None:
    text = "Correspondence: Maria do Carmo Silva, mcs@x.example"
    start = text.index("mcs@")
    people = [Person(1, "Maria do Carmo Silva")]
    assert attribute_spans(text, [(start, start + 14)], people) == [(1, "name")]


@pytest.mark.parametrize(
    "lines",
    [
        ("Corresponding author: Prof. John Smith, js@ox.example",),
        ("Corresponding author: John Smith, MIT, Cambridge, MA 02139.", "js@ox.example"),
        ("Correspondence: John Smith et al.", "js@ox.example"),
        ("Correspondence: John Smith, js@ox.example", "1. Introduction"),
        ("Correspondence: John Smith, js@ox.example", "v1.2 released"),
        ("Correspondence: John Smith, js@ox.example.", "e.g. results"),
    ],
)
def test_pdf_valid_addresses_are_not_lost(lines: tuple[str, ...]) -> None:
    assert _pdf(*lines) == [("js@ox.example", "John Smith", "pdf_correspondence_line")]

"""Regressions for the second independent review (2026-11-15).

Inputs reproduce the reviewer's cases: sliced non-ASCII addresses, short
surnames read as initials, surnames inside institution names, particle
surnames, address-then-name lists, and four super-linear paths.
"""

import time

import pytest
from emailmonitor.discovery.document_intake import _jats_identifier, extract_document
from emailmonitor.extraction.attribution import Person, attribute_spans, find_addresses
from emailmonitor.extraction.citation_meta import parse_citation_page
from emailmonitor.extraction.jats import parse_jats_xml
from emailmonitor.extraction.pdf_contacts import parse_pdf_contacts
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.openaccess import PmcIdentifier
from pdf_fixture_builder import document

PMC = PmcIdentifier(value="PMC7700001")


def _jats(authors: list[tuple[str, str]], note: str) -> bytes:
    contribs = "".join(
        f'<contrib contrib-type="author"><name><surname>{s}</surname>'
        f"<given-names>{g}</given-names></name></contrib>"
        for g, s in authors
    )
    return (
        "<article><front><article-meta><contrib-group>"
        f"{contribs}</contrib-group><author-notes><corresp>{note}</corresp>"
        "</author-notes></article-meta></front></article>"
    ).encode()


def _owners(obs: object) -> dict[str, list[int]]:
    return {c.raw_address: c.author_positions for c in obs.candidates}  # type: ignore[attr-defined]


def _pdf(*lines: str) -> bytes:
    return document([[(72.0, 740.0 - 14 * i, 9.0, t) for i, t in enumerate(lines)]])


# 1, 12 — literal or nothing


@pytest.mark.parametrize(
    "text",
    [
        "müller@uni.de",
        "jose.garcía@x.es",
        "pré.smith@x.edu",
        "a@x.comé",
        "a@x.com.b@y.org",
        "smith@x.edu.Phone: 1",
    ],
)
def test_no_sliced_or_run_on_addresses(text: str) -> None:
    for start, address in find_addresses(text):
        # Whatever is reported must be a complete token, never a fragment.
        before = text[start - 1] if start else " "
        after = text[start + len(address) : start + len(address) + 1] or " "
        assert not before.isalnum() and not after.isalnum(), (text, address)
    assert find_addresses(text) == []


def test_valid_leading_underscore_and_plain_lists() -> None:
    assert find_addresses("_john@x.com") == [(0, "_john@x.com")]
    assert [a for _s, a in find_addresses("Mail: a@x.com, b@y.org.")] == ["a@x.com", "b@y.org"]


def test_pdf_never_reports_slice_of_umlaut_address() -> None:
    obs = parse_pdf_contacts(
        _pdf("Correspondence: Jürgen Müller, müller@uni.de"), known_authors=["Jürgen Müller"]
    )
    assert all(c.raw_address != "ller@uni.de" for c in obs.candidates)


# 2 — short surname label is a name, not initials


def test_short_surname_label_is_not_initials() -> None:
    obs = parse_jats_xml(
        _jats(
            [("Wei", "Li"), ("Lan", "Ito")],
            "E-mail addresses: wli@x.example (Li), lito@y.example (Ito)",
        ),
        PMC,
    )
    assert _owners(obs) == {"wli@x.example": [1], "lito@y.example": [2]}


# 3 — surnames inside institution names


@pytest.mark.parametrize(
    "note",
    [
        "Correspondence: Department of Surgery, Brown University, Providence, RI. "
        "E-mail: kj@brown.example",
        "Correspondence: Johns Hopkins School of Medicine, Baltimore. kjones@jhmi.example",
    ],
)
def test_institution_word_never_claims_an_address(note: str) -> None:
    obs = parse_jats_xml(
        _jats([("Alice", "Brown"), ("Mary", "Hopkins"), ("Karen", "Jones")], note), PMC
    )
    (positions,) = _owners(obs).values()
    assert positions == []
    assert all(a.corresponding is not True for a in obs.authors[:2])


def test_pdf_institution_word_never_claims_an_address() -> None:
    obs = parse_pdf_contacts(
        _pdf("Correspondence: Brown University, Providence. kj@brown.example"),
        known_authors=["Alice Brown", "Karen Jones"],
    )
    assert obs.candidates[0].author_name is None


# 5 — particle surnames


def test_particle_surname_does_not_match_preposition() -> None:
    html = b"""<html><head><meta name="citation_title" content="T">
<meta name="citation_author" content="Silva, Maria">
<meta name="citation_author" content="de Souza, Joao"></head><body>
<p>Correspondence: Faculdade de Medicina, Universidade de Sao Paulo.
<a href="mailto:ms@usp.example">ms@usp.example</a></p></body></html>"""
    (candidate,) = parse_citation_page(html).candidates
    assert candidate.author_positions == ()


def test_particle_surname_still_matches_the_person() -> None:
    people = [Person(1, "Maria Silva"), Person(2, "Joao de Souza")]
    text = "Correspondence to Joao de Souza: js@usp.example"
    start = text.index("js@")
    assert attribute_spans(text, [(start, len(text))], people) == [(2, "name")]


# 6 — address-then-name lists


def test_address_then_name_list_jats_and_pdf() -> None:
    note = "E-mail: smith@x.example, John Smith; jones@y.example, Karen Jones"
    obs = parse_jats_xml(_jats([("John", "Smith"), ("Karen", "Jones")], note), PMC)
    assert _owners(obs) == {"smith@x.example": [1], "jones@y.example": [2]}
    pdf = parse_pdf_contacts(_pdf(note), known_authors=["John Smith", "Karen Jones"])
    assert {c.raw_address: c.author_name for c in pdf.candidates} == {
        "smith@x.example": "John Smith",
        "jones@y.example": "Karen Jones",
    }


def test_name_then_address_list_still_works() -> None:
    note = "Correspondence to John Smith: smith@x.example; Karen Jones: jones@y.example"
    obs = parse_jats_xml(_jats([("John", "Smith"), ("Karen", "Jones")], note), PMC)
    assert _owners(obs) == {"smith@x.example": [1], "jones@y.example": [2]}


# 10, 13 — HTML markers and roles


def test_html_email_label_links_without_role() -> None:
    html = b"""<html><head><meta name="citation_title" content="T">
<meta name="citation_author" content="Smith, John"></head><body>
<p>E-mail: <a href="mailto:smith@x.example">smith@x.example</a> (J. Smith)</p></body></html>"""
    obs = parse_citation_page(html)
    (candidate,) = obs.candidates
    assert candidate.association_basis == "email_block_surname"
    assert candidate.author_positions == (1,)
    assert obs.authors[0].corresponding is not True


def test_highwire_email_tag_does_not_assert_role() -> None:
    html = b"""<html><head><meta name="citation_title" content="T">
<meta name="citation_author" content="Smith, John">
<meta name="citation_author_email" content="smith@x.example"></head></html>"""
    obs = parse_citation_page(html)
    assert obs.candidates[0].association_basis == "highwire_author_sequence"
    assert obs.authors[0].corresponding is not True


# 11 — identifier bounds


def test_out_of_range_pmcid_falls_back_to_doi() -> None:
    data = (
        b'<?xml version="1.0"?><article><front><article-meta>'
        b'<article-id pub-id-type="pmc">PMC12345678901</article-id>'
        b'<article-id pub-id-type="doi">10.5555/fallback.1</article-id>'
        b"</article-meta></front></article>"
    )
    assert _jats_identifier(data).value == "10.5555/fallback.1"
    assert extract_document(data).doi == "10.5555/fallback.1"


# 4, 7, 8, 9 — bounded time


def test_nested_correspondence_blocks_are_fast() -> None:
    filler = "x " * 20_000
    inner = '<p>Correspondence: <a href="mailto:a@lab.example">a</a></p>'
    page = inner
    for _ in range(50):
        page = f"<div>Correspondence: {filler}{page}</div>"
    authors = "".join(f'<meta name="citation_author" content="S{i}, G{i}">' for i in range(100))
    head = f'<html><head><meta name="citation_title" content="T">{authors}</head>'
    html = f"{head}<body>{page}</body></html>"
    started = time.perf_counter()
    parse_citation_page(html.encode())
    assert time.perf_counter() - started < 10


def test_many_unmatched_structured_links_are_linear() -> None:
    links = "".join(
        f'<ext-link ext-link-type="email" xlink:href="mailto:q{i}@x.example">{"t" * 95}</ext-link>'
        for i in range(15_000)
    )
    data = (
        '<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>'
        '<contrib-group><contrib contrib-type="author" corresp="yes"><name><surname>A</surname>'
        f"<given-names>B</given-names></name></contrib></contrib-group><author-notes><corresp>{links}"
        "</corresp></author-notes></article-meta></front></article>"
    ).encode()
    started = time.perf_counter()
    obs = parse_jats_xml(data, PMC)
    assert time.perf_counter() - started < 10
    assert len(obs.candidates) == 100


def test_many_note_addresses_with_many_authors_are_bounded() -> None:
    authors = [(f"G{i}", f"Surname{i}") for i in range(100)]
    note = "a@b.cc " * 100_000
    started = time.perf_counter()
    parse_jats_xml(_jats(authors, note), PMC)
    assert time.perf_counter() - started < 10


def test_identifier_prescan_is_linear() -> None:
    data = b'<?xml version="1.0"?><article>' + b"<article-id " * 25_000
    started = time.perf_counter()
    with pytest.raises(FetchDenied, match="jats_identifier_missing"):
        _jats_identifier(data)
    assert time.perf_counter() - started < 2

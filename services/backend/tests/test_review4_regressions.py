"""Regressions for the fourth independent review (2026-11-15)."""

import pytest
from emailmonitor.discovery.document_intake import extract_document
from emailmonitor.extraction.attribution import (
    Person,
    asserts_correspondence,
    attribute_spans,
    find_addresses,
)
from emailmonitor.extraction.citation_meta import parse_citation_page
from emailmonitor.extraction.jats import parse_jats_xml
from emailmonitor.extraction.pdf_contacts import parse_pdf_contacts
from emailmonitor.sources.openaccess import PmcIdentifier
from pdf_fixture_builder import document

PMC = PmcIdentifier(value="PMC7700001")


def _asserts(text: str, address: str) -> bool:
    return asserts_correspondence(text, text.index(address))


def _pdf(*lines: str) -> bytes:
    return document([[(72.0, 740.0 - 14 * i, 9.0, t) for i, t in enumerate(lines)]])


def _page(body: str) -> bytes:
    return (
        '<html><head><meta name="citation_title" content="T">'
        '<meta name="citation_author" content="Jones, Kate">'
        '<meta name="citation_author" content="Smith, John"></head>'
        f"<body><article>{body}</article></body></html>"
    ).encode()


# H1 — mail labels and sentence boundaries end the correspondence clause


@pytest.mark.parametrize(
    "text",
    [
        "Corresponding author: Kate Jones. Emails: kj@x.example (K.J.), js@y.example (J.S.)",
        "Correspondence to: Kate Jones, kj@x.example; Tel +1 555; "
        "E-mail of co-author: John Smith, js@y.example",
        "Corresponding author. Other authors' e-mail addresses: js@y.example (J.S.)",
        "Correspondence: Kate Jones. Electronic mail: js@y.example, kj@x.example",
        "Kate Jones is the corresponding author. John Smith: js@y.example",
    ],
)
def test_co_author_addresses_get_no_role(text: str) -> None:
    assert not _asserts(text, "js@y.example")


@pytest.mark.parametrize(
    ("text", "address"),
    [
        ("*Correspondence: Chiara Rossi, c@x.example; Luca Bianchi, l@x.example", "l@x.example"),
        ("Correspondence: K. Jones, kj@x.example", "kj@x.example"),
        ("Correspondence: Kate Jones, Dept of X, Univ Y, UK. Email: kj@x.example", "kj@x.example"),
        ("*To whom correspondence should be addressed. Email: kj@x.example", "kj@x.example"),
        (
            "Correspondence and requests for materials should be addressed to A.B. "
            "(email: ab@x.example)",
            "ab@x.example",
        ),
    ],
)
def test_real_correspondence_layouts_keep_the_role(text: str, address: str) -> None:
    assert _asserts(text, address)


def test_role_not_fabricated_end_to_end() -> None:
    text = "Corresponding author: Kate Jones. Emails: kj@x.example (K.J.), js@y.example (J.S.)"
    contribs = "".join(
        f'<contrib contrib-type="author"><name><surname>{s}</surname>'
        f"<given-names>{g}</given-names></name></contrib>"
        for g, s in (("Kate", "Jones"), ("John", "Smith"))
    )
    obs = parse_jats_xml(
        (
            f"<article><front><article-meta><contrib-group>{contribs}</contrib-group>"
            f"<author-notes><corresp>{text}</corresp></author-notes></article-meta></front>"
            "</article>"
        ).encode(),
        PMC,
    )
    assert obs.authors[1].corresponding is not True
    result = extract_document(_pdf(text), known_authors=["Kate Jones", "John Smith"])
    smith = next(c for c in result.contacts if c.email == "js@y.example")
    assert smith.author_name == "John Smith" and not smith.is_corresponding_author


# H2 — joiners and invisible characters never yield a fragment


@pytest.mark.parametrize(
    "text",
    [
        "k­j@med.harvard.edu",
        "kj@med.har­vard.edu",
        "kj@med.harvard​.edu",
        "first‑last@x.example",
        "o’neil@x.example",
    ],
)
def test_joiner_characters_reject_the_token(text: str) -> None:
    assert find_addresses(text) == []


def test_soft_hyphen_inside_jats_email_reads_as_displayed() -> None:
    obs = parse_jats_xml(
        b'<article><front><article-meta><contrib-group><contrib contrib-type="author" '
        b'corresp="yes"><name><surname>Jones</surname><given-names>Kate</given-names></name>'
        b"</contrib></contrib-group><author-notes><corresp>E-mail: "
        b"<email>kj@med.har&#173;vard.edu</email></corresp></author-notes></article-meta>"
        b"</front></article>",
        PMC,
    )
    assert [c.raw_address for c in obs.candidates] == ["kj@med.harvard.edu"]


def test_pdf_soft_hyphen_inside_address_is_not_sliced() -> None:
    obs = parse_pdf_contacts(
        _pdf("Correspondence: Kate Jones, kj@med.har­vard.edu"), known_authors=["Kate Jones"]
    )
    assert all(c.raw_address != "kj@med.har" for c in obs.candidates)


# H3, M3 — PDF wraps in both directions; sentence-final addresses kept


@pytest.mark.parametrize(
    "lines",
    [
        ("Correspondence: John Smith, john.", "smith@x.example"),
        ("Correspondence: John Smith, john-", "smith@x.example"),
        ("Correspondence: John Smith, js@med.harvard", ".edu"),
        ("Correspondence: John Smith, js@med.harv", "ard.edu"),
    ],
)
def test_pdf_wraps_are_never_reported_cut(lines: tuple[str, str]) -> None:
    obs = parse_pdf_contacts(_pdf(*lines), known_authors=["John Smith"])
    assert obs.candidates == ()
    assert obs.possibly_wrapped_addresses >= 1


@pytest.mark.parametrize(
    "lines",
    [
        ("Requests to John Smith (Correspondence), js@x.example.", "and Kate Jones"),
        ("Correspondence: John Smith.", "js@x.example"),
        ("Correspondence: John Smith, js@x.example", "Department of Medicine"),
    ],
)
def test_pdf_complete_addresses_are_kept(lines: tuple[str, str]) -> None:
    obs = parse_pdf_contacts(_pdf(*lines), known_authors=["John Smith"])
    assert [c.raw_address for c in obs.candidates] == ["js@x.example"]


# H4 — exact HTML link spans


@pytest.mark.parametrize(
    "body",
    [
        '<p>Correspondence: Kate Jones, <a href="mailto:js@y.example"> js@y.example </a> '
        "(J.S.)</p>",
        '<p>Correspondence: Kate Jones, <a href="mailto:js@y.example"><span>js@y.example'
        "</span></a> (J.S.)</p>",
        "<p>Correspondence: Kate Jones "
        + "" * 12
        + '<a href="mailto:js@y.example">John Smith</a></p>',
    ],
)
def test_link_spans_survive_whitespace_nesting_and_marker_chars(body: str) -> None:
    (candidate,) = parse_citation_page(_page(body)).candidates
    assert candidate.author_positions == (2,)


# M1, M2 — running text and mixed-case domains


def test_running_text_is_not_a_person() -> None:
    def owner(text: str, address: str, names: list[str]) -> int | None:
        start = text.index(address)
        people = [Person(i + 1, n) for i, n in enumerate(names)]
        return attribute_spans(text, [(start, start + len(address))], people)[0][0]

    assert (
        owner(
            "Correspondence may be sent to Lee at hl@x.example",
            "hl@x.example",
            ["May Lee", "Hyun Lee"],
        )
        is None
    )
    assert (
        owner(
            "Correspondence: Kate Brown and John Smith, kb@x.example",
            "kb@x.example",
            ["Kate Smith", "Mark Jones"],
        )
        is None
    )
    assert owner("Correspondence: JOHN SMITH, js@x.example", "js@x.example", ["John Smith"]) == 1
    assert (
        owner("Correspondence: John Q. Public, jp@x.example", "jp@x.example", ["John Public"]) == 1
    )


@pytest.mark.parametrize(
    "address", ["J.Smith@LaTrobe.edu.au", "kj@cs.McGill.ca", "a.b@UniMelb.edu.au", "a@X.EXAMPLE"]
)
def test_mixed_case_domains_are_kept(address: str) -> None:
    assert find_addresses(f"E-mail: {address}") == [(8, address)]

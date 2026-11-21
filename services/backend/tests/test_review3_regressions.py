"""Regressions for the third independent review (2026-11-15)."""

import time

from emailmonitor.discovery.document_intake import extract_document
from emailmonitor.extraction.attribution import Person, attribute_spans, find_addresses
from emailmonitor.extraction.citation_meta import parse_citation_page
from emailmonitor.extraction.jats import parse_jats_xml
from emailmonitor.extraction.pdf_contacts import parse_pdf_contacts
from emailmonitor.sources.openaccess import PmcIdentifier
from pdf_fixture_builder import document

PMC = PmcIdentifier(value="PMC7700001")


def _author(given: str, surname: str, extra: str = "") -> str:
    return (
        f'<contrib contrib-type="author"><name><surname>{surname}</surname>'
        f"<given-names>{given}</given-names></name>{extra}</contrib>"
    )


def _jats(contribs: str, notes: str) -> bytes:
    return (
        '<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>'
        f"<contrib-group>{contribs}</contrib-group><author-notes>{notes}</author-notes>"
        "</article-meta></front></article>"
    ).encode()


def _page(authors: list[str], body: str) -> bytes:
    metas = "".join(f'<meta name="citation_author" content="{a}">' for a in authors)
    return (
        f'<html><head><meta name="citation_title" content="T">{metas}</head>'
        f"<body><article>{body}</article></body></html>"
    ).encode()


def _pdf(*lines: str) -> bytes:
    return document([[(72.0, 740.0 - 14 * i, 9.0, t) for i, t in enumerate(lines)]])


def _owner(text: str, address: str, names: list[str]) -> int | None:
    start = text.index(address)
    people = [Person(i + 1, n) for i, n in enumerate(names)]
    return attribute_spans(text, [(start, start + len(address))], people)[0][0]


# 1 — titles are not initials


def test_titles_never_act_as_initials() -> None:
    assert (
        _owner("Correspondence: Dr. Kim, kim@x.example", "kim@x.example", ["Daniel Kim", "Min Kim"])
        is None
    )
    assert (
        _owner(
            "Correspondence: Mr. Smith, s@x.example", "s@x.example", ["Mary Smith", "Peter Smith"]
        )
        is None
    )
    obs = parse_jats_xml(
        _jats(
            _author("Thomas", "Brown") + _author("Kate", "Brown"),
            "<corresp>Correspondence to Dr Brown, <email>brown@lab.example</email></corresp>",
        ),
        PMC,
    )
    assert obs.candidates[0].author_positions == []
    page = parse_citation_page(
        _page(
            ["Brown, Kate", "Brown, Mark"],
            '<p>Correspondence: Ms. Brown, <a href="mailto:kb@lab.example">kb@lab.example</a></p>',
        )
    )
    assert page.candidates[0].author_positions == ()


# 2 — a shared "E-mail addresses" clause asserts no role


def test_shared_email_footnote_does_not_spread_role_jats() -> None:
    contribs = (
        _author("John", "Smith", '<xref ref-type="corresp" rid="c1"/>')
        + _author("Mary", "Jones")
        + _author("Kate", "Brown")
    )
    note = (
        '<corresp id="c1">Corresponding author. E-mail addresses: '
        "<email>js@x.example</email> (J. Smith), <email>mj@y.example</email> (M. Jones), "
        "<email>kb@z.example</email> (K. Brown).</corresp>"
    )
    obs = parse_jats_xml(_jats(contribs, note), PMC)
    assert [a.corresponding for a in obs.authors] == [True, False, False]
    owners = {c.raw_address: c.author_positions for c in obs.candidates}
    assert owners == {"js@x.example": [1], "mj@y.example": [2], "kb@z.example": [3]}


def test_shared_email_footnote_does_not_spread_role_html_and_pdf() -> None:
    page = parse_citation_page(
        _page(
            ["Smith, John", "Jones, Mary"],
            "<p>Corresponding author. E-mail addresses: "
            '<a href="mailto:js@x.example">js@x.example</a> (J. Smith), '
            '<a href="mailto:mj@y.example">mj@y.example</a> (M. Jones).</p>',
        )
    )
    assert all(a.corresponding is not True for a in page.authors)
    assert {c.association_basis for c in page.candidates} == {"email_block_surname"}
    result = extract_document(
        _pdf(
            "Corresponding author. E-mail addresses: js@x.example (J. Smith), "
            "mj@y.example (M. Jones)."
        ),
        known_authors=["John Smith", "Mary Jones"],
    )
    assert {c.email: c.author_name for c in result.contacts} == {
        "js@x.example": "John Smith",
        "mj@y.example": "Mary Jones",
    }
    assert all(not c.is_corresponding_author for c in result.contacts)


# 3, 15, 16 — HTML link positions and link text


def test_link_position_is_the_links_own() -> None:
    page = parse_citation_page(
        _page(
            ["Jones, Mary", "Smith, John"],
            "<p>Correspondence: Mary Jones (Email), John Smith "
            '(<a href="mailto:js@x.example">Email</a>)</p>',
        )
    )
    (candidate,) = page.candidates
    assert candidate.author_positions != (1,)


def test_name_text_links_are_attributed_by_their_text() -> None:
    page = parse_citation_page(
        _page(
            ["Smith, John", "Jones, Mary"],
            '<p>Correspondence: <a href="mailto:js@x.example">John Smith</a>; '
            '<a href="mailto:mj@y.example">Mary Jones</a></p>',
        )
    )
    assert {c.raw_address: c.author_positions for c in page.candidates} == {
        "js@x.example": (1,),
        "mj@y.example": (2,),
    }


def test_visible_address_differing_from_target_is_unmatched() -> None:
    page = parse_citation_page(
        _page(
            ["Smith, John"],
            '<p>Correspondence: John Smith, <a href="mailto:mj@y.example">js@x.example</a></p>',
        )
    )
    (candidate,) = page.candidates
    assert candidate.raw_address == "mj@y.example"
    assert candidate.author_positions == ()


# 4, 5, 6, 7, 8, 9 — never sliced, joined or altered


def test_line_wrapped_pdf_addresses_are_not_reported_cut() -> None:
    for lines in (
        ("*Correspondence: John Smith, jsmith@med.harvard.", "edu; other text"),
        ("*Correspondence: John Smith, jsmith@chem.uni-", "versity.example"),
        ("*Correspondence: John Smith, jsmith@chem.uni­", "versity.example"),
    ):
        obs = parse_pdf_contacts(_pdf(*lines), known_authors=["John Smith"])
        assert [c.raw_address for c in obs.candidates] == [], lines
        assert obs.possibly_wrapped_addresses >= 1


def test_sentence_final_address_is_still_reported() -> None:
    obs = parse_pdf_contacts(
        _pdf("Correspondence: John Smith, js@uni.example.", "Received 2026"),
        known_authors=["John Smith"],
    )
    assert [c.raw_address for c in obs.candidates] == ["js@uni.example"]


def test_superscript_markers_are_not_address_text() -> None:
    obs = parse_pdf_contacts(
        _pdf("E-mail: ¹js@uni.example, ²mj@uni.example", "Contact: kb@uni.example¹")
    )
    assert [c.raw_address for c in obs.candidates] == [
        "js@uni.example",
        "mj@uni.example",
        "kb@uni.example",
    ]


def test_marker_and_separator_symbols_end_the_token() -> None:
    text = "Correspondence: John Smith *js@uni.example"
    assert find_addresses(text) == [(text.index("js@"), "js@uni.example")]
    assert [a for _s, a in find_addresses("Phone: 555-1234|js@x.example")] == ["js@x.example"]


def test_run_on_and_capped_tokens_are_rejected() -> None:
    assert find_addresses("js@uni.eduTel.: +1 555") == []
    hostile = "a@" + "cccccccc" + "ab.cd--ef." * 30 + "com"
    assert find_addresses(hostile) == []


# 10 — bounded time


def test_large_note_with_many_authors_is_fast() -> None:
    contribs = "".join(_author(f"G{i}", f"Surname{i}") for i in range(100))
    note = "<corresp>" + "G x " * 250_000 + "<email>a@b.example</email></corresp>"
    started = time.perf_counter()
    parse_jats_xml(_jats(contribs, note), PMC)
    assert time.perf_counter() - started < 10


def test_nested_notes_are_not_reprocessed() -> None:
    contribs = "".join(_author(f"G{i}", f"Surname{i}") for i in range(100))
    note = "G x " * 6000 + "<email>a@b.example</email>"
    for _ in range(40):
        note = f"<corresp>{note}</corresp>"
    started = time.perf_counter()
    obs = parse_jats_xml(_jats(contribs, note), PMC)
    assert time.perf_counter() - started < 10
    assert [c.raw_address for c in obs.candidates] == ["a@b.example"]


# 11, 12, 13, 14 — clear misses


def test_role_only_labels_do_not_block_name_matching() -> None:
    text = (
        "John Smith, js@x.example (corresponding author); "
        "Mary Jones, mj@y.example (corresponding author)"
    )
    people = [Person(1, "John Smith"), Person(2, "Mary Jones")]
    spans = [(s, s + len(a)) for s, a in find_addresses(text)]
    assert [o for o, _k in attribute_spans(text, spans, people)] == [1, 2]


def test_nature_initials_before_email() -> None:
    text = (
        "Correspondence and requests for materials should be addressed to A.B. "
        "(email: ab@x.example) or C.D. (email: cd@y.example)."
    )
    people = [Person(1, "Alice Baker"), Person(2, "Carl Dunn")]
    spans = [(s, s + len(a)) for s, a in find_addresses(text)]
    assert attribute_spans(text, spans, people) == [(1, "initials"), (2, "initials")]


def test_hyphenated_initials_do_not_cross_match() -> None:
    text = "J.-H. Kim, jhkim@x.example; M.-J. Kim, mjkim@y.example"
    people = [Person(1, "Ji-Hoon Kim"), Person(2, "Min-Jung Kim")]
    spans = [(s, s + len(a)) for s, a in find_addresses(text)]
    assert [o for o, _k in attribute_spans(text, spans, people)] == [1, 2]


def test_plain_text_address_next_to_structured_email_is_reported() -> None:
    obs = parse_jats_xml(
        _jats(
            _author("John", "Smith") + _author("Mary", "Jones"),
            "<corresp>Correspondence: John Smith, <email>js@x.example</email>; "
            "Mary Jones, mj@y.example</corresp>",
        ),
        PMC,
    )
    owners = {c.raw_address: c.author_positions for c in obs.candidates}
    assert owners == {"js@x.example": [1], "mj@y.example": [2]}

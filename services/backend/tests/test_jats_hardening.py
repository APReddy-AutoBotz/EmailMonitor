"""Role, association-basis and parser-safety tests for JATS extraction (OA-012)."""

from pathlib import Path

import pytest
from emailmonitor.extraction.jats import clean_address, parse_jats_xml
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.openaccess import PmcIdentifier

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
PMC = PmcIdentifier(value="PMC7700001")


def _article(meta: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<article xmlns:xlink="http://www.w3.org/1999/xlink"><front>'
        "<journal-meta><journal-title>Synthetic</journal-title></journal-meta>"
        f"<article-meta>{meta}</article-meta></front></article>"
    ).encode()


def _author(given: str, surname: str, extra: str = "", attrs: str = "") -> str:
    return (
        f'<contrib contrib-type="author" {attrs}><name><surname>{surname}</surname>'
        f"<given-names>{given}</given-names></name>{extra}</contrib>"
    )


def test_rich_fixture_roles_and_bases() -> None:
    obs = parse_jats_xml((FIXTURES / "jats" / "usher-base-editing.xml").read_bytes(), PMC)

    assert obs.article_pmcid == "PMC7700001"
    assert obs.publication_date == "2026-02-04"  # epub preferred over collection year
    assert obs.keywords == ["base editing", "Usher syndrome", "AAV delivery"]
    assert obs.license_url == "https://creativecommons.org/licenses/by/4.0/"
    assert obs.title == "In vivo base editing rescues sensory defects in Usher syndrome mice"

    names = [a.display_name for a in obs.authors]
    assert names == ["Aiko Tanaka", "Rahul Mehta", "Lucia Ferreira", "Tomasz Nowak"]
    # Equal-contribution footnotes and a contrib email do not assert correspondence.
    assert [a.corresponding for a in obs.authors] == [False, False, True, True]
    assert obs.authors[0].orcid == "0000-0000-0000-001X"
    assert obs.authors[3].affiliations == [
        "Department of Medical Genetics, Jagiellonian Research Centre, Kraków, Poland"
    ]

    by_address = {c.raw_address: c for c in obs.candidates}
    assert set(by_address) == {
        "r.mehta@bio.pune.example",
        "lucia.ferreira@neuro.lisbon.example",
        "t.nowak@genetics.krakow.example",
        "core-lab@genetics.krakow.example",
    }
    assert by_address["r.mehta@bio.pune.example"].association_basis == "contrib_email"
    assert by_address["r.mehta@bio.pune.example"].author_positions == [2]
    assert by_address["lucia.ferreira@neuro.lisbon.example"].author_positions == [3]
    assert by_address["lucia.ferreira@neuro.lisbon.example"].association_basis == (
        "corresp_initials"
    )
    assert by_address["t.nowak@genetics.krakow.example"].author_positions == [4]
    lab = by_address["core-lab@genetics.krakow.example"]
    assert lab.association_basis == "unmatched"
    assert lab.author_positions == []
    assert lab.association_status == "unmatched"
    # Editors and untrusted body text never yield candidates.
    assert "handling.editor@journal.example" not in by_address
    assert "attacker@evil.example" not in by_address


def test_affiliation_text_keeps_document_order_and_drops_label() -> None:
    obs = parse_jats_xml(
        (FIXTURES / "jats" / "plos-sample.xml").read_bytes(), PmcIdentifier(value="PMC10293847")
    )
    assert obs.authors[0].affiliations == [
        "Department of Molecular Genetics, University of Cambridge, Cambridge, United Kingdom"
    ]


def test_contrib_email_alone_is_not_correspondence_and_unknown_role_is_none() -> None:
    meta = _author("Ana", "Silva", "<email>ana@lab.example</email>") + _author("Ben", "Ode")
    obs = parse_jats_xml(_article(f"<contrib-group>{meta}</contrib-group>"), PMC)
    assert [a.corresponding for a in obs.authors] == [None, None]
    assert obs.candidates[0].association_basis == "contrib_email"
    assert obs.candidates[0].author_positions == [1]


def test_unreferenced_note_name_proximity_marks_author() -> None:
    meta = (
        "<contrib-group>"
        + _author("Ana", "Silva")
        + _author("Ben", "Ode")
        + "</contrib-group><author-notes><corresp>Correspondence to Ben Ode: "
        "<email>b.ode@lab.example</email></corresp></author-notes>"
    )
    obs = parse_jats_xml(_article(meta), PMC)
    (candidate,) = obs.candidates
    assert candidate.author_positions == [2]
    assert candidate.association_basis == "corresp_name_proximity"
    assert [a.corresponding for a in obs.authors] == [None, True]


def test_shared_note_without_markers_stays_unmatched() -> None:
    meta = (
        "<contrib-group>"
        + _author("Ana", "Silva", '<xref ref-type="corresp" rid="c1"/>')
        + _author("Ben", "Ode", '<xref ref-type="corresp" rid="c1"/>')
        + '</contrib-group><author-notes><corresp id="c1">E-mail: '
        "<email>office@lab.example</email></corresp></author-notes>"
    )
    obs = parse_jats_xml(_article(meta), PMC)
    (candidate,) = obs.candidates
    assert candidate.association_basis == "unmatched"
    assert candidate.author_positions == []


def test_footnote_correspondence_and_mailto_uri() -> None:
    meta = (
        "<contrib-group>"
        + _author("Ana", "Silva", '<xref ref-type="fn" rid="fn1">*</xref>')
        + _author("Ben", "Ode")
        + '</contrib-group><author-notes><fn fn-type="corresp" id="fn1"><p>Contact: '
        '<uri xlink:href="mailto:ana.silva@lab.example">ana.silva@lab.example</uri>.</p></fn>'
        "</author-notes>"
    )
    obs = parse_jats_xml(_article(meta), PMC)
    assert [a.corresponding for a in obs.authors] == [True, False]
    (candidate,) = obs.candidates
    assert candidate.raw_address == "ana.silva@lab.example"
    assert candidate.association_basis == "corresp_xref"
    assert candidate.author_positions == [1]


def test_text_fallback_strips_trailing_punctuation() -> None:
    meta = (
        "<contrib-group>"
        + _author("Ana", "Silva", "", 'corresp="yes"')
        + "</contrib-group><author-notes><corresp>Email: ana@lab.example.</corresp>"
        "</author-notes>"
    )
    obs = parse_jats_xml(_article(meta), PMC)
    assert obs.candidates[0].raw_address == "ana@lab.example"
    assert obs.candidates[0].association_basis == "sole_corresponding_author"


def test_group_member_contribs_do_not_take_positions() -> None:
    meta = (
        '<contrib-group><contrib contrib-type="author"><collab>Synthetic Consortium'
        "<contrib-group>"
        + _author("Cy", "Member")
        + "</contrib-group></collab></contrib>"
        + _author("Ana", "Silva")
        + "</contrib-group>"
    )
    obs = parse_jats_xml(_article(meta), PMC)
    assert [(a.display_name, a.author_kind) for a in obs.authors] == [
        ("Synthetic Consortium", "group"),
        ("Ana Silva", "person"),
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("mailto:a.b@lab.example", "a.b@lab.example"),
        ("<a@lab.example>", "a@lab.example"),
        ("a@lab.example;", "a@lab.example"),
        ("a@@lab.example", None),
        ("a@lab", None),
        ("a@-lab.example", None),
        ("two a@lab.example b@lab.example", None),
    ],
)
def test_clean_address(value: str, expected: str | None) -> None:
    assert clean_address(value) == expected


def test_internal_dtd_subset_is_refused() -> None:
    data = (
        b'<?xml version="1.0"?><!DOCTYPE article [<!ENTITY a "aaaa">]>'
        b"<article><front><article-meta/></front></article>"
    )
    with pytest.raises(FetchDenied, match="jats_internal_dtd_subset_denied"):
        parse_jats_xml(data, PMC)


def test_billion_laughs_is_refused_before_expansion() -> None:
    entities = "".join(
        f'<!ENTITY l{i} "{"&l" + str(i - 1) + ";" * 10 if i else "lol"}">' for i in range(10)
    )
    data = f'<?xml version="1.0"?><!DOCTYPE a [{entities}]><a>&l9;</a>'.encode()
    with pytest.raises(FetchDenied):
        parse_jats_xml(data, PMC)


def test_external_entity_is_never_resolved() -> None:
    data = b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'
    with pytest.raises(FetchDenied):
        parse_jats_xml(data, PMC)


def test_candidate_cap_is_bounded() -> None:
    emails = "".join(f"<email>user{i}@lab.example</email>" for i in range(150))
    meta = (
        "<contrib-group>"
        + _author("Ana", "Silva", "", 'corresp="yes"')
        + f"</contrib-group><author-notes><corresp>{emails}</corresp></author-notes>"
    )
    obs = parse_jats_xml(_article(meta), PMC)
    assert len(obs.candidates) == 100

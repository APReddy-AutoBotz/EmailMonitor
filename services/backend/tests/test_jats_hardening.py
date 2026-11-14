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


# --- Regressions from the independent review (2026-11-14) -------------------


def _two_authors(extra_smith: str = "", extra_jones: str = "", notes: str = "") -> bytes:
    meta = (
        "<contrib-group>"
        + _author("John", "Smith", extra_smith)
        + _author("Kate", "Jones", extra_jones)
        + f"</contrib-group><author-notes>{notes}</author-notes>"
    )
    return _article(meta)


def _owner(obs: object, address: str) -> tuple[list[int], str]:
    candidate = next(c for c in obs.candidates if c.raw_address == address)  # type: ignore[attr-defined]
    return candidate.author_positions, candidate.association_basis


def test_full_name_label_after_each_address_is_respected() -> None:
    obs = parse_jats_xml(
        _two_authors(
            notes="<corresp>E-mail addresses: <email>smith@x.example</email> (J. Smith), "
            "<email>jones@y.example</email> (K. Jones).</corresp>"
        ),
        PMC,
    )
    assert _owner(obs, "smith@x.example") == ([1], "corresp_name_proximity")
    assert _owner(obs, "jones@y.example") == ([2], "corresp_name_proximity")


def test_label_naming_nobody_never_falls_back_to_previous_text() -> None:
    obs = parse_jats_xml(
        _two_authors(
            notes="<corresp>Smith: <email>a@x.example</email> (lab office), "
            "<email>b@x.example</email></corresp>"
        ),
        PMC,
    )
    assert _owner(obs, "a@x.example") == ([], "unmatched")
    assert _owner(obs, "b@x.example") == ([], "unmatched")


def test_contrib_email_does_not_become_corresponding_role() -> None:
    obs = parse_jats_xml(
        _two_authors(
            extra_jones="<email>kate@y.example</email>",
            notes="<corresp>Correspondence should be addressed via the journal office.</corresp>",
        ),
        PMC,
    )
    assert _owner(obs, "kate@y.example") == ([2], "contrib_email")
    assert obs.authors[1].corresponding is not True


def test_sole_corresponding_author_does_not_absorb_other_addresses() -> None:
    obs = parse_jats_xml(
        _two_authors(
            extra_smith="",
            notes='<fn fn-type="corresp"><p>office@inst.example; kate.jones@y.example</p></fn>',
        ).replace(
            b'<contrib contrib-type="author" >', b'<contrib contrib-type="author" corresp="yes">', 1
        ),
        PMC,
    )
    assert obs.authors[0].corresponding is True
    assert _owner(obs, "office@inst.example") == ([], "unmatched")
    assert _owner(obs, "kate.jones@y.example") == ([], "unmatched")


def test_single_xref_note_with_labelled_second_address() -> None:
    obs = parse_jats_xml(
        _two_authors(
            extra_smith='<xref ref-type="corresp" rid="c1"/>',
            notes='<corresp id="c1"><email>smith@x.example</email>; Kate Jones, '
            "<email>kj@y.example</email> (K.J.)</corresp>",
        ),
        PMC,
    )
    assert _owner(obs, "kj@y.example") == ([2], "corresp_initials")
    assert _owner(obs, "smith@x.example") == ([], "unmatched")


def test_sole_address_label_conflicting_with_xref_is_unmatched() -> None:
    obs = parse_jats_xml(
        _two_authors(
            extra_smith='<xref ref-type="corresp" rid="c1"/>',
            notes='<corresp id="c1"><email>kj@y.example</email> (K. Jones)</corresp>',
        ),
        PMC,
    )
    assert _owner(obs, "kj@y.example") == ([], "unmatched")


def test_addresses_keep_document_order_beyond_ten() -> None:
    emails = "".join(f"<email>u{i}@lab.example</email> " for i in range(12))
    meta = (
        "<contrib-group>"
        + _author("Ana", "Silva", "", 'corresp="yes"')
        + f"</contrib-group><author-notes><corresp>{emails}</corresp></author-notes>"
    )
    obs = parse_jats_xml(_article(meta), PMC)
    assert [c.raw_address for c in obs.candidates] == [f"u{i}@lab.example" for i in range(12)]


def test_group_member_addresses_are_not_the_groups() -> None:
    meta = (
        '<contrib-group><contrib contrib-type="author"><collab>Big Consortium'
        "<contrib-group>"
        + _author("Ann", "Lee", "<email>ann.lee@z.example</email>")
        + "</contrib-group></collab></contrib></contrib-group>"
    )
    obs = parse_jats_xml(_article(meta), PMC)
    assert all(c.association_basis != "contrib_email" for c in obs.candidates)


def test_more_than_100_authors_is_truncated_not_crashing() -> None:
    contribs = "".join(_author(f"G{i}", f"S{i}") for i in range(101))
    obs = parse_jats_xml(_article(f"<contrib-group>{contribs}</contrib-group>"), PMC)
    assert len(obs.authors) == 100
    assert obs.authors_truncated is True


def test_hostile_address_text_is_linear_time() -> None:
    import time

    meta = (
        "<contrib-group>"
        + _author("Ana", "Silva", "", 'corresp="yes"')
        + "</contrib-group><author-notes><corresp>"
        + "a" * 400_000
        + "</corresp></author-notes>"
    )
    started = time.perf_counter()
    obs = parse_jats_xml(_article(meta), PMC)
    assert time.perf_counter() - started < 5
    assert obs.candidates == []


def test_find_addresses_bounds() -> None:
    from emailmonitor.extraction.jats import find_addresses

    assert find_addresses("x" * 100 + "@lab.example") == []  # local part over 64
    assert find_addresses("mail ana@lab.example, ben@lab.example.") == [
        (5, "ana@lab.example"),
        (22, "ben@lab.example"),
    ]
    assert find_addresses("{amara,office}@lab.example") == [] or all(
        "{" not in a and "}" not in a for _s, a in find_addresses("{amara,office}@lab.example")
    )

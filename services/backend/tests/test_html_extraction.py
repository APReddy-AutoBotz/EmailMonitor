"""Observed synthetic facts, not fixture expected-output substitution."""

from pathlib import Path

import pytest
from emailmonitor.config import Settings
from emailmonitor.extraction.html import ArticleObservation, parse_article
from emailmonitor.fetching.safety import FetchDenied, IsolationUnavailable

ROOT = Path(__file__).resolve().parents[3]
SETTINGS = Settings(environment="test", fixture_mode=True)
ORIGIN = "https://synthetic.publisher.example"


def payload(name: str) -> bytes:
    return (ROOT / "fixtures/html" / name).read_bytes()


def parse(
    name: str, data: bytes | None = None, *, browser_dom: bool = False, depth: int = 0
) -> ArticleObservation:
    return parse_article(
        SETTINGS,
        ORIGIN + "/" + name,
        payload(name) if data is None else data,
        browser_dom=browser_dom,
        depth=depth,
    )


def test_article_a_first_and_corresponding_are_separate_observed_facts() -> None:
    result = parse("article-a.html")
    assert [(a.display_name, a.first, a.corresponding) for a in result.authors] == [
        ("Mira Rao", True, None),
        ("Alex Chen", False, True),
    ]
    assert [c.raw_address for c in result.candidates] == ["alex.chen@example.org"]
    assert result.candidates[0].author_positions == [2]
    assert result.candidates[0].association_status == "needs_review"
    assert result.candidates[0].technical_status == "not_checked"
    assert result.candidates[0].delivery_status == "unverified"
    assert result.candidates[0].outreach_eligibility == "not_assessed"
    assert result.identity_association_implemented is False
    assert all(c.evidence.locator and c.evidence.excerpt for c in result.candidates)
    assert [m.evidence.kind for m in result.metadata if m.field == "title"] == [
        "structured_metadata",
        "article_dom",
    ]


def test_article_b_preserves_two_correspondents_and_distinct_addresses() -> None:
    result = parse("article-b.html")
    assert [(a.first, a.corresponding) for a in result.authors] == [(True, True), (False, True)]
    assert [(c.raw_address, c.author_positions) for c in result.candidates] == [
        ("ravi.das@example.org", [1]),
        ("noor.ibrahim@example.org", [2]),
    ]


def test_static_tooltip_does_not_read_javascript_or_fabricate_contact() -> None:
    result = parse("tooltip.html")
    assert result.candidates == [] and result.status == "requires_browser"
    assert result.browser_plan == "synthetic-tooltip-v1"
    assert result.authors[0].corresponding is True
    revealed = payload("tooltip.html").replace(
        b"</div>", b'<span id="contact-tooltip" role="tooltip">elena.park@example.org</span></div>'
    )
    observed = parse("tooltip.html", revealed, browser_dom=True)
    assert observed.route == "browser_dom" and observed.status == "observed"
    assert [(c.raw_address, c.evidence.kind) for c in observed.candidates] == [
        ("elena.park@example.org", "browser_dom")
    ]
    assert observed.browser_plan is None


def test_no_contact_is_not_failure_or_invented_email() -> None:
    result = parse("no-contact.html")
    assert result.status == "no_contact" and result.candidates == []
    assert result.authors[0].display_name == "Leena Shah"
    assert result.authors[0].corresponding is None
    assert not any(m.field in {"journal", "publication_date", "doi"} for m in result.metadata)


@pytest.mark.parametrize(
    "wrapper",
    [
        "<footer>{}</footer>",
        "<aside>{}</aside>",
        "<nav>{}</nav>",
        "<form>{}</form>",
        '<div class="references">{}</div>',
        '<div id="references">{}</div>',
        "<div hidden>{}</div>",
        '<div aria-hidden="true">{}</div>',
        '<div style="display: none">{}</div>',
        '<div style="visibility: hidden">{}</div>',
        "<template>{}</template>",
        "<script>{}</script>",
        "<style>{}</style>",
    ],
)
def test_hostile_support_reference_hidden_or_script_contacts_are_excluded(wrapper: str) -> None:
    injection = wrapper.format('<a href="mailto:excluded@example.org">excluded@example.org</a>')
    data = payload("article-a.html").replace(b"</p></main>", injection.encode() + b"</p></main>")
    assert [c.raw_address for c in parse("article-a.html", data).candidates] == [
        "alex.chen@example.org"
    ]


def test_mailto_decodes_address_but_not_subject_body_or_encoded_query() -> None:
    for target in (
        "Alex.Chen%2Bpaper@example.org?subject=secret@example.org&body=wrong@example.org",
        "Alex.Chen@example.org%3Fbody=wrong@example.org",
    ):
        data = payload("article-a.html").replace(
            b"mailto:alex.chen@example.org", ("mailto:" + target).encode()
        )
        result = parse("article-a.html", data)
        assert len(result.candidates) == 1
        assert result.candidates[0].raw_address in {
            "Alex.Chen+paper@example.org",
            "Alex.Chen@example.org",
        }


def test_connector_public_attribute_is_observed_but_credential_attributes_are_not() -> None:
    data = payload("article-a.html").replace(
        b'<a href="mailto:alex.chen@example.org">alex.chen@example.org</a>',
        b'<span title="alex.chen@example.org" data-token="secret@example.org">contact</span>',
    )
    result = parse("article-a.html", data)
    assert [(c.raw_address, c.evidence.kind) for c in result.candidates] == [
        ("alex.chen@example.org", "public_attribute")
    ]


def test_superscript_equal_contribution_is_not_correspondence_role() -> None:
    data = payload("no-contact.html").replace(b"Leena Shah <span", b"Leena Shah <sup>*</sup><span")
    result = parse("no-contact.html", data)
    assert result.authors[0].display_name == "Leena Shah"
    assert result.authors[0].corresponding is None


def test_negation_or_name_substring_cannot_establish_corresponding_role() -> None:
    for replacement in (
        b"Not Corresponding author: Alex Chen",
        b"Corresponding author: Alex Chenoweth",
    ):
        data = payload("article-a.html").replace(b"Corresponding author: Alex Chen", replacement)
        assert parse("article-a.html", data).authors[1].corresponding is None


def test_same_name_authors_remain_distinct_and_ambiguous() -> None:
    data = payload("article-a.html").replace(b"Mira Rao", b"Alex Chen")
    result = parse("article-a.html", data)
    assert len(result.authors) == 2
    assert [author.first for author in result.authors] == [True, False]
    assert all(author.corresponding is None for author in result.authors)
    assert result.candidates[0].author_positions == [1, 2]
    assert result.candidates[0].association_status == "needs_review"


def test_unicode_names_addresses_and_explicit_group_identifier_are_preserved() -> None:
    data = (
        payload("article-a.html")
        .replace(b"Mira Rao", "Míra Rao".encode())
        .replace(b"alex.chen@example.org", "Alex.Chén@exämple.org".encode())
    )
    result = parse("article-a.html", data)
    assert result.authors[0].display_name == "Míra Rao"
    assert result.candidates[0].raw_address == "Alex.Chén@exämple.org"
    assert result.candidates[0].technical_status == "not_checked"
    grouped = payload("no-contact.html").replace(
        b"<li>", b'<li data-author-kind="group" data-orcid="0000-0000-0000-000X">'
    )
    author = parse("no-contact.html", grouped).authors[0]
    assert author.author_kind == "group" and author.orcid == "0000-0000-0000-000X"


def test_owned_browser_fixture_acquisition_digest_and_static_waterfall() -> None:
    import hashlib

    from emailmonitor.extraction.fixture import BROWSER_ACQUISITION_DIGEST
    from run_browser_acceptance import PAGE

    assert hashlib.sha256(PAGE).hexdigest() == BROWSER_ACQUISITION_DIGEST
    result = parse("tooltip.html", PAGE)
    assert result.status == "requires_browser" and result.candidates == []
    assert result.authors[0].display_name == "Elena Park"


def test_followups_are_scoped_candidates_never_scheduled_and_depth_bounded() -> None:
    data = payload("article-a.html").replace(
        b"</main>",
        b'<a rel="full-text" href="/article-b.html">Full text</a><a href="https://elsewhere.example/reference">Reference</a></main>',
    )
    result = parse("article-a.html", data)
    assert len(result.follow_up) == 1
    assert result.follow_up[0].url == ORIGIN + "/article-b.html"
    assert result.follow_up[0].scheduled is False and result.follow_up[0].depth == 1
    assert parse("article-a.html", data, depth=2).follow_up == []
    with pytest.raises(FetchDenied):
        parse(
            "article-a.html", data.replace(b"/article-b.html", b"https://elsewhere.example/article")
        )


@pytest.mark.parametrize(
    "data",
    [
        b"x" * 32769,
        b"\xff",
        b'<main><ol class="authors"><li>A</ol></main>',
        b"<main></main>",
        b"<div>" * 66,
        b"<main " + b'x="a" ' * 36 + b">",
        b'<main id="a" id="b">',
    ],
)
def test_parser_limits_and_selector_ambiguity_fail_closed(data: bytes) -> None:
    with pytest.raises(FetchDenied):
        parse("article-a.html", data)


def test_production_unknown_routes_and_extra_observation_fields_refused() -> None:
    with pytest.raises(IsolationUnavailable):
        parse_article(Settings(), ORIGIN + "/article-a.html", payload("article-a.html"))
    with pytest.raises(FetchDenied):
        parse_article(SETTINGS, ORIGIN + "/unknown.html", payload("article-a.html"))
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ArticleObservation.model_validate(
            {**parse("article-a.html").model_dump(), "accepted": True}
        )


def test_user_zero_link_budget_cannot_offer_followup() -> None:
    data = payload("article-a.html").replace(
        b"</main>", b'<a rel="full-text" href="/article-b.html">Full text</a></main>'
    )
    result = parse_article(SETTINGS, ORIGIN + "/article-a.html", data, max_depth=0)
    assert result.follow_up == []


def test_metadata_precedence_keeps_conflicts_and_missing_fields_null() -> None:
    data = payload("article-a.html").replace(
        b"<h1>Synthetic myocardial infarction study A</h1>",
        b"<h1>Different observed DOM title</h1>",
    )
    result = parse("article-a.html", data)
    assert result.preferred_metadata.title == "Synthetic myocardial infarction study A"
    assert result.preferred_metadata.doi == "10.9999/synthetic.article-a"
    assert [fact.value for fact in result.metadata if fact.field == "title"] == [
        "Synthetic myocardial infarction study A",
        "Different observed DOM title",
    ]
    absent = parse("no-contact.html").preferred_metadata
    assert absent.journal is absent.publication_date is absent.doi is None

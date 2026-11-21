"""Regressions for the independent review of the OA branch (2026-11-14).

Each test reproduces a reported defect: wrong-person attribution, fabricated
roles, whole-run failure on one hostile article, quadratic parsing, merge
duplication, ORCID bridging through shared mailboxes, export aborts.
"""

import time

import pytest
from emailmonitor.discovery.document_intake import extract_document
from emailmonitor.discovery.openaccess_orchestrator import (
    ArticleContext,
    AuthorView,
    ExtractedAcademicContact,
    OpenAccessOrchestrator,
    OpenAlexFixtureGateway,
    build_contact,
)
from emailmonitor.extraction.citation_meta import parse_citation_page
from emailmonitor.extraction.pdf_contacts import parse_pdf_contacts
from emailmonitor.fetching.europepmc import EuropePmcFixtureGateway, EuropePmcRequest
from emailmonitor.results.researchers import build_researcher_profiles, render_researchers_export
from emailmonitor.sources.crossref import CrossrefFixtureGateway, CrossrefQueryPlanner, CrossrefWork
from emailmonitor.sources.europepmc_search import (
    EuropePmcHit,
    EuropePmcSearchFixtureGateway,
    EuropePmcSearchPage,
    EuropePmcSearchRequest,
)
from emailmonitor.sources.openaccess import DoiIdentifier
from emailmonitor.sources.openalex import OpenAlexSearchRequest, OpenAlexWork
from pdf_fixture_builder import document

A, B = "0000-0002-1825-0097", "0000-0000-0000-001X"


def _pdf(*lines: str) -> bytes:
    return document([[(72.0, 740.0 - 14 * i, 9.0, t) for i, t in enumerate(lines)]])


# 2 — PDF "address (Full Name)" lists


def test_pdf_full_name_labels_and_no_role_from_email_list() -> None:
    data = _pdf("E-mail addresses: smith@x.example (J. Smith), jones@y.example (K. Jones).")
    obs = parse_pdf_contacts(data, known_authors=["John Smith", "Kate Jones"])
    owners = {c.raw_address: (c.author_name, c.region) for c in obs.candidates}
    assert owners["smith@x.example"] == ("John Smith", "pdf_email_line")
    assert owners["jones@y.example"] == ("Kate Jones", "pdf_email_line")
    result = extract_document(data, known_authors=["John Smith", "Kate Jones"])
    # An "E-mail addresses:" list labels owners but asserts no correspondence role.
    assert all(c.is_corresponding_author is False for c in result.contacts)


def test_pdf_correspondence_line_still_asserts_role() -> None:
    result = extract_document(
        _pdf("*Correspondence: Kate Jones, jones@y.example"),
        known_authors=["John Smith", "Kate Jones"],
    )
    (contact,) = result.contacts
    assert contact.author_name == "Kate Jones" and contact.is_corresponding_author is True


def test_pdf_long_known_author_name_does_not_crash() -> None:
    long_name = "Kate " + "Q" * 320 + " Jones"
    result = extract_document(
        _pdf("*Correspondence: Jones, jones@y.example"), known_authors=["A B", long_name]
    )
    assert len(result.contacts) == 1


def test_pdf_hostile_text_is_fast() -> None:
    started = time.perf_counter()
    parse_pdf_contacts(_pdf("a" * 5000, "(" + "a," * 2000 + "a"))
    assert time.perf_counter() - started < 5


# 7, 9 — HTML


def test_html_many_mailto_links_are_not_quadratic() -> None:
    links = "".join(f'<a href="mailto:u{i}@lab.example">u{i}</a> ' for i in range(8000))
    html = (
        f'<html><head><meta name="citation_title" content="T"></head><body>{links}</body></html>'
    ).encode()
    started = time.perf_counter()
    parse_citation_page(html)
    assert time.perf_counter() - started < 10


def test_html_tags_after_author_cap_are_not_misattributed() -> None:
    metas = "".join(
        f'<meta name="citation_author" content="Surname{i}, Author{i}">' for i in range(1, 102)
    )
    html = (
        '<html><head><meta name="citation_title" content="T">'
        + metas
        + '<meta name="citation_author_email" content="a101@inst.example"></head></html>'
    ).encode()
    obs = parse_citation_page(html)
    assert len(obs.authors) == 100
    overflow = next(c for c in obs.candidates if c.raw_address == "a101@inst.example")
    assert overflow.association_status == "unmatched" and overflow.author_positions == ()


def test_html_block_with_two_links_and_one_name_does_not_absorb() -> None:
    html = b"""<html><head><meta name="citation_title" content="T">
<meta name="citation_author" content="Haddad, Yusuf">
<meta name="citation_author" content="Lee, Ann">
</head><body><p>Correspondence: Yusuf Haddad, <a href="mailto:y@arid.example">y@arid.example</a>;
lab office <a href="mailto:office@arid.example">office@arid.example</a></p></body></html>"""
    owners = {c.raw_address: c.author_positions for c in parse_citation_page(html).candidates}
    assert owners["y@arid.example"] == (1,)
    assert owners["office@arid.example"] == ()


# 5, 14 — one hostile article must not fail the run


class _HostileSearch(EuropePmcSearchFixtureGateway):
    def search(self, request: EuropePmcSearchRequest) -> EuropePmcSearchPage:
        hits = (
            EuropePmcHit(
                source_id="PMC10293847",
                source="PMC",
                pmcid="PMC10293847",
                title="Good",
                is_open_access=True,
                in_epmc=True,
            ),
            EuropePmcHit(
                source_id="PMC4040404",
                source="PMC",
                pmcid="PMC4040404",
                title="Hostile",
                is_open_access=True,
                in_epmc=True,
            ),
        )
        return EuropePmcSearchPage(hit_count=2, hits=hits)


class _HostileFullText(EuropePmcFixtureGateway):
    def fetch(self, request: EuropePmcRequest):  # type: ignore[no-untyped-def]
        if request.pmcid.value != "PMC4040404":
            return super().fetch(request)
        import hashlib

        from emailmonitor.fetching.europepmc import EuropePmcResponse

        contribs = "".join(
            f'<contrib contrib-type="author"><name><surname>S{i}</surname>'
            f"<given-names>G{i}</given-names></name></contrib>"
            for i in range(3)
        )
        body = (
            "<article><front><article-meta><contrib-group>"
            + contribs
            + "</contrib-group><author-notes><corresp>x@y.example</corresp></author-notes>"
            "<pub-date><year>3025</year></pub-date></article-meta></front></article>"
        ).encode()
        return EuropePmcResponse(
            request=request,
            status_code=200,
            body=body,
            content_digest=hashlib.sha256(body).hexdigest(),
            elapsed_ms=1,
        )


def test_hostile_article_is_isolated_and_bad_year_is_dropped() -> None:
    orchestrator = OpenAccessOrchestrator(
        europe_pmc_gateway=_HostileFullText(),
        europe_pmc_search_gateway=_HostileSearch(),
        reference_year=2026,
    )
    result = orchestrator.discover_and_extract("anything", target_roles="all")
    statuses = {a.work_key: a.status for a in result.articles}
    assert statuses["PMC10293847"] == "contacts_observed"
    hostile = next(a for a in result.articles if a.work_key == "PMC4040404")
    assert hostile.publication_year is None  # 3025 is out of range, not trusted
    assert any(c.email == "marcus.vance@biotech.zurich.example" for c in result.contacts_extracted)


def test_eleven_digit_pmcid_query_is_keyword_not_crash() -> None:
    result = OpenAccessOrchestrator(reference_year=2026).discover_and_extract("PMC12345678901")
    assert result.route_reason == "keyword_full_text_search"


# 8 — merge


class _EpmcOnlyPmc(EuropePmcSearchFixtureGateway):
    def search(self, request: EuropePmcSearchRequest) -> EuropePmcSearchPage:
        if request.query.startswith("DOI:"):
            return EuropePmcSearchPage(hit_count=0, hits=())
        hit = EuropePmcHit(
            source_id="PMC10293847",
            source="PMC",
            pmcid="PMC10293847",
            title="T",
            is_open_access=True,
            in_epmc=True,
        )
        return EuropePmcSearchPage(hit_count=1, hits=(hit,))


class _OpenAlexOnlyDoi(OpenAlexFixtureGateway):
    def search_works(self, request: OpenAlexSearchRequest) -> list[OpenAlexWork]:
        return [
            OpenAlexWork(
                id="https://openalex.org/W12345678",
                doi="https://doi.org/10.5555/oa.plos.3002145",
            )
        ]


class _CrossrefBoth(CrossrefFixtureGateway):
    def search_works(self, planner: CrossrefQueryPlanner) -> tuple[CrossrefWork, ...]:
        return (CrossrefWork(doi=DoiIdentifier(value="10.5555/oa.plos.3002145"), title="T"),)


def test_merge_joins_groups_bridged_by_a_later_record() -> None:
    class _Bridge(_EpmcOnlyPmc):
        def resolve_doi(self, doi: str) -> EuropePmcHit | None:
            return EuropePmcHit(
                source_id="PMC10293847",
                source="PMC",
                pmcid="PMC10293847",
                is_open_access=True,
                in_epmc=True,
            )

    orchestrator = OpenAccessOrchestrator(
        europe_pmc_search_gateway=_Bridge(),
        openalex_gateway=_OpenAlexOnlyDoi(),
        crossref_gateway=_CrossrefBoth(),
        reference_year=2026,
    )
    # OpenAlex's work has only a DOI; Crossref's record carries PMCID (via lookup) and DOI.
    result = orchestrator.discover_and_extract("x", source="all", target_roles="all")
    assert len(result.articles) == 1
    assert set(result.articles[0].found_in) == {"europe-pmc", "openalex", "crossref"}


# 10, 11 — researchers


def _contact(
    address: str,
    orcid: str | None,
    basis: str = "corresp_xref",
    title: str = "T",
    name: str = "Ana Silva",
    doi: str = "10.5555/a.1",
) -> ExtractedAcademicContact:
    context = ArticleContext(
        source="europe-pmc",
        article_key=doi,
        doi=doi,
        pmcid=None,
        title=title,
        journal="J",
        publication_year=2026,
        content_digest="0" * 64,
        full_text_url=None,
    )
    author = AuthorView(
        position=1, display_name=name, kind="person", first=True, corresponding=True, orcid=orcid
    )
    contact = build_contact(
        context,
        address=address,
        author=author,
        association_basis=basis,
        association_status="needs_review",
        evidence_locator="/a",
        evidence_excerpt=address,
        target_roles="all",
        reference_year=2026,
        suppressed_emails=frozenset(),
        suppressed_domains=frozenset(),
    )
    assert contact is not None
    return contact


def test_shared_mailbox_does_not_bridge_two_people() -> None:
    profiles = build_researcher_profiles(
        [
            _contact("smith@x.example", A, name="John Smith"),
            _contact("lab@x.example", A, name="John Smith", doi="10.5555/b"),
            _contact("lab@x.example", B, name="Kate Jones", doi="10.5555/c"),
            _contact("kjones@y.example", B, name="Kate Jones", doi="10.5555/d"),
        ]
    )
    groups = [set(p.emails) for p in profiles]
    assert {"smith@x.example", "kjones@y.example"} not in [
        g & {"smith@x.example", "kjones@y.example"} for g in groups
    ]
    assert not any({"smith@x.example", "kjones@y.example"} <= g for g in groups)


def test_heuristic_association_does_not_link_by_orcid() -> None:
    profiles = build_researcher_profiles(
        [
            _contact("a@x.example", A, basis="corresp_name_proximity"),
            _contact("b@y.example", A, doi="10.5555/b"),
        ]
    )
    assert len(profiles) == 2


def test_researchers_export_withholds_unsafe_rows() -> None:
    profiles = build_researcher_profiles(
        [
            _contact("a@x.example", None, title="-1+1 hostile"),
            _contact("b@y.example", None, doi="10.5555/b"),
        ]
    )
    content, written, withheld = render_researchers_export(profiles)
    assert (written, withheld) == (1, 1)
    assert b"hostile" not in content and b"b@y.example" in content


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/creativecommons.org/licenses/by/",
        "ftp://creativecommons.org/licenses/by/4.0/",
    ],
)
def test_license_requires_creative_commons_host(url: str) -> None:
    from emailmonitor.sources.openaccess import license_category

    assert license_category(url) == "other"

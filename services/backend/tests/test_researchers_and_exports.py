"""Researcher rollups (OA-017), role accounts (OA-018) and export presets (OA-019)."""

import csv
import io

import pytest
from emailmonitor.dev_server import ORG_ID, app
from emailmonitor.discovery.openaccess_orchestrator import (
    ArticleContext,
    AuthorView,
    ExtractedAcademicContact,
    OpenAccessOrchestrator,
    build_contact,
)
from emailmonitor.results.oa_exports import EXPORT_PRESETS, render_export
from emailmonitor.results.outreach import is_role_account
from emailmonitor.results.researchers import build_researcher_profiles, render_researchers_csv
from fastapi.testclient import TestClient

VALID_ORCID = "0000-0002-1825-0097"
OTHER_VALID_ORCID = "0000-0000-0000-001X"


def _contact(
    address: str,
    *,
    name: str | None = "Ana Silva",
    doi: str = "10.5555/a.1",
    year: int | None = 2026,
    title: str = "Paper",
    orcid: str | None = None,
    affiliation: str = "Synthetic University",
    corresponding: bool = True,
    first: bool = False,
    suppressed: frozenset[str] = frozenset(),
) -> ExtractedAcademicContact:
    context = ArticleContext(
        source="europe-pmc",
        article_key=doi,
        doi=doi,
        pmcid=None,
        title=title,
        journal="Synthetic Journal",
        publication_year=year,
        content_digest="0" * 64,
        full_text_url=None,
    )
    author = (
        AuthorView(
            position=2,
            display_name=name,
            kind="person",
            first=first,
            corresponding=corresponding,
            affiliations=(affiliation,),
            orcid=orcid,
        )
        if name
        else None
    )
    contact = build_contact(
        context,
        address=address,
        author=author,
        association_basis="corresp_xref" if author else "unmatched",
        association_status="needs_review" if author else "unmatched",
        evidence_locator="/article[1]",
        evidence_excerpt=address,
        target_roles="all",
        reference_year=2026,
        suppressed_emails=suppressed,
        suppressed_domains=frozenset(),
    )
    assert contact is not None
    return contact


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("info@lab.example", True),
        ("NoReply@journal.example", True),
        ("office+cfp@uni.example", True),
        ("genomics-lab@uni.example", True),
        ("ana.silva@uni.example", False),
        ("labrador@uni.example", False),
    ],
)
def test_role_accounts(address: str, expected: bool) -> None:
    assert is_role_account(address) is expected


def test_role_account_needs_review() -> None:
    contact = _contact("office@uni.example")
    assert contact.outreach_eligibility == "needs_review"
    assert "role_account" in contact.eligibility_reasons


def test_same_address_across_articles_rolls_up() -> None:
    profiles = build_researcher_profiles(
        [
            _contact("ana@uni.example", doi="10.5555/a.1", year=2022, affiliation="Old Institute"),
            _contact("ana@uni.example", doi="10.5555/a.2", year=2026, affiliation="New Institute"),
            _contact("ANA@uni.example", doi="10.5555/a.2", year=2026),  # duplicate observation
        ],
        reference_year=2026,
    )
    (profile,) = profiles
    assert profile.publication_count == 2
    assert profile.latest_publication_year == 2026
    assert profile.latest_affiliation == "New Institute"
    assert profile.affiliation_changed is True
    assert profile.activity == "active_recent"
    assert profile.outreach_eligibility == "eligible"
    assert profile.publications[0].doi == "10.5555/a.2"


def test_same_name_different_addresses_never_merge() -> None:
    profiles = build_researcher_profiles(
        [_contact("ana@uni.example"), _contact("a.silva@other.example", doi="10.5555/b.1")]
    )
    assert len(profiles) == 2


def test_shared_valid_orcid_links_addresses() -> None:
    profiles = build_researcher_profiles(
        [
            _contact("ana@uni.example", orcid=VALID_ORCID),
            _contact("a.silva@other.example", doi="10.5555/b.1", orcid=VALID_ORCID),
        ]
    )
    (profile,) = profiles
    assert set(profile.emails) == {"ana@uni.example", "a.silva@other.example"}
    assert profile.orcids == (VALID_ORCID,)
    assert "multiple_addresses_linked_by_orcid" in profile.review_flags


def test_invalid_orcid_does_not_link() -> None:
    profiles = build_researcher_profiles(
        [
            _contact("ana@uni.example", orcid="0000-0002-1825-0098"),
            _contact("a.silva@other.example", doi="10.5555/b.1", orcid="0000-0002-1825-0098"),
        ]
    )
    assert len(profiles) == 2
    assert all("invalid_orcid_declared" in p.review_flags for p in profiles)


def test_conflicts_are_flagged_and_block_eligibility() -> None:
    profiles = build_researcher_profiles(
        [
            _contact("shared@uni.example", name="Ana Silva", orcid=VALID_ORCID),
            _contact(
                "shared@uni.example", name="Ben Ode", doi="10.5555/c.1", orcid=OTHER_VALID_ORCID
            ),
        ]
    )
    # Two ORCIDs on one address chain into one group; both conflicts are surfaced.
    (profile,) = profiles
    assert "address_has_conflicting_orcids" in profile.review_flags
    assert "address_used_under_different_names" in profile.review_flags
    assert profile.outreach_eligibility == "needs_review"


def test_suppression_dominates_profile() -> None:
    profiles = build_researcher_profiles(
        [
            _contact("ana@uni.example", suppressed=frozenset({"ana@uni.example"})),
            _contact("ana@uni.example", doi="10.5555/a.9"),
        ]
    )
    assert profiles[0].outreach_eligibility == "suppressed"


def test_unknown_year_activity() -> None:
    (profile,) = build_researcher_profiles([_contact("ana@uni.example", year=None)])
    assert profile.activity == "unknown"
    assert profile.latest_publication_year is None


def test_researchers_csv() -> None:
    profiles = build_researcher_profiles(
        [_contact("ana@uni.example", orcid=VALID_ORCID)], reference_year=2026
    )
    rows = list(csv.DictReader(io.StringIO(render_researchers_csv(profiles).decode())))
    assert rows[0]["primary_email"] == "ana@uni.example"
    assert rows[0]["orcids"] == VALID_ORCID
    assert rows[0]["activity"] == "active_recent"


@pytest.mark.parametrize("preset", EXPORT_PRESETS)
def test_every_preset_renders_and_is_formula_safe(preset: str) -> None:
    contacts = [
        _contact("ana@uni.example"),
        _contact("evil@uni.example", name="=HYPERLINK(1)", doi="10.5555/x.1"),
        _contact("unmatched@uni.example", name=None, doi="10.5555/y.1"),
    ]
    export = render_export(preset, contacts)  # type: ignore[arg-type]
    text = export.content.decode()
    assert "ana@uni.example" in text
    assert "HYPERLINK" not in text
    assert export.rows_withheld_unsafe == 1
    if preset == "evidence":
        assert "unmatched@uni.example" in text  # review file keeps unmatched rows
        assert "corresp_xref" in text
    else:
        assert "unmatched@uni.example" not in text
        assert export.rows_excluded_not_eligible == 1


def test_outreach_presets_dedupe_addresses() -> None:
    contacts = [_contact("ana@uni.example"), _contact("ana@uni.example", doi="10.5555/a.2")]
    assert render_export("lemlist", contacts).rows_written == 1
    assert render_export("evidence", contacts).rows_written == 2


def test_lemlist_and_hubspot_columns() -> None:
    result = OpenAccessOrchestrator(reference_year=2026).discover_and_extract("PMC10293847")
    lem = list(
        csv.DictReader(
            io.StringIO(render_export("lemlist", result.contacts_extracted).content.decode())
        )
    )
    assert lem[0]["doiLink"] == "https://doi.org/10.1371/journal.pbio.3002145"
    hub = list(
        csv.DictReader(
            io.StringIO(render_export("hubspot", result.contacts_extracted).content.decode())
        )
    )
    assert hub[0]["Email"] == "marcus.vance@biotech.zurich.example"
    assert hub[0]["Lead Source Detail"] == "EmailMonitor Open Access extraction"


def test_preview_export_presets_and_researchers_endpoint() -> None:
    client = TestClient(app)
    base = f"/api/v1/organizations/{ORG_ID}/open-access"
    for preset in ("lemlist", "hubspot", "evidence", "researchers"):
        response = client.post(f"{base}/export", json={"query": "CRISPR", "preset": preset})
        assert response.status_code == 200, preset
        assert int(response.headers["x-emailmonitor-rows-written"]) >= 1
    response = client.post(f"{base}/researchers", json={"query": "CRISPR", "target_roles": "all"})
    assert response.status_code == 200
    body = response.json()
    assert body["researchers"]
    assert all(r["publication_count"] >= 1 for r in body["researchers"])


def test_minimum_association_strength_filters_outreach_presets() -> None:
    result = OpenAccessOrchestrator(reference_year=2026).discover_and_extract(
        "PMC7700001", target_roles="all"
    )
    strengths = {c.email: c.association_strength for c in result.contacts_extracted}
    assert strengths == {
        "r.mehta@bio.pune.example": "structural",
        "lucia.ferreira@neuro.lisbon.example": "labelled",
        "t.nowak@genetics.krakow.example": "labelled",
        "core-lab@genetics.krakow.example": "none",
    }
    default = render_export("instantly", result.contacts_extracted)
    strict = render_export("instantly", result.contacts_extracted, "structural")
    assert (default.rows_written, strict.rows_written) == (3, 1)
    # The evidence audit is a review file and ignores the outreach threshold.
    assert render_export("evidence", result.contacts_extracted, "structural").rows_written == 4


def test_preview_export_accepts_minimum_strength() -> None:
    client = TestClient(app)
    response = client.post(
        f"/api/v1/organizations/{ORG_ID}/open-access/export",
        json={
            "query": "PMC7700001",
            "target_roles": "all",
            "preset": "smartlead",
            "minimum_association_strength": "structural",
        },
    )
    assert response.status_code == 200
    assert response.headers["x-emailmonitor-rows-written"] == "1"

"""Open Access orchestrator: own-article evidence, truthful outcomes, roles (OA-012)."""

from __future__ import annotations

import csv
import io

import pytest
from emailmonitor.discovery.openaccess_orchestrator import (
    DiscoveryFilters,
    DiscoveryResult,
    OpenAccessOrchestrator,
    contact_id_for,
    route_query,
)
from emailmonitor.fetching.safety import FetchDenied


@pytest.fixture
def orchestrator() -> OpenAccessOrchestrator:
    return OpenAccessOrchestrator(reference_year=2026)


def _by_email(result: DiscoveryResult) -> dict[str, object]:
    return {c.email: c for c in result.contacts_extracted}


@pytest.mark.parametrize(
    ("query", "source", "reason"),
    [
        ("PMC10293847", "europe-pmc", "pmcid_identifier"),
        ("pmc10293847", "europe-pmc", "pmcid_identifier"),
        ("10.1101/2026.03.14.584920", "biorxiv", "preprint_doi_prefix"),
        ("https://doi.org/10.1038/s41587-026-01824-x", "crossref", "doi_identifier"),
        ("CRISPR base editing", "europe-pmc", "keyword_full_text_search"),
        # A keyword that merely contains 'PMC' is not an identifier.
        ("PMC funding policy", "europe-pmc", "keyword_full_text_search"),
    ],
)
def test_routing(query: str, source: str, reason: str) -> None:
    assert route_query(query) == (source, reason)


def test_europe_pmc_keyword_pipeline_reports_every_work(
    orchestrator: OpenAccessOrchestrator,
) -> None:
    result = orchestrator.discover_and_extract("CRISPR", target_roles="all")

    assert result.source_used == "europe-pmc"
    statuses = {a.work_key: a.status for a in result.articles}
    assert statuses == {
        "PMC10293847": "contacts_observed",
        "PMC7700001": "contacts_observed",
        "PMC887766": "no_contact",
        "PMC5550001": "full_text_unavailable",
    }
    # Subscription (non-OA) hit is filtered by the request, not reported as scanned.
    assert result.total_articles_scanned == 4
    assert result.articles_with_full_text == 3
    assert result.unmatched_candidates_count == 1
    assert result.hit_count_reported == 4

    vance = _by_email(result)["marcus.vance@biotech.zurich.example"]
    assert vance.author_name == "Marcus Vance"  # type: ignore[attr-defined]
    assert vance.is_corresponding_author is True  # type: ignore[attr-defined]
    assert vance.is_first_author is False  # type: ignore[attr-defined]
    assert vance.affiliations == (  # type: ignore[attr-defined]
        "Institute of Biotechnology, ETH Zurich, Zurich, Switzerland",
    )
    assert vance.doi == "10.1371/journal.pbio.3002145"  # type: ignore[attr-defined]
    assert vance.publication_year == 2026  # type: ignore[attr-defined]
    assert vance.association_basis == "corresp_xref"  # type: ignore[attr-defined]
    assert vance.technical_status == "syntax_valid_not_mailbox_verified"  # type: ignore[attr-defined]
    assert vance.outreach_eligibility == "eligible"  # type: ignore[attr-defined]
    # Author 1's ORCID is never transferred to the corresponding author.
    assert vance.orcid_id is None  # type: ignore[attr-defined]
    assert vance.orcid_status == "absent"  # type: ignore[attr-defined]
    assert "Article 6(1)(f)" in vance.gdpr_notice  # type: ignore[attr-defined]


def test_unmatched_address_needs_review_and_is_not_exported(
    orchestrator: OpenAccessOrchestrator,
) -> None:
    result = orchestrator.discover_and_extract("PMC7700001", target_roles="all")
    lab = _by_email(result)["core-lab@genetics.krakow.example"]
    assert lab.author_name is None  # type: ignore[attr-defined]
    assert lab.association_status == "unmatched"  # type: ignore[attr-defined]
    assert lab.outreach_eligibility == "needs_review"  # type: ignore[attr-defined]
    assert "author_association_unresolved" in lab.eligibility_reasons  # type: ignore[attr-defined]
    assert b"core-lab@genetics.krakow.example" not in result.export_instantly_csv()


def test_role_filters(orchestrator: OpenAccessOrchestrator) -> None:
    corresponding = orchestrator.discover_and_extract("PMC7700001", target_roles="corresponding")
    assert sorted(_by_email(corresponding)) == [
        "lucia.ferreira@neuro.lisbon.example",
        "t.nowak@genetics.krakow.example",
    ]
    both = orchestrator.discover_and_extract("PMC7700001", target_roles="both")
    # Middle author with a contrib email is neither first nor corresponding.
    assert "r.mehta@bio.pune.example" not in _by_email(both)
    every = orchestrator.discover_and_extract("PMC7700001", target_roles="all")
    assert len(every.contacts_extracted) == 4
    first = orchestrator.discover_and_extract("PMC7700001", target_roles="first")
    assert first.contacts_extracted == ()  # first author published no address


def test_crossref_work_uses_only_its_own_full_text(orchestrator: OpenAccessOrchestrator) -> None:
    result = orchestrator.discover_and_extract("gene editing", source="crossref")
    by_work = {a.work_key: a for a in result.articles}
    assert by_work["10.1016/j.cell.2025.11.020"].status == "full_text_unavailable"
    assert by_work["10.1016/j.cell.2025.11.020"].contacts_retained == 0
    usher = by_work["10.1038/s41587-026-01824-x"]
    assert usher.status == "contacts_observed"
    assert usher.pmcid == "PMC7700001"
    for contact in result.contacts_extracted:
        assert contact.doi == "10.1038/s41587-026-01824-x"
        assert contact.pmcid == "PMC7700001"
        assert "Usher" in (contact.article_title or "")
    # The PLOS fixture's address must never be attached to a Crossref work.
    assert "marcus.vance@biotech.zurich.example" not in _by_email(result)


def test_crossref_doi_lookup(orchestrator: OpenAccessOrchestrator) -> None:
    result = orchestrator.discover_and_extract("doi:10.1038/S41587-026-01824-X")
    assert result.source_used == "crossref"
    assert result.total_articles_scanned == 1
    assert result.corresponding_authors_count == 2


def test_openalex_resolves_doi_to_pmcid(orchestrator: OpenAccessOrchestrator) -> None:
    result = orchestrator.discover_and_extract("CRISPR", source="openalex")
    by_work = {a.work_key: a for a in result.articles}
    assert by_work["W3029182736"].pmcid == "PMC10293847"
    # No PMCID in OpenAlex; resolved through the Europe PMC DOI lookup.
    assert by_work["W4019283746"].pmcid == "PMC1234567"
    kim = _by_email(result)["kim.soojin@cropgenomics.suwon.example"]
    assert kim.journal == "BMC Genomics"  # type: ignore[attr-defined]
    assert kim.is_corresponding_author is True  # type: ignore[attr-defined]


def test_biorxiv_uses_preprint_full_text_or_reports_unavailable(
    orchestrator: OpenAccessOrchestrator,
) -> None:
    found = orchestrator.discover_and_extract("10.1101/2026.03.14.584920")
    assert found.source_used == "biorxiv"
    (contact,) = found.contacts_extracted
    assert contact.email == "m.vance@biotech.zurich.example"
    assert contact.doi == "10.1101/2026.03.14.584920"
    assert contact.full_text_url.endswith("584920v1.source.xml")
    assert contact.orcid_id is None

    missing = orchestrator.discover_and_extract("10.1101/2026.02.10.579112")
    assert missing.contacts_extracted == ()
    assert missing.articles[0].status == "full_text_unavailable"


def test_biorxiv_keyword_filter_is_applied(orchestrator: OpenAccessOrchestrator) -> None:
    result = orchestrator.discover_and_extract("hematopoietic progenitor", source="biorxiv")
    assert [a.work_key for a in result.articles] == ["10.1101/2026.03.14.584920"]
    none = orchestrator.discover_and_extract("zebrafish cardiology", source="biorxiv")
    assert none.articles == ()


def test_contact_ids_are_deterministic(orchestrator: OpenAccessOrchestrator) -> None:
    first = orchestrator.discover_and_extract("PMC10293847")
    second = orchestrator.discover_and_extract("PMC10293847")
    assert [c.contact_id for c in first.contacts_extracted] == [
        c.contact_id for c in second.contacts_extracted
    ]
    assert first.contacts_extracted[0].contact_id == contact_id_for(
        "europe-pmc", "PMC10293847", "marcus.vance@biotech.zurich.example"
    )


def test_filters_report_exclusions(orchestrator: OpenAccessOrchestrator) -> None:
    result = orchestrator.discover_and_extract(
        "CRISPR",
        source="openalex",
        filters=DiscoveryFilters(exclude_journals=("bmc genomics",)),
    )
    statuses = {a.work_key: (a.status, a.reason) for a in result.articles}
    assert statuses["W4019283746"] == ("excluded_by_filter", "journal_excluded")
    assert all(c.journal != "BMC Genomics" for c in result.contacts_extracted)


def test_year_filter_on_europe_pmc(orchestrator: OpenAccessOrchestrator) -> None:
    result = orchestrator.discover_and_extract(
        "CRISPR", filters=DiscoveryFilters(from_year=2026), target_roles="all"
    )
    assert {a.work_key for a in result.articles} == {"PMC10293847", "PMC7700001"}


def test_suppression_by_address_and_domain(orchestrator: OpenAccessOrchestrator) -> None:
    result = orchestrator.discover_and_extract(
        "PMC7700001",
        target_roles="all",
        suppressed_emails=["Lucia.Ferreira@neuro.lisbon.example"],
        suppressed_domains=["krakow.example"],
    )
    states = {c.email: c.outreach_eligibility for c in result.contacts_extracted}
    assert states["lucia.ferreira@neuro.lisbon.example"] == "suppressed"
    assert states["t.nowak@genetics.krakow.example"] == "suppressed"  # subdomain match
    assert states["r.mehta@bio.pune.example"] == "eligible"
    exported = result.export_smartlead_csv().decode()
    assert "lucia.ferreira" not in exported and "t.nowak" not in exported
    assert "r.mehta@bio.pune.example" in exported


def test_export_columns_carry_provenance(orchestrator: OpenAccessOrchestrator) -> None:
    result = orchestrator.discover_and_extract("PMC10293847")
    rows = list(csv.DictReader(io.StringIO(result.export_instantly_csv().decode())))
    assert len(rows) == 1
    row = rows[0]
    assert row["email"] == "marcus.vance@biotech.zurich.example"
    assert row["first_name"] == "Marcus"
    assert row["last_name"] == "Vance"
    assert row["custom_doi"] == "10.1371/journal.pbio.3002145"
    assert "ETH Zurich" in row["company_name"]


@pytest.mark.parametrize(
    ("query", "max_results"),
    [("", 5), ("x" * 1001, 5), ("CRI\x00SPR", 5), ("CRISPR", 0), ("CRISPR", 101)],
)
def test_input_bounds(orchestrator: OpenAccessOrchestrator, query: str, max_results: int) -> None:
    with pytest.raises(FetchDenied):
        orchestrator.discover_and_extract(query.rstrip(" ") or "", max_results=max_results)


def test_max_results_bounds_work_count(orchestrator: OpenAccessOrchestrator) -> None:
    result = orchestrator.discover_and_extract("CRISPR", max_results=2, target_roles="all")
    assert result.total_articles_scanned == 2

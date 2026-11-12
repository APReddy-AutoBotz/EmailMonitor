"""Unit tests for Unified Open Access Discovery Orchestrator."""

from __future__ import annotations

from emailmonitor.discovery.openaccess_orchestrator import (
    DiscoveryResult,
    ExtractedAcademicContact,
    OpenAccessOrchestrator,
)


def test_orchestrator_europe_pmc_pipeline() -> None:
    orchestrator = OpenAccessOrchestrator()
    result: DiscoveryResult = orchestrator.discover_and_extract(
        query="CRISPR hematopoietic stem cells",
        source="europe-pmc",
        max_results=5,
        target_roles="both",
    )

    assert result.source_used == "europe-pmc"
    assert len(result.contacts_extracted) >= 1
    assert result.corresponding_authors_count >= 1

    contact: ExtractedAcademicContact = result.contacts_extracted[0]
    assert contact.email == "marcus.vance@biotech.ethz.ch"
    assert contact.first_name == "Marcus"
    assert contact.last_name == "Vance"
    assert contact.is_corresponding_author is True
    assert "ETH Zurich" in contact.affiliations[0]
    assert contact.deliverability_score >= 80
    assert contact.outreach_eligibility == "eligible"
    assert "GDPR" in contact.gdpr_notice
    assert "Article 6(1)(f)" in contact.gdpr_notice


def test_orchestrator_openalex_bridge_pipeline() -> None:
    orchestrator = OpenAccessOrchestrator()
    result: DiscoveryResult = orchestrator.discover_and_extract(
        query="CRISPR Cas9 base editing",
        source="openalex",
        max_results=5,
        target_roles="corresponding",
    )

    assert result.source_used == "openalex"
    assert len(result.contacts_extracted) >= 1
    for contact in result.contacts_extracted:
        assert contact.is_corresponding_author is True
        assert "@" in contact.email
        assert contact.outreach_eligibility == "eligible"


def test_orchestrator_crossref_pipeline() -> None:
    orchestrator = OpenAccessOrchestrator()
    result: DiscoveryResult = orchestrator.discover_and_extract(
        query="10.1038/s41587-026-01824-x",
        source="crossref",
        max_results=5,
        target_roles="both",
    )

    assert result.source_used == "crossref"
    assert len(result.contacts_extracted) >= 1
    contact = result.contacts_extracted[0]
    assert "@" in contact.email
    assert contact.publication_year in (2025, 2026)


def test_orchestrator_biorxiv_pipeline() -> None:
    orchestrator = OpenAccessOrchestrator()
    result: DiscoveryResult = orchestrator.discover_and_extract(
        query="10.1101/2026.03.14.584920",
        source="biorxiv",
        max_results=5,
        target_roles="corresponding",
    )

    assert result.source_used == "biorxiv"
    assert len(result.contacts_extracted) >= 1
    contact = result.contacts_extracted[0]
    assert "@" in contact.email
    assert contact.is_corresponding_author is True
    assert contact.orcid_id == "0000-0002-1825-0097"
    assert "ETH Zurich" in contact.affiliations[0]


def test_orchestrator_export_presets_csv() -> None:
    orchestrator = OpenAccessOrchestrator()
    result: DiscoveryResult = orchestrator.discover_and_extract(
        query="CRISPR gene editing",
        source="europe-pmc",
    )

    instantly_csv = result.export_instantly_csv()
    smartlead_csv = result.export_smartlead_csv()

    assert len(instantly_csv) > 50
    assert len(smartlead_csv) > 50

    text_instantly = instantly_csv.decode("utf-8")
    assert "email" in text_instantly
    assert "marcus.vance@biotech.ethz.ch" in text_instantly
    assert "Marcus" in text_instantly
    assert "Vance" in text_instantly
    assert "ETH Zurich" in text_instantly

    text_smartlead = smartlead_csv.decode("utf-8")
    assert "Email" in text_smartlead
    assert "marcus.vance@biotech.ethz.ch" in text_smartlead
    assert "10.1371/journal.pbio.3002145" in text_smartlead

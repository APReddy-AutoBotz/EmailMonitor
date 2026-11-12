"""Unit tests for Medical Subject Headings (MeSH) & Thematic Issue Sourcing."""

from __future__ import annotations

from emailmonitor.discovery.mesh_search import (
    COMMON_MESH_CATALOG,
    MeshDescriptor,
    ThematicSearchPlanner,
    match_mesh_terms,
)


def test_mesh_catalog_integrity() -> None:
    assert "D000089822" in COMMON_MESH_CATALOG
    crispr: MeshDescriptor = COMMON_MESH_CATALOG["D000089822"]
    assert crispr.name == "CRISPR-Cas Systems"
    assert "CRISPR-Cas9" in crispr.synonyms
    assert crispr.scope_note is not None


def test_thematic_search_planner_europepmc_query() -> None:
    planner = ThematicSearchPlanner(
        primary_topic="Gene Therapy",
        mesh_descriptor_ids=("D000089822",),
        excluded_journals=("Nature Biotechnology", "Science"),
        keywords_must=("clinical trials",),
        keywords_must_not=("murine",),
        recent_months=12,
    )

    query = planner.to_europepmc_query()
    assert '"Gene Therapy"' in query
    assert '(MESH:"CRISPR-Cas Systems")' in query
    assert '"clinical trials"' in query
    assert 'NOT "murine"' in query
    assert 'NOT JOURNAL:"Nature Biotechnology"' in query
    assert 'NOT JOURNAL:"Science"' in query


def test_thematic_journal_exclusion() -> None:
    planner = ThematicSearchPlanner(
        primary_topic="Immunotherapy",
        excluded_journals=("Nature", "Cell"),
    )

    assert planner.is_journal_excluded("Nature Medicine") is True
    assert planner.is_journal_excluded("Cell Reports") is True
    assert planner.is_journal_excluded("PLOS Biology") is False
    assert planner.is_journal_excluded(None) is False


def test_natural_language_mesh_term_matching() -> None:
    query = "Recent advances in mRNA Vaccines and checkpoint inhibitor cancer therapies"
    matches = match_mesh_terms(query)
    names = [m.name for m in matches]

    assert "Vaccines" in names
    assert "Neoplasms" in names  # from 'cancer' synonym
    assert "Immunotherapy" in names  # from 'checkpoint inhibitor' synonym

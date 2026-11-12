"""Unit tests for bioRxiv / medRxiv Pre-Print REST Connector."""

from __future__ import annotations

from emailmonitor.sources.biorxiv import (
    BioRxivFixtureGateway,
    BioRxivPreprint,
    BioRxivQueryPlanner,
)
from emailmonitor.sources.openaccess import DoiIdentifier


def test_biorxiv_query_planner_canonical_url() -> None:
    planner = BioRxivQueryPlanner(
        server="biorxiv",
        from_date="2026-01-01",
        to_date="2026-03-31",
        cursor=0,
        limit=50,
    )

    assert planner.api_path == "/details/biorxiv/2026-01-01/2026-03-31/0"
    assert planner.canonical_url == "https://api.biorxiv.org/details/biorxiv/2026-01-01/2026-03-31/0"


def test_biorxiv_parse_fixture() -> None:
    gateway = BioRxivFixtureGateway()
    planner = BioRxivQueryPlanner(
        server="biorxiv",
        from_date="2026-01-01",
        to_date="2026-04-01",
        limit=10,
    )

    preprints: tuple[BioRxivPreprint, ...] = gateway.search_preprints(planner)
    assert len(preprints) == 2

    p1 = preprints[0]
    assert p1.doi.value == "10.1101/2026.03.14.584920"
    assert "Base Editing" in p1.title
    assert p1.corresponding_author == "Marcus Vance"
    assert p1.corresponding_institution is not None
    assert "ETH Zurich" in p1.corresponding_institution
    assert p1.server == "biorxiv"
    assert p1.publication_year == 2026
    assert p1.jats_xml_url is not None
    assert "source.xml" in p1.jats_xml_url


def test_biorxiv_doi_resolver() -> None:
    gateway = BioRxivFixtureGateway()
    doi = DoiIdentifier(value="10.1101/2026.02.10.579112")
    preprint = gateway.resolve_doi(doi)

    assert preprint is not None
    assert preprint.corresponding_author == "Soojin Kim"
    assert preprint.corresponding_institution is not None
    assert "Seoul National University" in preprint.corresponding_institution
    assert preprint.version == 2


def test_biorxiv_date_boundary_filtering() -> None:
    gateway = BioRxivFixtureGateway()
    planner = BioRxivQueryPlanner(
        server="biorxiv",
        from_date="2026-03-01",
        to_date="2026-03-31",
    )
    preprints = gateway.search_preprints(planner)
    assert len(preprints) == 1
    assert preprints[0].posted_date == "2026-03-14"

"""Unit tests for Crossref REST API connector and Open Access DOI resolver."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from emailmonitor.sources.crossref import (
    CrossrefAuthor,
    CrossrefFixtureGateway,
    CrossrefFullTextLink,
    CrossrefQueryPlanner,
)


def test_crossref_query_planner_url_generation() -> None:
    planner = CrossrefQueryPlanner(
        query="CRISPR gene editing",
        rows=30,
        open_access_only=True,
        from_year=2024,
        until_year=2026,
    )
    url = planner.plan_url()
    assert "https://api.crossref.org/works?" in url
    assert "query=CRISPR+gene+editing" in url
    assert "rows=30" in url
    assert "has-license%3Atrue" in url
    assert "from-pub-date%3A2024-01-01" in url
    assert "until-pub-date%3A2026-12-31" in url


def test_crossref_query_planner_bounds() -> None:
    with pytest.raises(ValidationError):
        CrossrefQueryPlanner(query="", rows=10)
    with pytest.raises(ValidationError):
        CrossrefQueryPlanner(query="test", rows=500)  # Exceeds MAX_ROWS=100


def test_crossref_author_parsing() -> None:
    raw = {
        "given": "Emmanuelle",
        "family": "Charpentier",
        "sequence": "first",
        "ORCID": "http://orcid.org/0000-0002-0498-5743",
        "affiliation": [
            {"name": "Max Planck Unit for the Science of Pathogens, Berlin, Germany"}
        ],
    }
    author = CrossrefAuthor.from_dict(raw)
    assert author.display_name == "Emmanuelle Charpentier"
    assert author.is_first_author is True
    assert author.orcid == "http://orcid.org/0000-0002-0498-5743"
    assert len(author.affiliations) == 1
    assert "Max Planck Unit" in author.affiliations[0]


def test_crossref_full_text_links() -> None:
    xml_link = CrossrefFullTextLink(
        url="https://example.com/paper.xml",
        content_type="application/xml",
    )
    pdf_link = CrossrefFullTextLink(
        url="https://example.com/paper.pdf",
        content_type="application/pdf",
    )
    assert xml_link.is_xml is True
    assert xml_link.is_pdf is False
    assert pdf_link.is_xml is False
    assert pdf_link.is_pdf is True

    # Insecure HTTP URL must fail
    with pytest.raises(ValidationError):
        CrossrefFullTextLink(url="http://insecure.org/paper.xml", content_type="text/xml")


def test_crossref_fixture_gateway_search() -> None:
    gateway = CrossrefFixtureGateway()
    planner = CrossrefQueryPlanner(query="CRISPR gene therapy", rows=10)
    works = gateway.search_works(planner)

    assert len(works) == 2
    nature_work = works[0]
    assert nature_work.doi.value == "10.1038/s41587-026-01824-x"
    assert "Usher syndrome" in nature_work.title
    assert nature_work.container_title == "Nature Biotechnology"
    assert nature_work.publication_year == 2026
    assert nature_work.is_open_access is True
    assert nature_work.first_author is not None
    assert nature_work.first_author.display_name == "David Liu"
    assert nature_work.xml_full_text_url == "https://www.nature.com/articles/s41587-026-01824-x.xml"
    assert nature_work.pdf_full_text_url == "https://www.nature.com/articles/s41587-026-01824-x.pdf"


def test_crossref_doi_resolution() -> None:
    gateway = CrossrefFixtureGateway()
    work = gateway.resolve_doi("10.1016/j.cell.2025.11.020")
    assert work is not None
    assert "Cell" in (work.container_title or "")
    assert work.publication_year == 2025
    assert work.first_author is not None
    assert work.first_author.display_name == "Jennifer Doudna"
    assert "Innovative Genomics Institute" in work.first_author.affiliations[0]

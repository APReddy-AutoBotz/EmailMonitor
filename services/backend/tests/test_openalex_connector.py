"""Tests for OpenAlex REST connector, topic planning, and JATS XML integration."""

from pathlib import Path

import pytest

from emailmonitor.extraction.jats import parse_jats_xml
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.openaccess import DoiIdentifier, PmcIdentifier
from emailmonitor.sources.openalex import (
    OpenAlexFilter,
    OpenAlexSearchRequest,
    build_openalex_query_url,
    parse_openalex_search_response,
    work_to_open_access_identifier,
)

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"


def test_build_openalex_query_url():
    req = OpenAlexSearchRequest(
        query="CRISPR gene editing",
        filters=OpenAlexFilter(
            is_oa=True,
            from_publication_date="2025-01-01",
            to_publication_date="2026-12-31",
            issn="1545-7885",
            concept_id="c86803240",
        ),
        page=2,
        per_page=50,
        sort_by="publication_date",
    )
    url = build_openalex_query_url(req)

    assert "https://api.openalex.org/works?" in url
    assert "search=CRISPR%20gene%20editing" in url
    assert "open_access.is_oa:true" in url
    assert "from_publication_date:2025-01-01" in url
    assert "to_publication_date:2026-12-31" in url
    assert "primary_location.source.issn:1545-7885" in url
    assert "concepts.id:c86803240" in url
    assert "sort=publication_date:desc" in url
    assert "page=2" in url
    assert "per-page=50" in url


def test_parse_openalex_search_fixture():
    fixture_path = FIXTURES_DIR / "openalex" / "search-crispr.json"
    data = fixture_path.read_bytes()

    works = parse_openalex_search_response(data)
    assert len(works) == 2

    w1 = works[0]
    assert w1.id == "https://openalex.org/W3029182736"
    assert w1.title == "Advances in CRISPR-Cas9 Target Specificity"
    assert w1.doi == "https://doi.org/10.1371/journal.pbio.3002145"
    assert w1.pmcid == "PMC10293847"
    assert w1.journal_title == "PLOS Biology"
    assert w1.issn_l == "1545-7885"
    assert w1.publication_year == 2026
    assert w1.publication_date == "2026-03-15"
    assert w1.is_oa is True

    assert len(w1.authorships) == 2
    a1 = w1.authorships[0]
    assert a1.author.display_name == "Elena Rostova"
    assert a1.author_position == "first"
    assert a1.is_corresponding is False
    assert a1.author.orcid == "0000-0002-1825-0097"
    assert "University of Cambridge" in a1.institutions

    a2 = w1.authorships[1]
    assert a2.author.display_name == "Marcus Vance"
    assert a2.author_position == "last"
    assert a2.is_corresponding is True
    assert "ETH Zurich" in a2.institutions

    w2 = works[1]
    assert w2.doi == "https://doi.org/10.1186/s12864-026-09123-x"
    assert w2.pmcid is None
    assert len(w2.authorships) == 1
    assert w2.authorships[0].is_corresponding is True


def test_work_to_open_access_identifier_routing():
    fixture_path = FIXTURES_DIR / "openalex" / "search-crispr.json"
    works = parse_openalex_search_response(fixture_path.read_bytes())

    # Work 1 has PMCID -> routes to PmcIdentifier for full-text JATS XML!
    id1 = work_to_open_access_identifier(works[0])
    assert isinstance(id1, PmcIdentifier)
    assert id1.value == "PMC10293847"

    # Work 2 has no PMCID but has DOI -> routes to DoiIdentifier!
    id2 = work_to_open_access_identifier(works[1])
    assert isinstance(id2, DoiIdentifier)
    assert id2.value == "10.1186/s12864-026-09123-x"


def test_openalex_to_jats_pipeline_integration():
    """Verify end-to-end integration: OpenAlex search -> JATS XML email extraction."""
    openalex_fixture = FIXTURES_DIR / "openalex" / "search-crispr.json"
    works = parse_openalex_search_response(openalex_fixture.read_bytes())

    work = works[0]
    # Identify that Marcus Vance is the corresponding author from OpenAlex metadata
    corresp_author = [a for a in work.authorships if a.is_corresponding][0]
    assert corresp_author.author.display_name == "Marcus Vance"

    # Route OpenAlex work to PMCID identifier
    identifier = work_to_open_access_identifier(work)
    assert isinstance(identifier, PmcIdentifier)

    # Ingest corresponding full-text JATS XML
    jats_bytes = (FIXTURES_DIR / "jats" / "plos-sample.xml").read_bytes()
    observation = parse_jats_xml(jats_bytes, identifier)

    # Verify extracted correspondence contact
    assert observation.status == "observed"
    assert len(observation.candidates) == 1
    candidate = observation.candidates[0]
    assert candidate.raw_address == "marcus.vance@biotech.ethz.ch"
    # Provenance matches Marcus Vance
    assert candidate.author_positions == [2]
    assert observation.authors[1].display_name == "Marcus Vance"
    assert observation.authors[1].corresponding is True


def test_adversarial_openalex_inputs():
    with pytest.raises(FetchDenied, match="invalid_openalex_json"):
        parse_openalex_search_response(b"{malformed json...")

    with pytest.raises(FetchDenied, match="missing_results_array"):
        parse_openalex_search_response(b'{"meta": {}}')

    large_payload = b'{"results": []}' + (b" " * (5 * 1024 * 1024 + 10))
    with pytest.raises(FetchDenied, match="openalex_payload_too_large"):
        parse_openalex_search_response(large_payload)

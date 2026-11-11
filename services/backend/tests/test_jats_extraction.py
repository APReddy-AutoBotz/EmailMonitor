"""Tests for high-precision NISO JATS XML extraction in Open Access articles."""

from pathlib import Path

import pytest

from emailmonitor.extraction.jats import parse_jats_xml
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.openaccess import (
    DoiIdentifier,
    OpenAlexIdentifier,
    PmcIdentifier,
    open_access_url,
)

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "jats"


def test_open_access_identifiers():
    pmc = PmcIdentifier(value="pmc10293847")
    assert pmc.value == "PMC10293847"
    assert open_access_url(pmc) == "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC10293847/fullTextXML"

    doi = DoiIdentifier(value="https://doi.org/10.1371/journal.pbio.3002145")
    assert doi.value == "10.1371/journal.pbio.3002145"
    assert open_access_url(doi) == "https://api.crossref.org/works/10.1371%2Fjournal.pbio.3002145"

    oa = OpenAlexIdentifier(value="w3123456789")
    assert oa.value == "W3123456789"
    assert open_access_url(oa) == "https://api.openalex.org/works/W3123456789"


def test_plos_sample_extraction():
    xml_path = FIXTURES_DIR / "plos-sample.xml"
    data = xml_path.read_bytes()
    identifier = PmcIdentifier(value="PMC10293847")

    obs = parse_jats_xml(data, identifier)

    assert obs.status == "observed"
    assert obs.title == "Advances in CRISPR-Cas9 Target Specificity"
    assert obs.journal == "PLOS Biology"
    assert obs.doi == "10.1371/journal.pbio.3002145"
    assert obs.publication_date == "2026-03-15"

    assert len(obs.authors) == 2
    author1 = obs.authors[0]
    assert author1.position == 1
    assert author1.display_name == "Elena Rostova"
    assert author1.first is True
    assert author1.corresponding is False
    assert author1.orcid == "0000-0002-1825-0097"
    assert any("University of Cambridge" in aff for aff in author1.affiliations)

    author2 = obs.authors[1]
    assert author2.position == 2
    assert author2.display_name == "Marcus Vance"
    assert author2.first is False
    assert author2.corresponding is True
    assert any("ETH Zurich" in aff for aff in author2.affiliations)

    assert len(obs.candidates) == 1
    candidate = obs.candidates[0]
    assert candidate.raw_address == "marcus.vance@biotech.ethz.ch"
    # Accurately linked to Marcus Vance (position 2)!
    assert candidate.author_positions == [2]
    assert candidate.association_status == "needs_review"
    assert candidate.evidence.kind == "structured_metadata"
    assert "marcus.vance@biotech.ethz.ch" in candidate.evidence.excerpt


def test_biomed_direct_email_extraction():
    xml_path = FIXTURES_DIR / "biomed-sample.xml"
    data = xml_path.read_bytes()
    identifier = DoiIdentifier(value="10.1186/s12864-026-09123-x")

    obs = parse_jats_xml(data, identifier)

    assert obs.status == "observed"
    assert obs.title == "High-throughput transcriptomic profiling of drought-tolerant wheat"
    assert obs.journal == "BMC Genomics"
    assert obs.doi == "10.1186/s12864-026-09123-x"
    assert obs.publication_date == "2026-01"

    assert len(obs.authors) == 1
    author = obs.authors[0]
    assert author.position == 1
    assert author.display_name == "Soo-Jin Kim"
    assert author.first is True
    assert author.corresponding is True
    assert any("National Institute of Crop Science" in aff for aff in author.affiliations)

    assert len(obs.candidates) == 1
    candidate = obs.candidates[0]
    assert candidate.raw_address == "kim.soojin@cropgenomics.ac.kr"
    assert candidate.author_positions == [1]
    assert candidate.association_status == "needs_review"


def test_no_contact_article():
    xml_path = FIXTURES_DIR / "no-contact.xml"
    data = xml_path.read_bytes()
    identifier = DoiIdentifier(value="10.3389/fimmu.2026.887766")

    obs = parse_jats_xml(data, identifier)

    assert obs.status == "no_contact"
    assert obs.title == "Mechanisms of Memory T-Cell Persistence"
    assert obs.journal == "Frontiers in Immunology"
    assert len(obs.authors) == 1
    assert len(obs.candidates) == 0


def test_adversarial_malformed_xml():
    data = b"<article><front><title>Unclosed tag</article>"
    identifier = PmcIdentifier(value="PMC9999999")

    with pytest.raises(FetchDenied, match="malformed_jats_xml"):
        parse_jats_xml(data, identifier)


def test_adversarial_empty_payload():
    identifier = PmcIdentifier(value="PMC9999999")

    with pytest.raises(FetchDenied, match="empty_jats_xml_payload"):
        parse_jats_xml(b"   ", identifier)


def test_adversarial_oversized_payload():
    large_data = b"<article>" + (b"A" * (4 * 1024 * 1024 + 10)) + b"</article>"
    identifier = PmcIdentifier(value="PMC9999999")

    with pytest.raises(FetchDenied, match="jats_xml_byte_limit_exceeded"):
        parse_jats_xml(large_data, identifier)


def test_adversarial_deep_nesting():
    # Construct XML exceeding 48 levels of depth
    tags = [f"tag{i}" for i in range(55)]
    nested_xml = "".join(f"<{t}>" for t in tags) + "".join(f"</{t}>" for t in reversed(tags))
    identifier = PmcIdentifier(value="PMC9999999")

    with pytest.raises(FetchDenied, match="jats_xml_depth_limit_exceeded"):
        parse_jats_xml(nested_xml.encode("utf-8"), identifier)

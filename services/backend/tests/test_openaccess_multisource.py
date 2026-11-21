"""Merged multi-source discovery and license classification (OA-021)."""

import pytest
from emailmonitor.discovery.openaccess_orchestrator import (
    OpenAccessOrchestrator,
    OpenAlexFixtureGateway,
)
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.openaccess import license_category
from emailmonitor.sources.openalex import OpenAlexSearchRequest, OpenAlexWork


class BrokenOpenAlex(OpenAlexFixtureGateway):
    def search_works(self, request: OpenAlexSearchRequest) -> list[OpenAlexWork]:
        raise FetchDenied("openalex_unavailable")


def test_merged_sources_read_each_article_once() -> None:
    result = OpenAccessOrchestrator(reference_year=2026).discover_and_extract(
        "CRISPR", source="all", target_roles="all"
    )
    assert result.source_used == "all"
    assert result.route_reason == "merged_sources"
    keys = [a.pmcid or a.doi for a in result.articles]
    assert len(keys) == len(set(keys))
    by_key = {a.pmcid or a.doi: a for a in result.articles}
    assert by_key["PMC10293847"].found_in == ("europe-pmc", "openalex")
    assert by_key["PMC7700001"].found_in == ("europe-pmc", "crossref")
    assert by_key["10.1016/j.cell.2025.11.020"].status == "full_text_unavailable"
    # The PLOS address appears once even though two sources found the article.
    vance = [c for c in result.contacts_extracted if c.email.startswith("marcus.vance")]
    assert len(vance) == 1
    assert result.source_errors == {}


def test_one_failing_source_does_not_sink_the_run() -> None:
    orchestrator = OpenAccessOrchestrator(openalex_gateway=BrokenOpenAlex(), reference_year=2026)
    result = orchestrator.discover_and_extract("CRISPR", source="all", target_roles="all")
    assert result.source_errors == {"openalex": "openalex_unavailable"}
    assert any(a.pmcid == "PMC7700001" for a in result.articles)
    assert all("openalex" not in a.found_in for a in result.articles)


def test_merged_results_respect_max_results() -> None:
    result = OpenAccessOrchestrator(reference_year=2026).discover_and_extract(
        "CRISPR", source="all", max_results=2
    )
    assert result.total_articles_scanned == 2


def test_single_source_outcomes_record_origin_and_license() -> None:
    result = OpenAccessOrchestrator(reference_year=2026).discover_and_extract("PMC7700001")
    (article,) = result.articles
    assert article.found_in == ("europe-pmc",)
    assert article.license_category == "cc-by"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://creativecommons.org/licenses/by/4.0/", "cc-by"),
        ("http://creativecommons.org/licenses/by-nc-nd/4.0", "cc-by-nc-nd"),
        ("https://creativecommons.org/licenses/by-sa/3.0/igo/", "cc-by-sa"),
        ("https://creativecommons.org/publicdomain/zero/1.0/", "cc0"),
        ("https://creativecommons.org/publicdomain/mark/1.0/", "public-domain"),
        ("https://publisher.example/terms", "other"),
        ("https://creativecommons.org.attacker.example/licenses/by/4.0/", "other"),
        (None, "unknown"),
        ("   ", "unknown"),
    ],
)
def test_license_category(url: str | None, expected: str) -> None:
    assert license_category(url) == expected


def test_preview_api_accepts_all_sources() -> None:
    from emailmonitor.dev_server import ORG_ID, app
    from fastapi.testclient import TestClient

    response = TestClient(app).post(
        f"/api/v1/organizations/{ORG_ID}/open-access/discover",
        json={"query": "CRISPR", "source": "all"},
    )
    assert response.status_code == 200
    assert response.json()["source_used"] == "all"

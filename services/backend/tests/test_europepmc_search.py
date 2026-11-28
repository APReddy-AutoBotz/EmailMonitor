"""Europe PMC search planner/parser bounds (OA-013)."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.sources.europepmc_search import (
    MAX_PAYLOAD_BYTES,
    EuropePmcSearchFixtureGateway,
    EuropePmcSearchRequest,
    doi_lookup_request,
    parse_search_response,
)


def test_plan_url_adds_open_access_and_year_clauses() -> None:
    request = EuropePmcSearchRequest(query="CRISPR AND wheat", from_year=2024, until_year=2026)
    parts = urlsplit(request.plan_url())
    assert parts.scheme == "https" and parts.netloc == "www.ebi.ac.uk"
    assert parts.path == "/europepmc/webservices/rest/search"
    params = parse_qs(parts.query)
    assert params["query"] == [
        "(CRISPR AND wheat) AND OPEN_ACCESS:y AND IN_EPMC:y AND PUB_YEAR:[2024 TO 2026]"
    ]
    assert params["format"] == ["json"]
    assert params["pageSize"] == ["25"]
    assert params["cursorMark"] == ["*"]


def test_inverted_year_range_is_denied() -> None:
    with pytest.raises(FetchDenied, match="invalid_year_range"):
        EuropePmcSearchRequest(query="x", from_year=2026, until_year=2020).plan_url()


@pytest.mark.parametrize("bad", ["", "   ", "a\x00b", "x" * 1001])
def test_query_validation(bad: str) -> None:
    with pytest.raises(ValueError):
        EuropePmcSearchRequest(query=bad)


def test_page_size_is_bounded() -> None:
    with pytest.raises(ValueError):
        EuropePmcSearchRequest(query="x", page_size=101)


def test_doi_lookup_request() -> None:
    request = doi_lookup_request("https://doi.org/10.5555/OA.BASE-EDITING.01824")
    assert request.query == 'DOI:"10.5555/oa.base-editing.01824"'
    assert request.open_access_only is False
    with pytest.raises(FetchDenied, match="invalid_doi_format"):
        doi_lookup_request("not-a-doi")


def test_parse_response_does_not_default_absent_fields() -> None:
    payload = {
        "hitCount": 3,
        "nextCursorMark": "abc",
        "resultList": {
            "result": [
                {"id": "1", "source": "MED"},
                {"id": "PMC1", "source": "PMC", "pmcid": "not-a-pmcid", "pubYear": "20x6"},
                {"source": "PMC"},  # missing id: dropped
                "junk",
            ]
        },
    }
    page = parse_search_response(json.dumps(payload))
    assert page.hit_count == 3
    assert page.next_cursor_mark == "abc"
    assert len(page.hits) == 2
    first, second = page.hits
    assert first.pmcid is None and first.doi is None and first.publication_year is None
    assert first.is_open_access is False and first.full_text_xml_available is False
    assert second.pmcid is None and second.publication_year is None


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"{not json", "invalid_europe_pmc_search_json"),
        (b"[]", "invalid_europe_pmc_search_structure"),
        (b'{"resultList": {}}', "missing_europe_pmc_result_list"),
        (b"\xff\xfe", "invalid"),
    ],
)
def test_parse_rejects_malformed(payload: bytes, reason: str) -> None:
    with pytest.raises(FetchDenied, match=reason):
        parse_search_response(payload)


def test_parse_rejects_oversized() -> None:
    with pytest.raises(FetchDenied, match="too_large"):
        parse_search_response(b" " * (MAX_PAYLOAD_BYTES + 1))


def test_fixture_gateway_filters_non_open_access() -> None:
    gateway = EuropePmcSearchFixtureGateway()
    page = gateway.search(EuropePmcSearchRequest(query="CRISPR"))
    ids = [h.source_id for h in page.hits]
    assert "39999999" not in ids  # subscription commentary
    assert ids[:2] == ["PMC10293847", "PMC7700001"]
    page_all = gateway.search(
        EuropePmcSearchRequest(query="CRISPR", open_access_only=False, full_text_in_epmc_only=False)
    )
    assert "39999999" in [h.source_id for h in page_all.hits]


def test_fixture_gateway_resolves_doi() -> None:
    gateway = EuropePmcSearchFixtureGateway()
    hit = gateway.resolve_doi("10.5555/OA.BIOMED.09123")
    assert hit is not None and hit.pmcid == "PMC1234567"
    assert gateway.resolve_doi("10.9999/unknown") is None

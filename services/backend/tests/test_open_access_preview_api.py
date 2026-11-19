"""Preview open-access endpoints: bounds, org scoping and truthful payloads."""

import csv
import io

import pytest
from emailmonitor.dev_server import ORG_ID, app
from fastapi.testclient import TestClient

BASE = f"/api/v1/organizations/{ORG_ID}/open-access"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_discover_returns_outcomes_and_contacts(client: TestClient) -> None:
    response = client.post(f"{BASE}/discover", json={"query": "CRISPR", "target_roles": "all"})
    assert response.status_code == 200
    body = response.json()
    assert body["source_used"] == "europe-pmc"
    assert body["total_articles_scanned"] == len(body["articles"])
    assert {a["status"] for a in body["articles"]} >= {"contacts_observed", "full_text_unavailable"}
    for contact in body["contacts_extracted"]:
        assert contact["content_digest"] and contact["evidence_excerpt"]
        assert contact["email"] in contact["evidence_excerpt"]


def test_foreign_org_is_not_found(client: TestClient) -> None:
    other = "/api/v1/organizations/00000000-0000-0000-0000-000000000002/open-access"
    assert client.post(f"{other}/discover", json={"query": "CRISPR"}).status_code == 404
    assert client.post(f"{other}/export", json={"query": "CRISPR"}).status_code == 404
    assert client.get(f"{other}/mesh", params={"q": "cancer"}).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"query": ""},
        {"query": "x" * 1001},
        {"query": "CRISPR", "max_results": 0},
        {"query": "CRISPR", "max_results": 101},
        {"query": "CRISPR", "source": "scihub"},
        {"query": "CRISPR", "unexpected": True},
    ],
)
def test_invalid_input_is_rejected(client: TestClient, payload: dict[str, object]) -> None:
    assert client.post(f"{BASE}/discover", json=payload).status_code == 422


def test_orchestrator_denial_is_a_safe_400(client: TestClient) -> None:
    response = client.post(f"{BASE}/discover", json={"query": "CRI\x00SPR"})
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_query"


def test_export_honours_suppression_and_sets_headers(client: TestClient) -> None:
    response = client.post(
        f"{BASE}/export",
        json={
            "query": "PMC7700001",
            "preset": "smartlead",
            "target_roles": "all",
            "suppressed_domains": ["lisbon.example"],
        },
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "smartlead" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    emails = {r["Email"] for r in rows}
    assert "lucia.ferreira@neuro.lisbon.example" not in emails
    assert "t.nowak@genetics.krakow.example" in emails
    assert "core-lab@genetics.krakow.example" not in emails  # unmatched, needs review

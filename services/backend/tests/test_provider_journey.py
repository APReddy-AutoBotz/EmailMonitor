"""Pure request/registry/retention contracts, not actual HTTPS/SQL evidence."""

import hashlib
import json
import re
from pathlib import Path
from uuid import UUID

import pytest
from emailmonitor.associations.mapping import map_observation
from emailmonitor.associations.models import Review
from emailmonitor.associations.review import apply_review
from emailmonitor.discovery.planning import plan_input
from emailmonitor.extraction.sciencedirect import parse_article
from emailmonitor.extraction.xml_retained import RetainedXml, XmlBinding, retain_xml
from emailmonitor.fetching.plan import HopPlanner, PlanScope
from emailmonitor.fetching.safety import FetchDenied, classify_url
from emailmonitor.fetching.sciencedirect import ProviderRequest
from emailmonitor.sources import provider_documents as catalog
from emailmonitor.sources.policy import Operation
from emailmonitor.sources.sciencedirect import ArticleIdentifier, SearchRequest, parse_search
from test_job_contracts import request_body
from test_xml_pipeline import SETTINGS

ROOT = Path(__file__).resolve().parents[3]


def registry() -> tuple[catalog.ProviderDocument, ...]:
    sql = (ROOT / "services/backend/migrations/versions/0013_provider_journey.sql").read_text()
    match = re.search(r"'\{provider_documents\}','(.*?)'::jsonb", sql)
    assert match
    return catalog.documents({"provider_documents": json.loads(match[1])}, catalog.SOURCE)


def xml_bytes(document: catalog.ProviderDocument) -> bytes:
    name = "provider-pii.xml" if document.identifier.kind == "pii" else "sciencedirect-article.xml"
    return (ROOT / "fixtures/xml" / name).read_bytes()


def retained(document: catalog.ProviderDocument, excerpts: bool = True) -> RetainedXml:
    return retain_xml(
        parse_article(xml_bytes(document), document.identifier),
        XmlBinding(
            organization=UUID(int=1),
            job=UUID(int=2),
            item=UUID(int=3),
            generation=1,
            deletion_generation=1,
            policy_version=1,
            discovery_revision=1,
        ),
        excerpts,
        registered=document,
    )


@pytest.mark.parametrize("document", registry())
def test_full_request_is_bound_through_shared_url_and_hop_plan(
    document: catalog.ProviderDocument,
) -> None:
    request = document.request
    assert request.plan().method == "GET" and request.plan().path.endswith("?view=FULL")
    assert request.fingerprint != ProviderRequest(article=document.identifier).fingerprint
    assert request.url != retained(document).canonical_url
    scope = PlanScope(
        UUID(int=1),
        "elsevier_sciencedirect_v2",
        1,
        Operation.XML,
        frozenset({"api.elsevier.com"}),
        20,
        0,
    )
    planner = HopPlanner(scope, lambda scope, url: None, lambda: 1)
    safe = planner.authorize_url(request.url)
    plan = planner.snapshot(safe, ("93.184.216.34",))
    assert plan.url.normalized == request.url
    assert safe.path == request.plan().path


@pytest.mark.parametrize(
    "suffix",
    [
        "?view=META",
        "?view=full",
        "?view=FULL&apiKey=x",
        "?view=FULL&view=FULL",
        "?view=FULL?",
        "?view=FULL#x",
    ],
)
def test_only_exact_typed_full_query_is_supported(suffix: str) -> None:
    with pytest.raises(FetchDenied):
        classify_url(
            "https://api.elsevier.com/content/article/doi/10.9999/synthetic.1" + suffix,
            frozenset({"api.elsevier.com"}),
        )
    with pytest.raises(FetchDenied):
        classify_url(
            "https://synthetic.publisher.example/article-xml.xml" + suffix,
            frozenset({"synthetic.publisher.example"}),
        )


def test_full_cannot_be_a_search_parameter() -> None:
    with pytest.raises(ValueError):
        ProviderRequest(search=SearchRequest(query="topic"), view="FULL")


@pytest.mark.parametrize("document", registry())
def test_generalized_retention_keeps_three_identities_and_requires_review(
    document: catalog.ProviderDocument,
) -> None:
    value = retained(document)
    assert value.content_digest == hashlib.sha256(xml_bytes(document)).hexdigest()
    assert value.status == "observed" and value.url == document.source_url
    assert value.provider is not None
    assert value.provider.source_id == catalog.SOURCE
    assert value.provider.acquisition_mode == "controlled_fixture"
    assert value.provider.transport_url == document.request.url
    bundle = map_observation(SETTINGS, UUID(int=1), value)
    assert {a.state for a in bundle.associations} == {"needs_review"}
    assert all(c.address.domain_status == "not_checked" for c in bundle.candidates)
    stripped = map_observation(SETTINGS, UUID(int=1), retained(document, False))
    association = stripped.associations[0]
    with pytest.raises(ValueError, match="retained"):
        apply_review(
            SETTINGS,
            stripped,
            Review(
                association_id=association.id,
                expected_revision=1,
                action="accept",
                evidence_ids=association.evidence_ids,
                reason="Locator-only evidence is not sufficient",
            ),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("identifier", ArticleIdentifier(kind="doi", value="10.9999/other")),
        ("content_digest", "0" * 64),
        ("source_profile", "xocs_document"),
    ],
)
def test_registry_mismatch_cannot_retain_first_document(field: str, value: object) -> None:
    document = registry()[0]
    with pytest.raises((ValueError, FetchDenied)):
        retained(document.model_copy(update={field: value}))


def test_search_identifiers_resolve_only_registered_aliases() -> None:
    request = SearchRequest(query=catalog.QUERY, show=10)
    pages = parse_search(
        json.dumps(
            {
                "resultsFound": 3,
                "results": [
                    {"doi": "10.9999/synthetic.1", "title": "One"},
                    {
                        "doi": "10.9999/synthetic.1",
                        "pii": "S0000000000000001",
                        "title": "Duplicate",
                    },
                    {"pii": "S0000000000000002", "title": "Two"},
                ],
            }
        ).encode(),
        request,
    )
    assert [catalog.for_article(registry(), a).source_url for a in pages.articles] == [
        catalog.DOI_URL,
        catalog.DOI_URL,
        catalog.PII_URL,
    ]
    bad = pages.articles[0].model_copy(update={"pii": "S0000000000000002"})
    with pytest.raises(FetchDenied):
        catalog.for_article(registry(), bad)


def test_distinct_keyword_keeps_original_fixture_plan() -> None:
    from emailmonitor.jobs.models import JobRequest

    body = request_body()
    body["input"] = {
        "type": "keyword",
        "source_id": catalog.SOURCE,
        "original_query": catalog.QUERY,
    }
    assert plan_input(JobRequest.model_validate(body)).start_url == catalog.SEARCH_URL
    body["input"] = {
        "type": "keyword",
        "source_id": catalog.SOURCE,
        "original_query": "Myocardial Infarction",
    }
    assert (
        plan_input(JobRequest.model_validate(body)).start_url
        == catalog.ORIGIN + "/search-page-1.html"
    )


def test_forward_migration_preserves_latest_privacy_lease_and_xml_guards() -> None:
    root = ROOT / "services/backend/migrations/versions"
    old = (root / "0012_xml_pipeline.sql").read_text()
    new = (root / "0013_provider_journey.sql").read_text()
    for clause in [
        "emailmonitor.privacy_payload_allowed(NEW.organization_id,NEW.observation)",
        "emailmonitor.privacy_excerpt_allowed(NEW.organization_id,NEW.observed_at,NEW.observation)",
        "deadline.excerpt_deadline<=clock_timestamp()",
        "current_setting('emailmonitor.execution_item',true)",
        "NEW.deletion_generation<>d.deletion_generation",
        "NEW.observation->>'isolation_profile' IS DISTINCT FROM 'network-none-parser-v1'",
        "'generation',NEW.generation,'deletion_generation',NEW.deletion_generation",
        "NEW.revision<>OLD.revision+1 OR OLD.observation->>'status'<>'requires_browser'",
    ]:
        assert clause in old and clause in new
    assert "GRANT " not in new and "DISABLE ROW" not in new
    assert "execution_item_route_kind" in new
    assert 'down_revision = "0012_xml_pipeline"' in (root / "0013_provider_journey.py").read_text()

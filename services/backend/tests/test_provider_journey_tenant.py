"""Real SQL boundaries; supplied host observations here are not transport proof.

The separate controlled acceptance sends actual HTTPS bytes through the isolated
parser and these same tenant services before review/export.
"""

import json
from uuid import UUID, uuid4

import pytest
from emailmonitor.discovery.service import Discovery
from emailmonitor.extraction.xml_retained import retain_xml
from emailmonitor.fetching.resources import HopResources
from emailmonitor.fetching.safety import FetchDenied, IsolationUnavailable
from emailmonitor.fetching.sciencedirect import AcquiredResponse, ProviderBoundary
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import bound
from emailmonitor.progress.provider import ProviderJourney
from emailmonitor.progress.service import Progress
from emailmonitor.sources import provider_documents as catalog
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_progress_tenant import claim
from test_provider_journey import registry, xml_bytes
from test_source_foundation import policy_body, source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario
from test_xml_pipeline_tenant import mutate_authority


class NoDispatch:
    def acquire(self, boundary: ProviderBoundary, *, resources: HopResources) -> AcquiredResponse:
        raise AssertionError("No network dispatch permitted in this SQL boundary test")


def planned_provider(
    s: Scenario, *, url: str | None = None, excerpts: bool = True, max_articles: int = 10
) -> tuple[Progress, UUID]:
    operations = ["search", "fetch_xml", "extract_contacts", "export_contacts"]
    if excerpts:
        operations.append("retain_excerpt")
    with s.client() as client:
        csrf = s.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(s)
        policy = policy_body(
            allowed_operations=operations,
            retention={"raw_hours": 0, "excerpt_days": 30 if excerpts else 0, "contact_days": 90},
        )
        response = client.post(
            path + "/policies", headers=headers, json={"expected_version": 0, "policy": policy}
        )
        assert response.status_code == 201, response.text
        assert (
            client.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 200
        )
        ledger = Ledger(s.foundation.database, str(client.cookies[COOKIE]), SETTINGS)
    body = request_body()
    body["input"] = (
        {"type": "url", "url": url}
        if url
        else {"type": "keyword", "source_id": catalog.SOURCE, "original_query": catalog.QUERY}
    )
    options = body["options"]
    assert isinstance(options, dict)
    options["max_articles"] = max_articles
    job = ledger.create(s.organizations[0], JobRequest.model_validate(body), str(uuid4()))
    Discovery(ledger.database, ledger.token, SETTINGS).plan(s.organizations[0], job, 1)
    return Progress(ledger.database, ledger.token, SETTINGS), job


@pytest.mark.parametrize(
    "kind",
    [
        "cancel",
        "pause",
        "delete",
        "expired_lease",
        "lost_lease",
        "revoked_policy",
        "revoked_session",
        "expired_session",
    ],
)
def test_sql_current_authority_never_reuses_provider_binding(scenario: Scenario, kind: str) -> None:
    progress, job = planned_provider(scenario, url=catalog.DOI_URL)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)
    journey = ProviderJourney(progress, NoDispatch())
    with bound(work.lease):
        boundary, _ = journey.boundary(work)
        mutate_authority(scenario, progress, job, kind)
        with pytest.raises((FetchDenied, AuthorizationDenied, DBAPIError, HTTPException)):
            boundary.check_current()


def test_keyword_plan_has_no_implicit_dispatch_and_no_live_policy(scenario: Scenario) -> None:
    progress, job = planned_provider(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)
    assert work.kind == "discover" and work.url == catalog.SEARCH_URL
    with pytest.raises(IsolationUnavailable, match="controlled_provider_dispatch_required"):
        progress.process_fixture(work)
    with bound(work.lease):
        boundary, values = ProviderJourney(progress, NoDispatch()).boundary(work)
        assert (
            boundary.request.search is not None and boundary.request.search.query == catalog.QUERY
        )
        assert len(values) == 2
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        sources = c.execute(
            text("SELECT source_id,allowed_hosts FROM emailmonitor.source_catalog")
        ).all()
        assert sources == [(catalog.SOURCE, ["synthetic.publisher.example"])]


@pytest.mark.parametrize(
    "field,value",
    [
        ("transport_url", "https://api.elsevier.com/content/article/doi/10.9999/synthetic.1"),
        ("source_id", "another-source"),
        ("request_fingerprint", "0" * 64),
        ("acquisition_mode", "live"),
        ("requested_view", "META"),
    ],
)
def test_sql_rejects_forged_provider_provenance(scenario: Scenario, field: str, value: str) -> None:
    from emailmonitor.extraction.sciencedirect import parse_article

    progress, job = planned_provider(scenario, url=catalog.DOI_URL)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)
    journey = ProviderJourney(progress, NoDispatch())
    document = registry()[0]
    with bound(work.lease):
        binding, excerpts = journey.xml.binding(org, job, work.discovery_revision, work.url)
        retained = retain_xml(
            parse_article(xml_bytes(document), document.identifier),
            binding,
            excerpts,
            registered=document,
        )
        payload = retained.model_dump(mode="json")
        payload["provider"][field] = value
        with pytest.raises(DBAPIError):
            with progress.database.tenant(progress.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
                c.execute(
                    text("""INSERT INTO emailmonitor.article_observations
(organization_id,job_id,article_url,generation,deletion_generation,policy_version,discovery_revision,source_digest,observation)
VALUES(:org,:job,:url,:generation,:deletion,:policy,:revision,:digest,CAST(:payload AS jsonb))"""),
                    {
                        "org": org,
                        "job": job,
                        "url": work.url,
                        "generation": binding.generation,
                        "deletion": binding.deletion_generation,
                        "policy": binding.policy_version,
                        "revision": binding.discovery_revision,
                        "digest": retained.content_digest,
                        "payload": json.dumps(payload),
                    },
                )


def test_sql_generalized_retention_and_registry_are_not_caller_authority(
    scenario: Scenario,
) -> None:
    from emailmonitor.extraction.sciencedirect import parse_article

    progress, job = planned_provider(scenario, url=catalog.PII_URL)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)
    journey = ProviderJourney(progress, NoDispatch())
    document = registry()[1]
    with bound(work.lease):
        binding, excerpts = journey.xml.binding(org, job, work.discovery_revision, work.url)
        retained = retain_xml(
            parse_article(xml_bytes(document), document.identifier),
            binding,
            excerpts,
            registered=document,
        )
        assert (
            journey.xml.commit_xml(org, job, retained)["source_digest"] == document.content_digest
        )
        # Recovery consumes the committed row; this dispatch would fail if called.
        assert journey.process(work) == "needs_review"
    admin = create_engine(scenario.admin_url)
    try:
        with admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.execution_effects "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": job},
                ).scalar_one()
                == 1
            )
    finally:
        admin.dispose()
    # Let the denied statement unwind the tenant transaction before catching it.
    with pytest.raises(DBAPIError) as denied:
        with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
            c.execute(
                text(
                    "UPDATE emailmonitor.source_catalog SET support='{}'::jsonb "
                    "WHERE source_id='synthetic-publisher'"
                )
            )

    assert denied.value.orig is not None
    detail = denied.value.orig.args[0]
    assert isinstance(detail, dict) and detail.get("C") == "42501"
    # A fresh transaction remains usable after the expected privilege denial.
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert c.execute(text("SELECT 1")).scalar_one() == 1

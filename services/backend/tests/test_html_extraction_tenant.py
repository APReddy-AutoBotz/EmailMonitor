"""Actual runtime-role observation fences; no acquired publisher bytes."""

from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from api_client import APIClient
from emailmonitor.api import create_app
from emailmonitor.discovery.fixture import step_fixture
from emailmonitor.discovery.service import Discovery
from emailmonitor.extraction.fixture import DIGESTS
from emailmonitor.extraction.html import ArticleObservation, parse_article
from emailmonitor.extraction.service import Extraction
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from fastapi import HTTPException
from sqlalchemy import text
from test_durable_jobs import SETTINGS
from test_html_extraction import ORIGIN as SOURCE
from test_html_extraction import payload
from test_job_contracts import request_body
from test_source_foundation import policy_body, source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario


def extraction_policy() -> dict[str, object]:
    return policy_body(
        allowed_operations=[
            "search",
            "fetch_html",
            "extract_contacts",
            "retain_excerpt",
            "export_contacts",
        ]
    )


def test_extraction_synthetic_approval_is_explicit_and_does_not_change_shared_defaults() -> None:
    assert "extract_contacts" in cast(list[str], extraction_policy()["allowed_operations"])
    assert "extract_contacts" not in cast(list[str], policy_body()["allowed_operations"])


def approved(s: Scenario) -> Ledger:
    with s.client() as client:
        csrf = s.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(s)
        assert (
            client.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 0, "policy": extraction_policy()},
            ).status_code
            == 201
        )
        assert (
            client.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 200
        )
        return Ledger(s.foundation.database, str(client.cookies[COOKIE]), SETTINGS)


def begin(s: Scenario, *, articles: int = 500) -> tuple[Discovery, UUID]:
    ledger = approved(s)
    body = request_body()
    body["input"] = {
        "type": "keyword",
        "source_id": "synthetic-publisher",
        "original_query": "Myocardial Infarction",
    }
    body["options"] = {"max_articles": articles, "max_search_pages": 100, "author_target": "both"}
    job = ledger.create(s.organizations[0], JobRequest.model_validate(body), str(uuid4()))
    discovery = Discovery(ledger.database, ledger.token, SETTINGS)
    discovery.plan(s.organizations[0], job, 1)
    return discovery, job


def ready(s: Scenario) -> tuple[Extraction, UUID]:
    discovery, job = begin(s)
    step_fixture(discovery, s.organizations[0], job, 1)
    step_fixture(discovery, s.organizations[0], job, 2)
    return Extraction(discovery.database, discovery.token, SETTINGS), job


def test_real_author_observations_are_idempotent_separate_from_accepted_contacts(
    scenario: Scenario,
) -> None:
    extraction, job = ready(scenario)
    org = scenario.organizations[0]
    for name in DIGESTS:
        first = extraction.fixture(org, job, SOURCE + "/" + name, 3)
        assert first["revision"] == 1
        replay = extraction.fixture(org, job, SOURCE + "/" + name, 3)
        assert first["observed_at"] == replay["observed_at"]
        assert replay["revision"] == 1
    rows = extraction.read(org, job)
    assert len(rows) == 4
    observations = {
        str(row["article_url"]): ArticleObservation.model_validate(row["observation"])
        for row in rows
    }
    assert observations[SOURCE + "/tooltip.html"].status == "requires_browser"
    assert observations[SOURCE + "/no-contact.html"].status == "no_contact"
    assert sum(len(item.candidates) for item in observations.values()) == 3
    with extraction.database.tenant(extraction.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.audit_events "
                    "WHERE organization_id=:org AND resource_id=:job "
                    "AND action='extraction.observation_committed'"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            == 4
        )
        for table in ("job_items", "usage_events"):
            assert (
                c.execute(
                    text(
                        f"SELECT count(*) FROM emailmonitor.{table} "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": job},
                ).scalar_one()
                == 0
            )
        assert (
            c.execute(
                text("SELECT state FROM emailmonitor.jobs WHERE organization_id=:org AND id=:job"),
                {"org": org, "job": job},
            ).scalar_one()
            == "draft"
        )
        assert c.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class "
                "WHERE oid='emailmonitor.article_observations'::regclass"
            )
        ).scalar_one()
        assert not c.execute(
            text(
                "SELECT has_table_privilege(current_user,"
                "'emailmonitor.article_observations','DELETE')"
            )
        ).scalar_one()


def test_real_cross_tenant_viewer_and_forged_api_observation_refused(scenario: Scenario) -> None:
    extraction, job = ready(scenario)
    org = scenario.organizations[0]
    extraction.fixture(org, job, SOURCE + "/article-a.html", 3)
    with APIClient(
        create_app(SETTINGS.model_copy(update={"identity_stub": True}), scenario.foundation),
        base_url=ORIGIN,
    ) as client:
        scenario.login(client, "owner_b")
        other = Extraction(extraction.database, str(client.cookies[COOKIE]), SETTINGS)
        with pytest.raises(AuthorizationDenied):
            other.read(org, job)
        with pytest.raises(AuthorizationDenied):
            other.fixture(org, job, SOURCE + "/article-a.html", 3)
        csrf = scenario.login(client, "viewer")
        viewer = Extraction(extraction.database, str(client.cookies[COOKIE]), SETTINGS)
        assert len(viewer.read(org, job)) == 1
        with pytest.raises(AuthorizationDenied):
            viewer.fixture(org, job, SOURCE + "/article-a.html", 3)
        csrf = scenario.login(client, "owner")
        path = f"/api/v1/organizations/{org}/jobs/{job}/extract-fixture-article"
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        assert (
            client.post(
                path,
                headers=headers,
                json={"expected_revision": 3, "article_url": SOURCE + "/article-b.html"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                path,
                headers=headers,
                json={
                    "expected_revision": 3,
                    "article_url": SOURCE + "/article-b.html",
                    "html": "fabricated@example.org",
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                path,
                headers=headers,
                json={"expected_revision": 3, "article_url": "https://outside.example"},
            ).status_code
            == 422
        )
        assert client.get(path.rsplit("/", 1)[0] + "/article-observations").status_code == 200


def test_real_ordinary_operator_extracts_without_catalog_write_grant(scenario: Scenario) -> None:
    approved(scenario)
    org = scenario.organizations[0]
    with APIClient(
        create_app(SETTINGS.model_copy(update={"identity_stub": True}), scenario.foundation),
        base_url=ORIGIN,
    ) as client:
        scenario.login(client, "operator")
        token = str(client.cookies[COOKIE])
        request = request_body()
        request["input"] = {"type": "url", "url": SOURCE + "/article-a.html"}
        ledger = Ledger(scenario.foundation.database, token, SETTINGS)
        job = ledger.create(org, JobRequest.model_validate(request), str(uuid4()))
        discovery = Discovery(ledger.database, token, SETTINGS)
        row = discovery.plan(org, job, 1)
        extraction = Extraction(ledger.database, token, SETTINGS)
        result = extraction.fixture(org, job, SOURCE + "/article-a.html", int(str(row["revision"])))
        assert ArticleObservation.model_validate(result["observation"]).candidates[
            0
        ].author_positions == [2]
        with ledger.database.tenant(token, org, Capability.READ_ORGANIZATION) as (c, _):
            assert not c.execute(
                text(
                    "SELECT has_table_privilege(current_user,"
                    "'emailmonitor.source_catalog','UPDATE')"
                )
            ).scalar_one()


@pytest.mark.parametrize("action", ["cancel", "revoke", "offboard"])
def test_real_current_job_source_deletion_fence_before_commit(
    scenario: Scenario, action: str
) -> None:
    extraction, job = ready(scenario)
    org = scenario.organizations[0]
    if action == "revoke":
        extraction.fixture(org, job, SOURCE + "/article-b.html", 3)
        assert len(extraction.read(org, job)) == 1
    extraction.prepare(org, job, SOURCE + "/article-a.html")
    observation = parse_article(SETTINGS, SOURCE + "/article-a.html", payload("article-a.html"))
    with APIClient(
        create_app(SETTINGS.model_copy(update={"identity_stub": True}), scenario.foundation),
        base_url=ORIGIN,
    ) as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        if action == "cancel":
            Ledger(extraction.database, extraction.token, SETTINGS).control(org, job, "cancel", 1)
        elif action == "revoke":
            assert (
                client.post(
                    source_path(scenario) + "/policy-state",
                    headers=headers,
                    json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
                ).status_code
                == 200
            )
        else:
            assert (
                client.post(
                    f"/api/v1/organizations/{org}/lifecycle",
                    headers=headers,
                    json={"status": "offboarding", "expected_revision": 1},
                ).status_code
                == 200
            )
    if action == "revoke":
        assert extraction.read(org, job) == []
    with pytest.raises((AuthorizationDenied, HTTPException)):
        extraction.commit(
            org, job, observation, expected_revision=3, source_digest=DIGESTS["article-a.html"]
        )


def test_real_undiscovered_article_and_stale_revision_refused(scenario: Scenario) -> None:
    discovery, job = begin(scenario, articles=1)
    step_fixture(discovery, scenario.organizations[0], job, 1)
    extraction = Extraction(discovery.database, discovery.token, SETTINGS)
    with pytest.raises(AuthorizationDenied):
        extraction.fixture(scenario.organizations[0], job, SOURCE + "/article-b.html", 2)
    with pytest.raises(HTTPException):
        extraction.fixture(scenario.organizations[0], job, SOURCE + "/article-a.html", 1)


@pytest.mark.parametrize(
    "permission", ["no_extract", "no_contact_retention", "no_excerpt", "wrong_purpose"]
)
def test_real_collection_and_excerpt_retention_are_separate_permissions(
    scenario: Scenario, permission: str
) -> None:
    approved(scenario)
    org = scenario.organizations[0]
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        token = str(client.cookies[COOKIE])
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        policy = extraction_policy()
        if permission == "no_extract":
            cast(list[str], policy["allowed_operations"]).remove("extract_contacts")
        elif permission == "no_contact_retention":
            cast(dict[str, int], policy["retention"])["contact_days"] = 0
        elif permission == "no_excerpt":
            cast(list[str], policy["allowed_operations"]).remove("retain_excerpt")
            cast(dict[str, int], policy["retention"])["excerpt_days"] = 0
        path = source_path(scenario)
        assert (
            client.post(
                path + "/policies", headers=headers, json={"expected_version": 1, "policy": policy}
            ).status_code
            == 201
        )
        assert (
            client.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 2, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 200
        )
        body = request_body()
        body["input"] = {"type": "url", "url": SOURCE + "/article-a.html"}
        if permission == "wrong_purpose":
            body["purpose"] = "unapproved_purpose"
        ledger = Ledger(scenario.foundation.database, token, SETTINGS)
        job = ledger.create(org, JobRequest.model_validate(body), str(uuid4()))
        discovery = Discovery(ledger.database, token, SETTINGS)
        row = discovery.plan(org, job, 1)
        extraction = Extraction(ledger.database, token, SETTINGS)
        if permission != "no_excerpt":
            with pytest.raises((AuthorizationDenied, HTTPException)):
                extraction.fixture(org, job, SOURCE + "/article-a.html", int(str(row["revision"])))
            assert extraction.read(org, job) == []
        else:
            saved = extraction.fixture(
                org, job, SOURCE + "/article-a.html", int(str(row["revision"]))
            )
            observed = ArticleObservation.model_validate(saved["observation"])
            assert observed.candidates[0].raw_address == "alex.chen@example.org"
            assert not observed.candidates[0].evidence.excerpt
            assert all(not fact.evidence.excerpt for fact in observed.metadata)
            assert all(
                not evidence.excerpt for author in observed.authors for evidence in author.evidence
            )
            assert isinstance(saved["expires_at"], datetime)
            assert isinstance(saved["observed_at"], datetime)
            assert saved["expires_at"] > saved["observed_at"]

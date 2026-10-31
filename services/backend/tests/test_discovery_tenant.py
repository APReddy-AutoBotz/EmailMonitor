"""Real PostgreSQL discovery fences and fixture API; never acquires live bytes."""

from typing import cast
from uuid import UUID, uuid4

import pytest
from api_client import APIClient
from emailmonitor.api import create_app
from emailmonitor.discovery.fixture import step_fixture
from emailmonitor.discovery.service import Discovery
from emailmonitor.discovery.state import DiscoveryState
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from fastapi import HTTPException
from sqlalchemy import text
from test_discovery import page
from test_durable_jobs import SETTINGS, approved, snapshot
from test_job_contracts import request_body
from test_source_foundation import policy_body, source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario


def begin(s: Scenario, *, articles: int = 500, pages: int = 100) -> tuple[Discovery, UUID]:
    ledger = approved(s)
    body = request_body()
    body["input"] = {
        "type": "keyword",
        "source_id": "synthetic-publisher",
        "original_query": "Myocardial Infarction",
    }
    body["options"] = {"max_articles": articles, "max_search_pages": pages, "author_target": "both"}
    job = ledger.create(s.organizations[0], JobRequest.model_validate(body), str(uuid4()))
    discovery = Discovery(ledger.database, ledger.token, SETTINGS)
    discovery.plan(s.organizations[0], job, 1)
    return discovery, job


@pytest.mark.parametrize("date_type", ["published", "online", "issue"])
def test_real_date_request_is_retained_but_plan_has_no_discovery(
    scenario: Scenario, date_type: str
) -> None:
    ledger = approved(scenario)
    org = scenario.organizations[0]
    body = request_body()
    body["input"] = {
        "type": "keyword",
        "source_id": "synthetic-publisher",
        "original_query": "Myocardial Infarction",
    }
    body["filters"] = {"publication_date_type": date_type, "publication_from": "2026-01-15"}
    request = JobRequest.model_validate(body)
    key = str(uuid4())
    job = ledger.create(org, request, key)
    assert ledger.create(org, request, key) == job
    discovery = Discovery(ledger.database, ledger.token, SETTINGS)
    result = discovery.plan(org, job, 1)
    assert result["persisted"] is False
    plan = cast(dict[str, object], result["plan"])
    assert plan["classification"] == "unsupported"
    assert plan["reason"] == "fixture_filters_unavailable"
    saved = snapshot(ledger, org, job)
    assert saved["state"] == "draft"
    saved_request = cast(dict[str, object], saved["request"])
    filters = cast(dict[str, object], saved_request["filters"])
    assert filters["publication_date_type"] == date_type
    assert filters["publication_from"] == "2026-01-15"
    with pytest.raises(HTTPException):
        discovery.prepare(org, job)


@pytest.mark.parametrize(
    "filters",
    [
        {"journal": ""},
        {"journal": "Synthetic Journal A"},
        {"article_types": ["review"]},
        {"journal": "Synthetic Journal A", "article_types": ["review"]},
    ],
)
def test_real_unsupported_journal_and_type_remain_draft_without_discovery(
    scenario: Scenario, filters: dict[str, object]
) -> None:
    ledger = approved(scenario)
    org = scenario.organizations[0]
    body = request_body()
    body["input"] = {
        "type": "keyword",
        "source_id": "synthetic-publisher",
        "original_query": "Myocardial Infarction",
    }
    body["filters"] = filters
    request = JobRequest.model_validate(body)
    key = str(uuid4())
    job = ledger.create(org, request, key)
    assert ledger.create(org, request, key) == job
    discovery = Discovery(ledger.database, ledger.token, SETTINGS)
    result = discovery.plan(org, job, 1)
    assert result["persisted"] is False
    plan = cast(dict[str, object], result["plan"])
    assert plan["classification"] == "unsupported"
    assert plan["reason"] == "fixture_filters_unavailable" and plan["start_url"] is None
    saved = snapshot(ledger, org, job)
    assert saved["state"] == "draft"
    saved_request = cast(dict[str, object], saved["request"])
    for field, value in filters.items():
        assert cast(dict[str, object], saved_request["filters"])[field] == value
    with pytest.raises(HTTPException):
        discovery.prepare(org, job)


def test_real_reuse_refusal_creates_no_job_or_idempotency_receipt(scenario: Scenario) -> None:
    ledger = approved(scenario)
    org, key = scenario.organizations[0], str(uuid4())
    body = request_body()
    body["input"] = {
        "type": "keyword",
        "source_id": "synthetic-publisher",
        "original_query": "Myocardial Infarction",
    }
    choice = {"mode": "verified_retained", "fresh_since": "2026-10-01T13:00:00Z"}

    def counts() -> tuple[int, int]:
        with ledger.database.tenant(ledger.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
            jobs: int = c.execute(
                text("SELECT count(*) FROM emailmonitor.jobs WHERE organization_id=:org"),
                {"org": org},
            ).scalar_one()
            keys: int = c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.job_idempotency WHERE organization_id=:org"
                ),
                {"org": org},
            ).scalar_one()
            return int(jobs), int(keys)

    before = counts()
    with pytest.raises(HTTPException) as failure:
        ledger.create(org, JobRequest.model_validate({**body, "reuse": choice}), key)
    assert failure.value.status_code == 409 and counts() == before
    fresh = JobRequest.model_validate(body)
    job = ledger.create(org, fresh, key)
    assert ledger.create(org, fresh, key) == job
    result = Discovery(ledger.database, ledger.token, SETTINGS).plan(org, job, 1)
    assert result["job_id"] == job
    assert cast(dict[str, object], result["checkpoint"])["status"] == "pending"


def test_real_work_read_keeps_request_private_and_preserves_tenant_fence(
    scenario: Scenario,
) -> None:
    discovery, job = begin(scenario)
    org, other = scenario.organizations
    checkpoint, request = discovery.read_for_work(org, job)
    assert checkpoint == discovery.read(org, job)
    assert request.reuse is None
    assert "work_request" not in checkpoint
    with scenario.client() as c:
        scenario.login(c, "owner_b")
        foreign = Discovery(discovery.database, str(c.cookies[COOKIE]), SETTINGS)
        with pytest.raises(AuthorizationDenied):
            foreign.read_for_work(other, job)
        with pytest.raises(AuthorizationDenied):
            foreign.read_for_work(org, job)


def test_real_checkpoint_restart_replay_and_no_contact_or_usage(scenario: Scenario) -> None:
    discovery, job = begin(scenario)
    org = scenario.organizations[0]
    first = step_fixture(discovery, org, job, 1)
    assert first["revision"] == 2
    assert discovery.commit(org, job, 1, page(1))["revision"] == 2
    restored = Discovery(discovery.database, discovery.token, SETTINGS)
    final = step_fixture(restored, org, job, 2)
    state = DiscoveryState.model_validate(final["checkpoint"])
    assert state.status == "completed" and len(state.articles) == 4
    assert state.raw_entries == 5 and state.duplicates == 1
    assert final["revision"] == 3
    assert discovery.commit(org, job, 2, page(2))["revision"] == 3
    assert snapshot(approved_ledger(discovery), org, job)["state"] == "draft"
    with discovery.database.tenant(discovery.token, org, Capability.READ_ORGANIZATION) as (c, _):
        for table in ("job_items", "job_outbox", "usage_events"):
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
                text(
                    "SELECT count(*) FROM emailmonitor.audit_events "
                    "WHERE organization_id=:org AND resource_id=:job "
                    "AND action='discovery.page_committed'"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            == 2
        )


def approved_ledger(discovery: Discovery) -> Ledger:
    return Ledger(discovery.database, discovery.token, SETTINGS)


@pytest.mark.parametrize(
    "articles,pages,reason",
    [(1, 100, "article_cap"), (2, 100, "article_cap"), (500, 1, "page_cap")],
)
def test_real_durable_partial_caps(
    scenario: Scenario, articles: int, pages: int, reason: str
) -> None:
    discovery, job = begin(scenario, articles=articles, pages=pages)
    result = step_fixture(discovery, scenario.organizations[0], job, 1)
    assert DiscoveryState.model_validate(result["checkpoint"]).reason == reason
    assert discovery.pending(scenario.organizations[0]) == []
    with pytest.raises(HTTPException):
        discovery.prepare(scenario.organizations[0], job)


def test_real_cross_tenant_and_viewer_write_refusal(scenario: Scenario) -> None:
    discovery, job = begin(scenario)
    with scenario.client() as client:
        scenario.login(client, "owner_b")
        other = Discovery(discovery.database, str(client.cookies[COOKIE]), SETTINGS)
        with pytest.raises(AuthorizationDenied):
            other.read(scenario.organizations[0], job)
        with pytest.raises(AuthorizationDenied):
            other.commit(scenario.organizations[0], job, 1, page(1))
        scenario.login(client, "viewer")
        viewer = Discovery(discovery.database, str(client.cookies[COOKIE]), SETTINGS)
        assert viewer.read(scenario.organizations[0], job)["revision"] == 1
        with pytest.raises(AuthorizationDenied):
            viewer.commit(scenario.organizations[0], job, 1, page(1))


def test_real_stale_revision_changed_page_and_cancel_refuse(scenario: Scenario) -> None:
    discovery, job = begin(scenario)
    org = scenario.organizations[0]
    with pytest.raises(HTTPException):
        discovery.commit(org, job, 99, page(1))
    discovery.commit(org, job, 1, page(1))
    with pytest.raises(HTTPException):
        discovery.commit(org, job, 1, page(1).model_copy(update={"digest": "a" * 64}))
    approved_ledger(discovery).control(org, job, "cancel", 1)
    with pytest.raises(AuthorizationDenied):
        discovery.commit(org, job, 2, page(2))
    assert discovery.read(org, job)["revision"] == 2


@pytest.mark.parametrize("change", ["revoke", "new_version", "delete"])
def test_real_current_policy_and_deletion_barrier(scenario: Scenario, change: str) -> None:
    discovery, job = begin(scenario)
    org = scenario.organizations[0]
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        if change == "revoke":
            response = client.post(
                source_path(scenario) + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
            )
        elif change == "new_version":
            response = client.post(
                source_path(scenario) + "/policies",
                headers=headers,
                json={"expected_version": 1, "policy": policy_body()},
            )
        else:
            route = f"/api/v1/organizations/{org}/lifecycle"
            response = client.post(
                route, headers=headers, json={"status": "offboarding", "expected_revision": 1}
            )
        assert response.status_code in (200, 201), response.text
    with pytest.raises((AuthorizationDenied, HTTPException)):
        discovery.commit(org, job, 1, page(1))
    if change != "delete":
        assert discovery.pending(org) == []


def test_real_api_plans_and_advances_only_fixed_authored_fixtures(scenario: Scenario) -> None:
    approved(scenario)
    with APIClient(
        create_app(SETTINGS.model_copy(update={"identity_stub": True}), scenario.foundation),
        base_url=ORIGIN,
    ) as client:
        csrf = scenario.login(client, "operator")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())}
        root = f"/api/v1/organizations/{scenario.organizations[0]}/jobs"
        body = request_body()
        body["input"] = {
            "type": "keyword",
            "source_id": "synthetic-publisher",
            "original_query": "Myocardial Infarction",
        }
        body["options"] = {"max_articles": 500, "max_search_pages": 2, "author_target": "both"}
        response = client.post(root, headers=headers, json=body)
        assert response.status_code == 201
        job = response.json()["id"]
        path = root + "/" + job
        assert (
            client.post(path + "/plan", headers=headers, json={"expected_revision": 1}).status_code
            == 200
        )
        assert (
            client.post(
                path + "/discover-fixture-page", headers=headers, json={"expected_revision": 1}
            ).status_code
            == 200
        )
        final = client.post(
            path + "/discover-fixture-page", headers=headers, json={"expected_revision": 2}
        )
        assert final.status_code == 200 and final.json()["checkpoint"]["status"] == "completed"
        assert client.get(path + "/discovery").json()["revision"] == 3
        assert (
            client.post(
                path + "/discover-fixture-page",
                headers=headers,
                json={"expected_revision": 3, "url": "https://outside.example"},
            ).status_code
            == 422
        )


def test_real_outbox_successors_and_uncertain_publish_replay(scenario: Scenario) -> None:
    discovery, job = begin(scenario)
    org = scenario.organizations[0]
    first = discovery.pending(org)[0]
    discovery.confirmed(org, job, UUID(str(first["event_id"])))
    # Confirmation is transport evidence, not completion. Until a checkpoint
    # commits the same identifier remains safely redispatchable after a crash.
    assert discovery.pending(org)[0]["event_id"] == first["event_id"]
    step_fixture(discovery, org, job, 1)
    successor = discovery.pending(org)[0]
    assert successor["revision"] == 2 and successor["event_id"] != first["event_id"]
    step_fixture(discovery, org, job, 2)
    assert discovery.pending(org) == []


def test_real_changed_selector_commits_truthful_partial_and_no_successor(
    scenario: Scenario,
) -> None:
    discovery, job = begin(scenario)
    org = scenario.organizations[0]
    changed = page(1).model_copy(update={"selector_valid": False})
    result = discovery.commit(org, job, 1, changed)
    checkpoint = DiscoveryState.model_validate(result["checkpoint"])
    assert checkpoint.reason == "selectors_changed" and not checkpoint.discovery_complete
    assert not checkpoint.articles and not discovery.pending(org)
    assert snapshot(approved_ledger(discovery), org, job)["discovery_complete"] is False


@pytest.mark.parametrize("cap", [1, 2])
def test_real_source_cap_is_distinct_from_user_cap(scenario: Scenario, cap: int) -> None:
    discovery, _ = begin(scenario)
    org = scenario.organizations[0]
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        limits = {
            "max_concurrent_requests": 1,
            "min_request_interval_seconds": 5,
            "max_articles_per_job": cap,
        }
        path = source_path(scenario)
        assert (
            client.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 1, "policy": policy_body(limits=limits)},
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
    body["input"] = {
        "type": "keyword",
        "source_id": "synthetic-publisher",
        "original_query": "Myocardial Infarction",
    }
    body["options"] = {"max_articles": 500, "max_search_pages": 2, "author_target": "both"}
    job = approved_ledger(discovery).create(org, JobRequest.model_validate(body), str(uuid4()))
    discovery.plan(org, job, 1)
    result = step_fixture(discovery, org, job, 1)
    assert DiscoveryState.model_validate(result["checkpoint"]).reason == "source_cap"
    assert discovery.pending(org) == []


def test_real_expiry_after_plan_prevents_page_commit(scenario: Scenario) -> None:
    import time
    from datetime import UTC, datetime, timedelta

    discovery, _ = begin(scenario)
    org = scenario.organizations[0]
    expiry = datetime.now(UTC) + timedelta(seconds=8)
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(scenario)
        assert (
            client.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 1, "policy": policy_body(valid_until=expiry.isoformat())},
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
    body["input"] = {
        "type": "keyword",
        "source_id": "synthetic-publisher",
        "original_query": "Myocardial Infarction",
    }
    job = approved_ledger(discovery).create(org, JobRequest.model_validate(body), str(uuid4()))
    discovery.plan(org, job, 1)
    time.sleep(max(0, (expiry - datetime.now(UTC)).total_seconds()) + 0.05)
    with pytest.raises(AuthorizationDenied):
        discovery.commit(org, job, 1, page(1))
    assert discovery.read(org, job)["revision"] == 1
    assert discovery.pending(org) == []


def test_real_discovery_catalog_permission_assertions(scenario: Scenario) -> None:
    discovery, _ = begin(scenario)
    org = scenario.organizations[0]
    with discovery.database.tenant(discovery.token, org, Capability.READ_ORGANIZATION) as (c, _):
        for table in ("discovery", "discovery_outbox"):
            row = c.execute(
                text("""SELECT relrowsecurity,relforcerowsecurity FROM pg_class
WHERE oid=CAST(:name AS regclass)"""),
                {"name": "emailmonitor." + table},
            ).one()
            assert row == (True, True)
            assert c.execute(
                text("SELECT has_table_privilege(current_user,:name,'SELECT,INSERT,UPDATE')"),
                {"name": "emailmonitor." + table},
            ).scalar_one()
            assert not c.execute(
                text("SELECT has_table_privilege(current_user,:name,'DELETE')"),
                {"name": "emailmonitor." + table},
            ).scalar_one()
            assert not c.execute(
                text("SELECT has_table_privilege('emailmonitor_authenticator',:name,'SELECT')"),
                {"name": "emailmonitor." + table},
            ).scalar_one()


def test_real_operator_source_less_url_plan_without_catalog_write_grant(scenario: Scenario) -> None:
    approved(scenario)
    with APIClient(
        create_app(SETTINGS.model_copy(update={"identity_stub": True}), scenario.foundation),
        base_url=ORIGIN,
    ) as client:
        csrf = scenario.login(client, "operator")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())}
        root = f"/api/v1/organizations/{scenario.organizations[0]}/jobs"
        body = request_body()
        body["input"] = {"type": "url", "url": "https://synthetic.publisher.example/article-a.html"}
        response = client.post(root, headers=headers, json=body)
        assert response.status_code == 201
        path = root + "/" + response.json()["id"]
        planned = client.post(path + "/plan", headers=headers, json={"expected_revision": 1})
        assert planned.status_code == 200, planned.text
        assert planned.json()["checkpoint"]["discovery_complete"] is True
        token = str(client.cookies[COOKIE])
        with scenario.foundation.database.tenant(
            token, scenario.organizations[0], Capability.READ_ORGANIZATION
        ) as (c, _):
            assert not c.execute(
                text(
                    "SELECT has_table_privilege(current_user,"
                    "'emailmonitor.source_catalog','UPDATE')"
                )
            ).scalar_one()
            assert c.execute(
                text(
                    "SELECT has_function_privilege(current_user,"
                    "'emailmonitor.discovery_source_fence(uuid,uuid,bigint)','EXECUTE')"
                )
            ).scalar_one()
            assert not c.execute(
                text(
                    "SELECT has_function_privilege('emailmonitor_authenticator',"
                    "'emailmonitor.discovery_source_fence(uuid,uuid,bigint)','EXECUTE')"
                )
            ).scalar_one()

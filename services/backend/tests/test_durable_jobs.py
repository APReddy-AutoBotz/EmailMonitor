"""Real PostgreSQL fixture ledger regressions, without source acquisition."""

import time
from uuid import UUID, uuid4

import pytest
from emailmonitor.config import Settings
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger, Work
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from sqlalchemy import text
from test_source_foundation import policy_body, source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario

SETTINGS = Settings(environment="test", fixture_mode=True)


def approved(s: Scenario) -> Ledger:
    with s.client() as client:
        csrf = s.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(s)
        assert (
            client.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 0, "policy": policy_body()},
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


def snapshot(ledger: Ledger, org: UUID, job: UUID) -> dict[str, object]:
    with ledger.database.tenant(ledger.token, org, Capability.READ_ORGANIZATION) as (c, _):
        return dict(
            c.execute(
                text("SELECT * FROM emailmonitor.jobs WHERE organization_id=:org AND id=:job"),
                {"org": org, "job": job},
            )
            .mappings()
            .one()
        )


def test_probe_commits_one_effect_usage_and_transactional_completion(scenario: Scenario) -> None:
    ledger = approved(scenario)
    org = scenario.organizations[0]
    job = ledger.create_probe(org, 1)
    work = ledger.outbox(org)[0]
    lease = ledger.claim(work)
    assert lease is not None
    assert ledger.claim(work) is None
    assert ledger.commit(lease)
    assert not ledger.commit(lease)
    assert ledger.claim(work) is None
    complete = snapshot(ledger, org, job)
    assert complete["state"] == "completed"
    result_event = next(
        work
        for work in ledger.outbox(org)
        if ledger.envelope(work)["event_type"] == "job.item_terminal"
    )
    assert ledger.envelope(result_event)["aggregate_version"] == complete["row_version"]
    with ledger.database.tenant(ledger.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.usage_events "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            == 1
        )
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.job_outbox WHERE organization_id=:org "
                    "AND job_id=:job AND event_type='job.item_terminal'"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            == 1
        )


def test_expired_lease_reconciliation_fences_old_worker(scenario: Scenario) -> None:
    ledger = approved(scenario)
    org = scenario.organizations[0]
    job = ledger.create_probe(org, 1)
    first = ledger.claim(ledger.outbox(org)[0], lease_seconds=1)
    assert first is not None
    time.sleep(1.1)
    assert not ledger.commit(first)
    assert ledger.reconcile(org, job) == 1
    second = next(lease for work in ledger.outbox(org) if (lease := ledger.claim(work)))
    assert not ledger.commit(first)
    assert ledger.commit(second)


@pytest.mark.parametrize("action", ["pause", "cancel"])
def test_generation_barrier_refuses_stale_commit(scenario: Scenario, action: str) -> None:
    ledger = approved(scenario)
    org = scenario.organizations[0]
    job = ledger.create_probe(org, 1)
    lease = ledger.claim(ledger.outbox(org)[0])
    assert lease is not None
    revision = int(str(snapshot(ledger, org, job)["row_version"]))
    ledger.control(org, job, action, revision)
    assert not ledger.commit(lease)
    state = snapshot(ledger, org, job)
    assert state["state"] == ("paused" if action == "pause" else "cancelled")
    if action == "pause":
        ledger.control(org, job, "resume", int(str(state["row_version"])))
        current = next(v for work in ledger.outbox(org) if (v := ledger.claim(work)))
        assert ledger.commit(current)


def test_message_ids_do_not_supply_authority(scenario: Scenario) -> None:
    ledger = approved(scenario)
    org = scenario.organizations[0]
    job = ledger.create_probe(org, 1)
    work = ledger.outbox(org)[0]
    assert ledger.claim(Work(org, job, work.item, uuid4())) is None
    with pytest.raises(AuthorizationDenied):
        ledger.claim(Work(scenario.organizations[1], job, work.item, work.event))
    with scenario.client() as client:
        scenario.login(client, "operator")
        other = Ledger(scenario.foundation.database, str(client.cookies[COOKIE]), SETTINGS)
        with pytest.raises(AuthorizationDenied):
            other.claim(work)


def test_production_diagnostic_worker_refused(scenario: Scenario) -> None:
    with pytest.raises(ValueError):
        Ledger(scenario.foundation.database, "unused", Settings()).create_probe(
            scenario.organizations[0], 1
        )


def test_core_api_draft_idempotency_preserves_original_input(scenario: Scenario) -> None:
    body = {
        "schema_version": "1.0",
        "input": {
            "type": "keyword",
            "source_id": "synthetic-publisher",
            "original_query": "original research",
        },
        "purpose": "academic_contact_research",
        "options": {"max_articles": 10, "max_search_pages": 2, "author_target": "both"},
    }
    assert JobRequest.model_validate(body).input.type == "keyword"
    with scenario.client() as client:
        csrf = scenario.login(client, "operator")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf, "Idempotency-Key": "fixture-key"}
        path = f"/api/v1/organizations/{scenario.organizations[0]}/jobs"
        first = client.post(path, headers=headers, json=body)
        assert first.status_code == 201, first.text
        assert first.json()["state"] == "draft"
        assert client.post(path, headers=headers, json=body).json()["id"] == first.json()["id"]
        body["purpose"] = "changed"
        assert client.post(path, headers=headers, json=body).status_code == 409
        assert (
            client.post(
                path + "/" + first.json()["id"] + "/start",
                headers=headers,
                json={"expected_revision": 1},
            ).status_code
            == 409
        )


def test_fixture_quota_reservations_rollback_and_cancel_release(scenario: Scenario) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.exc import SQLAlchemyError

    ledger = approved(scenario)
    org = scenario.organizations[0]
    admin = create_engine(scenario.admin_url)
    try:
        with admin.begin() as c:
            c.execute(
                text(
                    "INSERT INTO emailmonitor.fixture_quota(organization_id,maximum) VALUES(:org,1)"
                ),
                {"org": org},
            )
        with pytest.raises(SQLAlchemyError, match="QUOTA_EXHAUSTED"):
            ledger.create_probe(org, 1, 2)
        with ledger.database.tenant(ledger.token, org, Capability.READ_ORGANIZATION) as (c, _):
            assert (
                c.execute(
                    text("SELECT count(*) FROM emailmonitor.jobs WHERE organization_id=:org"),
                    {"org": org},
                ).scalar_one()
                == 0
            )
            assert (
                c.execute(
                    text(
                        "SELECT reserved FROM emailmonitor.fixture_quota WHERE organization_id=:org"
                    ),
                    {"org": org},
                ).scalar_one()
                == 0
            )
        job = ledger.create_probe(org, 1)
        ledger.control(org, job, "cancel", 1)
        with ledger.database.tenant(ledger.token, org, Capability.READ_ORGANIZATION) as (c, _):
            assert (
                c.execute(
                    text(
                        "SELECT reserved+used FROM emailmonitor.fixture_quota "
                        "WHERE organization_id=:org"
                    ),
                    {"org": org},
                ).scalar_one()
                == 0
            )
        ledger.create_probe(org, 1)
    finally:
        admin.dispose()


def test_repeated_expiry_is_bounded_and_releases_reservation(scenario: Scenario) -> None:
    ledger = approved(scenario)
    org = scenario.organizations[0]
    job = ledger.create_probe(org, 1)
    for _ in range(5):
        lease = next(v for work in ledger.outbox(org) if (v := ledger.claim(work, lease_seconds=1)))
        time.sleep(1.05)
        assert not ledger.commit(lease)
        ledger.reconcile(org, job)
    assert snapshot(ledger, org, job)["state"] == "failed"
    assert ledger.reconcile(org, job) == 0
    with ledger.database.tenant(ledger.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text(
                    "SELECT reserved+used FROM emailmonitor.fixture_quota "
                    "WHERE organization_id=:org"
                ),
                {"org": org},
            ).scalar_one()
            == 0
        )


def test_policy_revocation_blocks_already_leased_commit(scenario: Scenario) -> None:
    ledger = approved(scenario)
    org = scenario.organizations[0]
    ledger.create_probe(org, 1)
    lease = ledger.claim(ledger.outbox(org)[0])
    assert lease is not None
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        assert (
            client.post(
                source_path(scenario) + "/policy-state",
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
            ).status_code
            == 200
        )
    with pytest.raises(AuthorizationDenied):
        ledger.commit(lease)
    with ledger.database.tenant(ledger.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text("SELECT count(*) FROM emailmonitor.usage_events WHERE organization_id=:org"),
                {"org": org},
            ).scalar_one()
            == 0
        )


def test_lifecycle_barrier_denies_leased_commit(scenario: Scenario) -> None:
    from sqlalchemy import create_engine

    ledger = approved(scenario)
    org = scenario.organizations[0]
    ledger.create_probe(org, 1)
    lease = ledger.claim(ledger.outbox(org)[0])
    assert lease is not None
    admin = create_engine(scenario.admin_url)
    try:
        with admin.begin() as c:
            c.execute(
                text("UPDATE emailmonitor.organizations SET status='offboarding' WHERE id=:org"),
                {"org": org},
            )
            assert (
                c.execute(
                    text(
                        "SELECT deletion_generation FROM emailmonitor.organizations WHERE id=:org"
                    ),
                    {"org": org},
                ).scalar_one()
                == lease.deletion_generation + 1
            )
        with pytest.raises(AuthorizationDenied):
            ledger.commit(lease)
    finally:
        admin.dispose()


def test_defensive_ledger_catalog_and_permissions(scenario: Scenario) -> None:
    ledger = approved(scenario)
    org = scenario.organizations[0]
    with ledger.database.tenant(ledger.token, org, Capability.READ_ORGANIZATION) as (c, _):
        for table in (
            "jobs",
            "job_items",
            "job_idempotency",
            "job_outbox",
            "fixture_quota",
            "usage_reservations",
            "usage_events",
        ):
            assert c.execute(
                text(
                    "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                    "WHERE oid=CAST(:table AS regclass)"
                ),
                {"table": "emailmonitor." + table},
            ).scalar_one()
        for table in ("fixture_quota", "usage_events", "usage_reservations"):
            assert not c.execute(
                text("SELECT has_table_privilege(current_user,:table,'UPDATE')"),
                {"table": "emailmonitor." + table},
            ).scalar_one()
        assert not c.execute(
            text(
                "SELECT has_function_privilege(current_user,"
                "'emailmonitor.establish_session(text,text,text,text)','EXECUTE')"
            )
        ).scalar_one()
        assert not c.execute(
            text(
                "SELECT pg_has_role(current_user,'emailmonitor_owner','SET') OR "
                "pg_has_role(current_user,'emailmonitor_authenticator','MEMBER')"
            )
        ).scalar_one()


def quota(ledger: Ledger, organization: UUID) -> tuple[int, int]:
    with ledger.database.tenant(ledger.token, organization, Capability.READ_ORGANIZATION) as (c, _):
        row = (
            c.execute(
                text(
                    "SELECT reserved,used FROM emailmonitor.fixture_quota "
                    "WHERE organization_id=:org"
                ),
                {"org": organization},
            )
            .mappings()
            .one()
        )
        return int(row["reserved"]), int(row["used"])


def expire_attempts(ledger: Ledger, work: Work, count: int) -> None:
    for _ in range(count):
        lease = ledger.claim(work, lease_seconds=1)
        assert lease is not None
        time.sleep(1.05)
        assert not ledger.commit(lease)
        ledger.reconcile(work.organization, work.job)


def test_exhausted_item_does_not_terminalize_other_live_lease(scenario: Scenario) -> None:
    ledger = approved(scenario)
    org = scenario.organizations[0]
    job = ledger.create_probe(org, 1, 2)
    first, second = ledger.outbox(org)
    expire_attempts(ledger, first, 4)
    last = ledger.claim(first, lease_seconds=1)
    live = ledger.claim(second, lease_seconds=30)
    assert last is not None and live is not None
    time.sleep(1.05)
    ledger.reconcile(org, job)
    assert snapshot(ledger, org, job)["state"] == "running"
    assert quota(ledger, org) == (1, 0)
    assert ledger.commit(live)
    assert snapshot(ledger, org, job)["state"] == "completed_partial"
    assert quota(ledger, org) == (0, 1)
    assert not ledger.commit(last)


def test_succeeded_and_exhausted_item_resolve_completed_partial(scenario: Scenario) -> None:
    ledger = approved(scenario)
    org = scenario.organizations[0]
    job = ledger.create_probe(org, 1, 2)
    first, second = ledger.outbox(org)
    lease = ledger.claim(first)
    assert lease is not None and ledger.commit(lease)
    assert quota(ledger, org) == (1, 1)
    expire_attempts(ledger, second, 5)
    assert snapshot(ledger, org, job)["state"] == "completed_partial"
    assert quota(ledger, org) == (0, 1)
    with ledger.database.tenant(ledger.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert c.execute(
            text(
                "SELECT result FROM emailmonitor.job_items "
                "WHERE organization_id=:org AND job_id=:job AND id=:item"
            ),
            {"org": org, "job": job, "item": first.item},
        ).scalar_one() == {"diagnostic": "persistence-only"}


def test_pause_on_fifth_attempt_settles_quota_and_resume_is_bounded(scenario: Scenario) -> None:
    ledger = approved(scenario)
    org = scenario.organizations[0]
    job = ledger.create_probe(org, 1)
    work = ledger.outbox(org)[0]
    expire_attempts(ledger, work, 4)
    fifth = ledger.claim(work)
    assert fifth is not None
    ledger.control(org, job, "pause", int(str(snapshot(ledger, org, job)["row_version"])))
    assert snapshot(ledger, org, job)["state"] == "paused"
    assert quota(ledger, org) == (0, 0)
    ledger.control(org, job, "resume", int(str(snapshot(ledger, org, job)["row_version"])))
    assert snapshot(ledger, org, job)["state"] == "failed"
    assert ledger.claim(work) is None
    assert not ledger.commit(fifth)
    assert ledger.reconcile(org, job) == 0
    assert quota(ledger, org) == (0, 0)

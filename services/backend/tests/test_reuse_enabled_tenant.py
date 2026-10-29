"""Synthetic PostgreSQL proof for the disabled-by-API enabling candidate."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from emailmonitor.associations.reuse_materialization import materialize_draft
from emailmonitor.lifecycle.models import DeletionRequest, SuppressionCreate
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.service import Progress
from emailmonitor.results.models import Filters
from emailmonitor.results.service import Results
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from test_association_tenant import URL, prepared, review_request
from test_association_tenant import client as fixture_client
from test_durable_jobs import SETTINGS
from test_html_extraction_tenant import ready as ready_observation
from test_job_contracts import request_body
from test_progress_tenant import drain
from test_results_tenant import ready as ready_export
from test_retained_reuse_lifecycle_tenant import target_request_for_sql_guard_test
from test_source_foundation import source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario


def test_actual_reuse_independent_review_replay_and_source_deletion(scenario: Scenario) -> None:
    print("REUSE_TEST_PHASE=prepare_source", flush=True)
    service, source, source_batch = prepared(scenario)
    org = scenario.organizations[0]
    rejected = service.review(
        org, source_batch, review_request(service, org, source_batch, action="reject")
    )
    assert rejected.associations[0].state == "rejected"
    print("REUSE_TEST_PHASE=prepare_target", flush=True)
    target = target_request_for_sql_guard_test(service, org)
    print("REUSE_TEST_PHASE=materialize", flush=True)
    assert materialize_draft(service, org, target, URL) == source_batch
    print("REUSE_TEST_PHASE=replay", flush=True)
    assert materialize_draft(service, org, target, URL) == source_batch
    print("REUSE_TEST_PHASE=derive", flush=True)
    target_batch = service.derive(org, target, URL, 1)
    assert service.detail(org, target_batch).associations[0].state == "needs_review"
    assert service.detail(org, source_batch).associations[0].state == "rejected"
    with service.database.tenant(service.token, org, Capability.READ_ORGANIZATION) as (c, _):
        count: int = c.execute(
            text(
                "SELECT count(*) FROM emailmonitor.audit_events WHERE organization_id=:org "
                "AND resource_id=:job AND action='extraction.retained_reused'"
            ),
            {"org": org, "job": target},
        ).scalar_one()
        assert count == 1
    lifecycle = Lifecycle(service.database, service.token, SETTINGS)
    print("REUSE_TEST_PHASE=stage_delete", flush=True)
    receipt = lifecycle.stage(org, DeletionRequest(job_id=source, reason="privacy_request"))
    with pytest.raises(AuthorizationDenied):
        service.detail(org, target_batch)
    print("REUSE_TEST_PHASE=purge", flush=True)
    assert lifecycle.purge(org, receipt.id).stage == "purged"
    # Verify physical removal as the synthetic test administrator; a runtime
    # zero-row read alone could merely be hidden by lifecycle RLS.
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.connect() as c:
            for table in ("article_observations", "association_batches"):
                assert (
                    c.execute(
                        text(
                            f"SELECT count(*) FROM emailmonitor.{table} "
                            "WHERE organization_id=:org AND job_id=:job"
                        ),
                        {"org": org, "job": target},
                    ).scalar_one()
                    == 0
                )
    finally:
        admin.dispose()


def test_actual_bounded_source_purge_resumes_after_ten_targets(scenario: Scenario) -> None:
    service, source, source_batch = prepared(scenario)
    org = scenario.organizations[0]
    targets = []
    for _ in range(11):
        target = target_request_for_sql_guard_test(service, org)
        assert materialize_draft(service, org, target, URL) == source_batch
        targets.append(target)
    lifecycle = Lifecycle(service.database, service.token, SETTINGS)
    receipt = lifecycle.stage(org, DeletionRequest(job_id=source, reason="privacy_request"))
    assert lifecycle.purge(org, receipt.id).stage == "fenced"
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.connect() as c:
            remaining: int = c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.article_observations "
                    "WHERE organization_id=:org AND reused_from_job=:job"
                ),
                {"org": org, "job": source},
            ).scalar_one()
            assert remaining == 1
        assert lifecycle.purge(org, receipt.id).stage == "purged"
        assert lifecycle.purge(org, receipt.id).stage == "purged"
        with admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND reused_from_job=:job"
                    ),
                    {"org": org, "job": source},
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()


def test_actual_freshness_refusal_never_creates_a_copy(scenario: Scenario) -> None:
    service, source, _ = prepared(scenario)
    org = scenario.organizations[0]
    target = target_request_for_sql_guard_test(service, org, datetime.now(UTC).isoformat())
    with pytest.raises(HTTPException) as failure:
        materialize_draft(service, org, target, URL)
    assert failure.value.status_code == 409
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": target},
                ).scalar_one()
                == 0
            )
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": source},
                ).scalar_one()
                == 1
            )
    finally:
        admin.dispose()


def test_actual_reuse_progress_executes_without_fresh_fixture_read(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, source_batch = prepared(scenario)
    org = scenario.organizations[0]
    target = target_request_for_sql_guard_test(service, org)
    assert materialize_draft(service, org, target, URL) == source_batch
    progress = Progress(service.database, service.token, SETTINGS)
    progress.start(org, target, progress.snapshot(org, target).revision)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Explicit reuse must not acquire a fresh fixture")

    monkeypatch.setattr(progress.extraction, "fixture", forbidden)
    drain(progress, org, target)
    snapshot = progress.snapshot(org, target)
    assert snapshot.state == "completed"
    assert snapshot.counts.by_outcome == {"needs_review": 1}


def test_actual_api_creates_and_plans_the_explicit_reuse(scenario: Scenario) -> None:
    service, source, source_batch = prepared(scenario)
    org = scenario.organizations[0]
    with fixture_client(scenario) as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())}
        body = {
            **request_body(),
            "input": {"type": "url", "url": URL},
            "reuse": {"mode": "verified_retained", "fresh_since": "2000-01-01T00:00:00Z"},
        }
        root = f"/api/v1/organizations/{org}/jobs"
        created = client.post(root, headers=headers, json=body)
        assert created.status_code == 201
        target = created.json()["id"]
        assert client.post(root, headers=headers, json=body).json()["id"] == target
        planned = client.post(
            root + f"/{target}/plan", headers=headers, json={"expected_revision": 1}
        )
        assert planned.status_code == 200
        assert planned.json()["plan"]["reason"] == "retained_reuse_authored"
    with service.database.tenant(service.token, org, Capability.READ_ORGANIZATION) as (c, _):
        row = c.execute(
            text(
                "SELECT reused_from_job,reused_source_batch FROM emailmonitor.article_observations "
                "WHERE organization_id=:org AND job_id=:job"
            ),
            {"org": org, "job": target},
        ).one()
        assert row.reused_from_job == source and row.reused_source_batch == source_batch


def test_actual_export_invalidates_when_original_is_deleted(scenario: Scenario) -> None:
    service, source, source_batch = prepared(scenario)
    org = scenario.organizations[0]
    target = target_request_for_sql_guard_test(service, org)
    assert materialize_draft(service, org, target, URL) == source_batch
    progress = Progress(service.database, service.token, SETTINGS)
    progress.start(org, target, progress.snapshot(org, target).revision)
    drain(progress, org, target)
    results = Results(service.database, service.token, SETTINGS)
    review_page = results.contacts(org, Filters(job_id=target, states=("needs_review",)))
    assert review_page.items and review_page.items[0].observation_origin == "reused"
    batch = review_page.items[0].batch_id
    service.review(org, batch, review_request(service, org, batch))
    export = ready_export(results, org, target)
    assert results.download(org, export).body
    lifecycle = Lifecycle(service.database, service.token, SETTINGS)
    receipt = lifecycle.stage(org, DeletionRequest(job_id=source, reason="privacy_request"))
    with pytest.raises(AuthorizationDenied):
        results.download(org, export)
    assert lifecycle.purge(org, receipt.id).stage == "purged"
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.export_artifacts "
                        "WHERE organization_id=:org AND export_id=:export"
                    ),
                    {"org": org, "export": export},
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()


def test_actual_reused_no_contact_discloses_original_time(scenario: Scenario) -> None:
    extraction, source = ready_observation(scenario)
    org = scenario.organizations[0]
    url = "https://synthetic.publisher.example/no-contact.html"
    extraction.fixture(org, source, url, 3)
    from emailmonitor.associations.service import Associations

    service = Associations(extraction.database, extraction.token, SETTINGS)
    source_batch = service.derive(org, source, url, 1)
    target = target_request_for_sql_guard_test(service, org, url=url)
    assert materialize_draft(service, org, target, url) == source_batch
    progress = Progress(service.database, service.token, SETTINGS)
    progress.start(org, target, progress.snapshot(org, target).revision)
    drain(progress, org, target)
    outcome = Results(service.database, service.token, SETTINGS).outcomes(org, target).items[0]
    assert outcome.state == "no_contact"
    assert outcome.observation_origin == "reused" and outcome.observed_at is not None


def test_actual_suppression_fences_reused_copy_and_removes_it(scenario: Scenario) -> None:
    service, _, source_batch = prepared(scenario)
    org = scenario.organizations[0]
    target = target_request_for_sql_guard_test(service, org)
    assert materialize_draft(service, org, target, URL) == source_batch
    target_batch = service.derive(org, target, URL, 1)
    candidate = service.detail(org, target_batch).candidates[0]
    lifecycle = Lifecycle(service.database, service.token, SETTINGS)
    lifecycle.suppress(
        org,
        SuppressionCreate.model_validate(
            {"kind": "contact", "value": candidate.raw_variants[0], "reason": "privacy_request"}
        ),
    )
    with pytest.raises(AuthorizationDenied):
        service.detail(org, target_batch)
    lifecycle.tick(org)
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": target},
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()


def test_actual_source_expiry_fences_and_purges_copied_evidence(scenario: Scenario) -> None:
    service, source, source_batch = prepared(scenario)
    org = scenario.organizations[0]
    target = target_request_for_sql_guard_test(service, org)
    assert materialize_draft(service, org, target, URL) == source_batch
    batch = service.derive(org, target, URL, 1)
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.begin() as c:
            c.execute(
                text(
                    "UPDATE emailmonitor.lifecycle_job_deadlines "
                    "SET contact_deadline=clock_timestamp()-interval '1 second' "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": source},
            )
        with pytest.raises(AuthorizationDenied):
            service.detail(org, batch)
        lifecycle = Lifecycle(service.database, service.token, SETTINGS)
        assert lifecycle.tick(org) >= 1
        with admin.connect() as c:
            for table in ("article_observations", "association_batches"):
                assert (
                    c.execute(
                        text(
                            f"SELECT count(*) FROM emailmonitor.{table} "
                            "WHERE organization_id=:org AND job_id=:job"
                        ),
                        {"org": org, "job": target},
                    ).scalar_one()
                    == 0
                )
    finally:
        admin.dispose()


def test_actual_revoked_source_refuses_target_without_privacy_purge(scenario: Scenario) -> None:
    service, source, source_batch = prepared(scenario)
    org = scenario.organizations[0]
    target = target_request_for_sql_guard_test(service, org)
    assert materialize_draft(service, org, target, URL) == source_batch
    batch = service.derive(org, target, URL, 1)
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        response = client.post(
            source_path(scenario) + "/policy-state",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
        )
        assert response.status_code == 200
    with pytest.raises(AuthorizationDenied):
        service.detail(org, batch)
    lifecycle = Lifecycle(service.database, service.token, SETTINGS)
    lifecycle.tick(org)
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": target},
                ).scalar_one()
                == 1
            )
    finally:
        admin.dispose()

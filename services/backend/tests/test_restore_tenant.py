"""Actual same-version dump/restore, private replay, runtime RLS and broker rebuild."""

import hashlib
import os
import time
from dataclasses import replace
from pathlib import Path

import pytest
from emailmonitor.jobs.broker import create_worker
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.lifecycle.models import DeletionRequest, SuppressionCreate
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied, Database
from emailmonitor.organizations.roles import Capability
from emailmonitor.results.models import Filters
from emailmonitor.results.service import Results
from restore_exercise import (
    ADMIN,
    RUNTIME,
    RestoreExercise,
    RestoreRefused,
    capture,
    supported_delta,
)
from sqlalchemy import create_engine, text
from test_durable_jobs import SETTINGS, snapshot
from test_real_broker_jobs import config, deliveries, wait_for, worker
from test_results_tenant import prepared, ready
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def test_actual_restore_replays_current_privacy_before_runtime_and_rebuilds_broker(
    scenario: Scenario, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if os.environ.get("EM_REQUIRE_SYNTHETIC_RESTORE") != "true":
        pytest.skip("Required disposable PostgreSQL dump/restore exercise is unavailable")
    started = time.monotonic()
    results_a, job_a = prepared(scenario)
    org_a, org_b = scenario.organizations
    other = replace(
        scenario,
        organizations=(org_b, org_a),
        identities={**scenario.identities, "owner": scenario.identities["owner_b"]},
    )
    results_b, job_b = prepared(other, "article-b.html")
    export_a, export_b = ready(results_a, org_a, job_a), ready(results_b, org_b, job_b)
    expected_hash = hashlib.sha256(results_b.download(org_b, export_b).body).hexdigest()
    life_a = Lifecycle(results_a.database, results_a.token, SETTINGS)
    life_b = Lifecycle(results_b.database, results_b.token, SETTINGS)
    life_a.retention(org_a)
    life_b.retention(org_b)
    ledger_b = Ledger(results_b.database, results_b.token, SETTINGS)
    probe = ledger_b.create_probe(org_b, 1)
    probe_state = snapshot(ledger_b, org_b, probe)
    admin = create_engine(ADMIN, hide_parameters=True)
    target = RestoreExercise(tmp_path)
    restored: Database | None = None
    try:
        before = capture(admin, (org_a, org_b))
        archive_digest = target.backup()
        marker = life_a.stage(org_a, DeletionRequest(job_id=job_a, reason="privacy_request"))
        life_a.purge(org_a, marker.id)
        life_a.suppress(
            org_a, SuppressionCreate(kind="domain", value="example.org", reason="privacy_request")
        )
        # Current guarded same-version revocation; no new login/session or policy
        # version is fabricated after the backup.
        with admin.begin() as c:
            c.execute(
                text(
                    "UPDATE emailmonitor.source_policies SET state='revoked' "
                    "WHERE organization_id=:org AND source_id='synthetic-publisher' "
                    "AND version=1"
                ),
                {"org": org_a},
            )
        current = capture(admin, (org_a, org_b))
        target.restore_closed()
        with target.target.connect() as c:
            assert c.execute(
                text(
                    "SELECT NOT has_database_privilege('em_ci_runtime',"
                    "current_database(),'CONNECT') AND NOT has_database_privilege("
                    "'em_ci_authenticator',current_database(),'CONNECT')"
                )
            ).scalar_one()
        with pytest.raises(RuntimeError):
            target.url(RUNTIME)
        target.replay(before, current, {org_a: results_a.token, org_b: results_b.token})
        target.replay(before, current, {org_a: results_a.token, org_b: results_b.token})
        target.open_after_validation()
        restored = Database(target.url(RUNTIME))
        a, b = (
            Results(restored, results_a.token, SETTINGS),
            Results(restored, results_b.token, SETTINGS),
        )
        with pytest.raises(AuthorizationDenied):
            a.contacts(org_a, Filters(job_id=job_a))
        with pytest.raises(AuthorizationDenied):
            a.download(org_a, export_a)
        with pytest.raises(AuthorizationDenied):
            a.contacts(org_b, Filters())
        assert hashlib.sha256(b.download(org_b, export_b).body).hexdigest() == expected_hash
        assert b.contacts(org_b, Filters(job_id=job_b)).items
        protected = (
            "article_observations",
            "association_batches",
            "author_email_associations",
            "execution_runs",
            "exports",
        )
        with target.target.connect() as c:
            for table in protected:
                assert c.execute(
                    text(
                        "SELECT relrowsecurity AND relforcerowsecurity "
                        "AND pg_get_userbyid(relowner)='emailmonitor_owner' FROM pg_class "
                        "WHERE oid=CAST(:table AS regclass)"
                    ),
                    {"table": "emailmonitor." + table},
                ).scalar_one()
        with restored.transaction() as c:
            for table in protected:
                assert (
                    c.execute(text(f"SELECT count(*) FROM emailmonitor.{table}")).scalar_one() == 0
                )
        with restored.tenant(results_b.token, org_b, Capability.READ_ORGANIZATION) as (c, _):
            assert (
                c.execute(
                    text("SELECT count(*) FROM emailmonitor.article_observations")
                ).scalar_one()
                > 0
            )
            for table in protected:
                assert (
                    c.execute(
                        text(
                            f"SELECT count(*) FROM emailmonitor.{table} WHERE organization_id=:org"
                        ),
                        {"org": org_a},
                    ).scalar_one()
                    == 0
                )
            c.execute(
                text("SELECT set_config('emailmonitor.organization_id',:org,true)"),
                {"org": str(org_a)},
            )
            for table in protected:
                assert (
                    c.execute(text(f"SELECT count(*) FROM emailmonitor.{table}")).scalar_one() == 0
                )
        with restored.tenant(results_a.token, org_a, Capability.READ_ORGANIZATION) as (c, _):
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org_a, "job": job_a},
                ).scalar_one()
                == 0
            )
            assert not c.execute(
                text("SELECT emailmonitor.privacy_payload_allowed(:org,CAST(:payload AS jsonb))"),
                {"org": org_a, "payload": '{"raw_address":"mira@example.org"}'},
            ).scalar_one()
        with target.target.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org_a, "job": job_a},
                ).scalar_one()
                == 0
            )
            assert (
                c.execute(
                    text(
                        "SELECT state FROM emailmonitor.source_policies "
                        "WHERE organization_id=:org AND version=1"
                    ),
                    {"org": org_a},
                ).scalar_one()
                == "revoked"
            )
        replayed_ledger = Ledger(restored, results_b.token, SETTINGS)
        assert snapshot(replayed_ledger, org_b, probe)["generation"] == probe_state["generation"]
        cfg = config(other, replayed_ledger, database_url=target.url(RUNTIME))
        app, _ = create_worker(cfg)
        try:
            # No queue snapshot is restored: reconstruct messages from durable
            # outbox identifiers and recover one ordinary fixture effect.
            from emailmonitor.jobs.broker import publish

            pending_work = replayed_ledger.outbox(org_b)
            assert len(pending_work) == 1
            assert publish(app, replayed_ledger, org_b) == 1
            app.send_task(
                "emailmonitor.fixture.persist",
                args=[replayed_ledger.envelope(pending_work[0])],
                queue=cfg.queue,
                routing_key=cfg.queue,
                delivery_mode=2,
                mandatory=True,
                retry=False,
            )
            with worker(cfg, tmp_path):
                wait_for(lambda: snapshot(replayed_ledger, org_b, probe)["state"] == "completed")
                wait_for(lambda: deliveries(replayed_ledger, org_b, pending_work[0].event) >= 2)
            assert replayed_ledger.reconcile(org_b, probe) == 0
        finally:
            app.close()
        with target.target.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.usage_events "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org_b, "job": probe},
                ).scalar_one()
                == 1
            )
        # A post-backup review is unsupported business history and must quarantine
        # a stale archive even when job/accounting anchors have not changed.
        from emailmonitor.associations.models import Review
        from emailmonitor.associations.service import Associations

        contact = results_b.contacts(org_b, Filters(job_id=job_b)).items[0]
        Associations(results_b.database, results_b.token, SETTINGS).review(
            org_b,
            contact.batch_id,
            Review(
                association_id=contact.association_id,
                expected_revision=contact.revision,
                action="reject",
                author_id=None,
                evidence_ids=contact.evidence_ids,
                reason="Synthetic restore drift refusal",
            ),
        )
        with pytest.raises(RestoreRefused, match="restore_unreplayed_business_frontier"):
            supported_delta(before, capture(admin, (org_a, org_b)))
        with capsys.disabled():
            print(
                {
                    "synthetic_restore": True,
                    "same_version_tools": True,
                    "archive_sha256": archive_digest,
                    "unaffected_artifact_hash": True,
                    "privacy_before_runtime": True,
                    "two_tenant_rls": True,
                    "broker_rebuilt_from_ledger": True,
                    "exercise_seconds": round(time.monotonic() - started, 3),
                    "production_rpo_rto_measured": False,
                }
            )
    finally:
        if restored is not None:
            restored.engine.dispose()
        target.close()
        admin.dispose()

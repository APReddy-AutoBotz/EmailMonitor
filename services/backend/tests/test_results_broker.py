"""Original broker redelivery, explicit duplicates and missing-work reconstruction are distinct."""

import time
from pathlib import Path
from uuid import UUID, uuid4

from emailmonitor.jobs.broker import create_worker
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.organizations.roles import Capability
from emailmonitor.results.broker import ExportEvent, publish
from emailmonitor.results.service import Results
from sqlalchemy import text
from test_durable_jobs import SETTINGS
from test_real_broker_jobs import config, wait_for, worker
from test_results_tenant import options, prepared
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def counters(results: Results, org: UUID, export: UUID) -> tuple[int, int]:
    with results.database.tenant(results.token, org, Capability.EXPORT_RESULTS) as (c, _):
        deliveries: int = c.execute(
            text(
                "SELECT deliveries FROM emailmonitor.export_outbox "
                "WHERE organization_id=:org AND export_id=:id"
            ),
            {"org": org, "id": export},
        ).scalar_one()
        effects: int = c.execute(
            text(
                "SELECT count(*) FROM emailmonitor.export_effects "
                "WHERE organization_id=:org AND export_id=:id"
            ),
            {"org": org, "id": export},
        ).scalar_one()
        return int(deliveries), int(effects)


def test_real_export_post_commit_original_unacked_redelivery(
    scenario: Scenario, tmp_path: Path
) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = results.create(org, options(job), str(uuid4())).id
    cfg = config(
        scenario, Ledger(results.database, results.token, SETTINGS), exit_after_commit=True
    )
    app, _ = create_worker(cfg)
    try:
        with worker(cfg, tmp_path) as process:
            assert publish(app, results, org) == 1
            wait_for(lambda: process.poll() is not None)
            assert process.returncode == 73
        before = results.download(org, export)
        with worker(cfg.model_copy(update={"exit_after_commit": False}), tmp_path):
            # No explicit duplicate publication may satisfy this original broker receipt.
            wait_for(lambda: counters(results, org, export)[0] >= 2)
        assert counters(results, org, export)[1] == 1 and results.download(org, export) == before
    finally:
        app.close()


def test_real_export_explicit_duplicate_one_effect(scenario: Scenario, tmp_path: Path) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = results.create(org, options(job), str(uuid4())).id
    row = results.pending(org)[0]
    event = ExportEvent(
        organization_id=str(org),
        export_id=str(export),
        event_id=str(row["event_id"]),
        generation=int(str(row["generation"])),
    )
    cfg = config(scenario, Ledger(results.database, results.token, SETTINGS))
    app, _ = create_worker(cfg)
    try:
        with worker(cfg, tmp_path):
            assert publish(app, results, org) == 1
            wait_for(lambda: results.state(org, export).state == "ready")
            before = results.download(org, export)
            app.send_task("emailmonitor.fixture.export", args=[event.model_dump()], queue=cfg.queue)
            wait_for(lambda: counters(results, org, export)[0] >= 2)
        assert counters(results, org, export)[1] == 1 and results.download(org, export) == before
    finally:
        app.close()


def test_real_export_crash_after_claim_recovers_lease(scenario: Scenario, tmp_path: Path) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = results.create(org, options(job), str(uuid4())).id
    cfg = config(
        scenario,
        Ledger(results.database, results.token, SETTINGS),
        exit_after_observation=True,
        lease_seconds=1,
    )
    app, _ = create_worker(cfg)
    try:
        with worker(cfg, tmp_path) as process:
            assert publish(app, results, org) == 1
            wait_for(lambda: process.poll() is not None)
            assert process.returncode == 74
        assert (
            results.state(org, export).state == "running" and counters(results, org, export)[1] == 0
        )
        time.sleep(1.1)
        results.reconcile(org, export)
        with worker(cfg.model_copy(update={"exit_after_observation": False}), tmp_path):
            publish(app, results, org)
            wait_for(lambda: results.state(org, export).state == "ready")
        assert counters(results, org, export)[1] == 1
    finally:
        app.close()


def test_real_export_confirmed_queue_loss_rebuilds(scenario: Scenario, tmp_path: Path) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = results.create(org, options(job), str(uuid4())).id
    original = results.pending(org)[0]
    cfg = config(scenario, Ledger(results.database, results.token, SETTINGS))
    app, _ = create_worker(cfg)
    try:
        assert publish(app, results, org) == 1 and results.pending(org) == []
        with app.connection_for_write() as connection:
            channel = connection.channel()
            try:
                assert app.amqp.queues[cfg.queue](channel).purge() == 1
            finally:
                channel.close()
        results.reconcile(org, export)
        assert results.pending(org)[0]["event_id"] == original["event_id"]
        with worker(cfg, tmp_path):
            assert publish(app, results, org) == 1
            wait_for(lambda: results.state(org, export).state == "ready")
        assert counters(results, org, export)[1] == 1
    finally:
        app.close()

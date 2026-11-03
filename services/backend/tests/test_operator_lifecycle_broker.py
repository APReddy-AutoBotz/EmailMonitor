"""Actual original-message redelivery of an operator continuation."""

from pathlib import Path
from uuid import UUID

from emailmonitor.administration.service import Administration
from emailmonitor.jobs.broker import create_worker
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.progress.broker import publish
from test_operator_lifecycle_tenant import failed_job
from test_progress_broker import deliveries
from test_real_broker_jobs import config, wait_for, worker
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def test_continuation_worker_restart_preserves_original_and_single_effect(
    scenario: Scenario, tmp_path: Path
) -> None:
    progress, original_job = failed_job(scenario)
    org = scenario.organizations[0]
    original = progress.snapshot(org, original_job)
    retained = progress.extraction.read(org, original_job)
    usage = Administration(progress.database, progress.token, progress.settings)
    before_units = usage.usage(org).settled_resolution_units
    child = progress.retry(org, original_job, original.revision)
    cfg = config(
        scenario,
        Ledger(progress.database, progress.token, progress.settings),
        exit_after_commit=True,
    )
    app, _ = create_worker(cfg)
    message = next(r for r in progress.pending(org) if r["job_id"] == child)
    event = UUID(str(message["event_id"]))
    try:
        with worker(cfg, tmp_path) as first:
            assert publish(app, progress, org) == 1
            wait_for(lambda: first.poll() is not None)
            assert first.returncode == 73
        completed = progress.snapshot(org, child)
        assert completed.state == "completed"
        child_rows = progress.extraction.read(org, child)
        assert len(child_rows) == 1
        with worker(cfg.model_copy(update={"exit_after_commit": False}), tmp_path):
            # Original unacknowledged message, never a synthetic second publish.
            wait_for(lambda: deliveries(progress, org, child, event) >= 2)
        assert progress.snapshot(org, child) == completed
        assert progress.extraction.read(org, child) == child_rows
        assert progress.snapshot(org, original_job) == original
        assert progress.extraction.read(org, original_job) == retained
        assert progress.retry(org, original_job, original.revision) == child
        assert usage.usage(org).settled_resolution_units == before_units + 1
        assert usage.usage(org).reserved_resolution_units == 0
    finally:
        app.close()

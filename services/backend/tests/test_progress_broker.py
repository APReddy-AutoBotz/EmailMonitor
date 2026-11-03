"""Actual broker original-message recovery and explicit duplicate delivery are separate."""

from pathlib import Path
from uuid import UUID

from emailmonitor.jobs.broker import create_worker
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.queues import phase_queue
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.broker import ExecutionEvent, publish
from sqlalchemy import text
from test_progress_tenant import planned
from test_real_broker_jobs import config, wait_for, worker
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def deliveries(progress: object, org: UUID, job: UUID, event: UUID) -> int:
    from emailmonitor.progress.service import Progress

    assert isinstance(progress, Progress)
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        return int(
            c.execute(
                text(
                    "SELECT deliveries FROM emailmonitor.execution_outbox "
                    "WHERE organization_id=:org AND job_id=:job AND event_id=:event"
                ),
                {"org": org, "job": job, "event": event},
            ).scalar_one()
        )


def test_real_execution_post_effect_pre_ack_original_redelivery(
    scenario: Scenario, tmp_path: Path
) -> None:
    progress, job = planned(scenario, "https://synthetic.publisher.example/no-contact.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    ledger = Ledger(progress.database, progress.token, progress.settings)
    cfg = config(scenario, ledger, exit_after_commit=True)
    app, _ = create_worker(cfg)
    original = progress.pending(org)[0]
    event_id = UUID(str(original["event_id"]))
    try:
        with worker(cfg, tmp_path) as running:
            assert publish(app, progress, org) == 1
            wait_for(lambda: running.poll() is not None)
            assert running.returncode == 73
        before = progress.snapshot(org, job)
        assert before.state == "completed" and before.counts.by_outcome == {"no_contact": 1}
        with worker(cfg.model_copy(update={"exit_after_commit": False}), tmp_path):
            # This receipt must be the broker's original unacked message, with no manual publish.
            wait_for(lambda: deliveries(progress, org, job, event_id) >= 2)
            assert progress.snapshot(org, job) == before
        with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
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
        app.close()


def test_real_accepted_contact_post_effect_pre_ack_original_redelivery(
    scenario: Scenario, tmp_path: Path
) -> None:
    """Separate static article recovery; not combined browser crash recovery."""
    from emailmonitor.administration.service import Administration

    progress, job = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    cfg = config(
        scenario,
        Ledger(progress.database, progress.token, progress.settings),
        exit_after_commit=True,
    )
    app, _ = create_worker(cfg)
    original = progress.pending(org)[0]
    event_id = UUID(str(original["event_id"]))
    usage = Administration(progress.database, progress.token, progress.settings)
    try:
        with worker(cfg, tmp_path) as running:
            assert publish(app, progress, org) == 1
            wait_for(lambda: running.poll() is not None)
            assert running.returncode == 73

        before = progress.snapshot(org, job)
        assert before.state == "completed" and before.counts.by_outcome == {"succeeded": 1}
        assert before.accepted_associations == 1
        batches = progress.associations.batches(org, job)
        assert len(batches) == 1
        batch_id = UUID(str(batches[0]["id"]))
        bundle = progress.associations.detail(org, batch_id)
        accepted_ids = {item.id for item in bundle.associations if item.state == "accepted"}
        assert len(accepted_ids) == 1
        retained = progress.extraction.read(org, job)
        assert len(retained) == 1 and retained[0]["revision"] == 1
        assert usage.usage(org).settled_resolution_units == 1
        assert usage.usage(org).reserved_resolution_units == 0

        with worker(cfg.model_copy(update={"exit_after_commit": False}), tmp_path):
            # No second publish: require RabbitMQ to redeliver the original unacked event.
            wait_for(lambda: deliveries(progress, org, job, event_id) >= 2)

        assert progress.snapshot(org, job) == before
        assert progress.associations.batches(org, job) == batches
        replayed = progress.associations.detail(org, batch_id)
        assert {
            item.id for item in replayed.associations if item.state == "accepted"
        } == accepted_ids
        assert replayed == bundle
        # Full retained rows include observation content, digests, revisions and timestamps.
        assert progress.extraction.read(org, job) == retained
        assert usage.usage(org).settled_resolution_units == 1
        assert usage.usage(org).reserved_resolution_units == 0
        with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
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
        app.close()


def test_real_execution_explicit_duplicate_has_one_effect(
    scenario: Scenario, tmp_path: Path
) -> None:
    progress, job = planned(scenario, "https://synthetic.publisher.example/no-contact.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    cfg = config(scenario, Ledger(progress.database, progress.token, progress.settings))
    app, _ = create_worker(cfg)
    row = progress.pending(org)[0]
    event = ExecutionEvent(
        organization_id=str(org),
        job_id=str(job),
        item_id=str(row["item_id"]),
        event_id=str(row["event_id"]),
        generation=1,
    )
    try:
        with worker(cfg, tmp_path):
            assert publish(app, progress, org) == 1
            wait_for(lambda: progress.snapshot(org, job).state == "completed")
            before = progress.snapshot(org, job)
            app.send_task(
                "emailmonitor.fixture.execute",
                args=[event.model_dump()],
                queue=cfg.queue,
                routing_key=cfg.queue,
                delivery_mode=2,
                mandatory=True,
                retry=False,
            )
            wait_for(lambda: deliveries(progress, org, job, UUID(event.event_id)) >= 2)
            assert progress.snapshot(org, job) == before
    finally:
        app.close()


def test_real_execution_crash_after_observation_resumes_retained_checkpoint(
    scenario: Scenario, tmp_path: Path
) -> None:
    import time

    from emailmonitor.administration.service import Administration

    progress, job = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    cfg = config(
        scenario,
        Ledger(progress.database, progress.token, progress.settings),
        exit_after_observation=True,
        lease_seconds=2,
    )
    app, _ = create_worker(cfg)
    row = progress.pending(org)[0]
    event_id = UUID(str(row["event_id"]))
    try:
        with worker(cfg, tmp_path) as running:
            assert publish(app, progress, org) == 1
            wait_for(lambda: running.poll() is not None)
            assert running.returncode == 74
        retained = progress.extraction.read(org, job)[0]
        assert retained["revision"] == 1
        usage = Administration(progress.database, progress.token, progress.settings)
        assert usage.usage(org).reserved_resolution_units == 1
        assert usage.usage(org).settled_resolution_units == 0
        assert progress.snapshot(org, job).state == "running"
        time.sleep(2.1)
        progress.reconcile(org, job)
        with worker(cfg.model_copy(update={"exit_after_observation": False}), tmp_path):
            # Recover original delivery before any republish; same retained source is reused.
            wait_for(lambda: deliveries(progress, org, job, event_id) >= 2)
            wait_for(lambda: progress.snapshot(org, job).state == "completed")
        assert progress.extraction.read(org, job)[0]["observed_at"] == retained["observed_at"]
        assert usage.usage(org).settled_resolution_units == 1
        assert usage.usage(org).reserved_resolution_units == 0
        with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
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
        app.close()


def test_real_confirmed_queue_loss_before_claim_is_rebuilt_from_database(
    scenario: Scenario, tmp_path: Path
) -> None:
    progress, job = planned(scenario, "https://synthetic.publisher.example/no-contact.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    cfg = config(scenario, Ledger(progress.database, progress.token, progress.settings))
    app, _ = create_worker(cfg)
    original = progress.pending(org)[0]
    try:
        # No worker has claimed the owned fixture message. Confirm then lose only
        # this uniquely named synthetic queue's contents, preserving PostgreSQL state.
        assert publish(app, progress, org) == 1
        assert progress.pending(org) == []
        with app.connection_for_write() as connection:
            channel = connection.channel()
            try:
                owned_queue = app.amqp.queues[phase_queue(cfg.queue, "parse")](channel)
                assert owned_queue.purge() == 1
            finally:
                channel.close()
        assert progress.snapshot(org, job).state == "queued"
        progress.reconcile(org, job)
        recovered = progress.pending(org)
        assert len(recovered) == 1 and recovered[0]["event_id"] == original["event_id"]
        with worker(cfg, tmp_path):
            assert publish(app, progress, org) == 1
            wait_for(lambda: progress.snapshot(org, job).state == "completed")
        with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
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
        app.close()

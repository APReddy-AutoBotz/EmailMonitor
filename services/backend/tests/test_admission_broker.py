"""Required actual RabbitMQ phase isolation and once-only settlement; no eager mocks."""

import time
from pathlib import Path

from emailmonitor.administration.service import Administration
from emailmonitor.jobs.broker import create_worker
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.queues import owned_queues, phase_queue
from emailmonitor.progress.broker import publish as publish_progress
from emailmonitor.progress.service import Progress
from emailmonitor.results.broker import publish as publish_exports
from test_admission_tenant import new_job
from test_real_broker_jobs import config, wait_for, worker
from test_results_tenant import options, prepared
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def close_owned(application: object, namespace: str) -> None:
    from typing import Any, cast

    app = cast(Any, application)
    with app.connection_for_write() as connection:
        channel = connection.channel()
        try:
            for name in owned_queues(namespace):
                channel.queue_delete(queue=name)
                channel.exchange_delete(exchange=name)
        finally:
            channel.close()
    app.close()


def test_real_fixed_phase_publication_routes_no_payload_selected_queue(
    scenario: Scenario,
) -> None:
    results, completed = prepared(scenario)
    org = scenario.organizations[0]
    progress = Progress(results.database, results.token, results.settings)
    job = new_job(progress, org, "https://synthetic.publisher.example/no-contact.html")
    progress.start(org, job, progress.snapshot(org, job).revision)
    results.create(org, options(completed), "authored-phase-routing")
    cfg = config(scenario, Ledger(progress.database, progress.token, progress.settings))
    app, _ = create_worker(cfg)
    try:
        # All declarations belong solely to this unique namespace; no consumer yet.
        with app.connection_for_write() as connection:
            channel = connection.channel()
            try:
                for name in owned_queues(cfg.queue):
                    app.amqp.queues[name](channel).declare()
            finally:
                channel.close()
        assert publish_progress(app, progress, org) == publish_exports(app, results, org) == 1
        with app.connection_for_read() as connection:
            channel = connection.channel()
            try:
                counts = {
                    name: channel.queue_declare(queue=name, passive=True).message_count
                    for name in owned_queues(cfg.queue)
                }
            finally:
                channel.close()
        assert counts[cfg.queue] == counts[phase_queue(cfg.queue, "fixture_io")] == 0
        assert (
            counts[phase_queue(cfg.queue, "parse")] == counts[phase_queue(cfg.queue, "export")] == 1
        )
    finally:
        close_owned(app, cfg.queue)


def test_real_held_parse_worker_does_not_block_export_consumer_and_settles_once(
    scenario: Scenario,
    tmp_path: Path,
) -> None:
    results, completed = prepared(scenario)
    org = scenario.organizations[0]
    progress = Progress(results.database, results.token, results.settings)
    job = new_job(progress, org, "https://synthetic.publisher.example/no-contact.html")
    progress.start(org, job, progress.snapshot(org, job).revision)
    export = results.create(org, options(completed), "authored-phase-isolation")
    cfg = config(
        scenario,
        Ledger(progress.database, progress.token, progress.settings),
        diagnostic_delay_seconds=5,
    )
    app, _ = create_worker(cfg)
    administration = Administration(progress.database, progress.token, progress.settings)
    try:
        with (
            worker(cfg, tmp_path, (phase_queue(cfg.queue, "parse"),)),
            worker(cfg, tmp_path, (phase_queue(cfg.queue, "export"),)),
        ):

            def consumers_ready() -> bool:
                try:
                    with app.connection_for_read() as connection:
                        channel = connection.channel()
                        try:
                            return all(
                                channel.queue_declare(queue=name, passive=True).consumer_count == 1
                                for name in (
                                    phase_queue(cfg.queue, "parse"),
                                    phase_queue(cfg.queue, "export"),
                                )
                            )
                        finally:
                            channel.close()
                except Exception:
                    return False

            wait_for(consumers_ready)
            assert publish_progress(app, progress, org) == 1
            wait_for(lambda: administration.usage(org).reserved_resolution_units == 1)
            start = time.monotonic()
            assert publish_exports(app, results, org) == 1
            wait_for(lambda: results.state(org, export.id).state == "ready")
            assert time.monotonic() - start < 5
            assert progress.snapshot(org, job).state == "running"
            assert results.download(org, export.id).body
            wait_for(lambda: progress.snapshot(org, job).state == "completed")
            usage = administration.usage(org)
            assert usage.settled_resolution_units == 2 and usage.reserved_resolution_units == 0
            progress.reconcile(org, job)
            assert administration.usage(org).settled_resolution_units == 2
    finally:
        close_owned(app, cfg.queue)

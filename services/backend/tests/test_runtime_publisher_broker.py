"""Actual SQL/RabbitMQ acceptance for finite owned test publication, never eager mocks."""

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from emailmonitor.administration.service import Administration
from emailmonitor.jobs.broker import create_worker
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.queues import owned_queues, phase_queue
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.broker import ExecutionEvent
from emailmonitor.progress.service import Progress
from emailmonitor.results.broker import ExportEvent
from emailmonitor.runtime import publisher
from kombu import Connection, Producer
from sqlalchemy import text
from test_admission_broker import close_owned
from test_admission_tenant import new_job
from test_progress_broker import deliveries
from test_real_broker_jobs import config, wait_for, worker
from test_results_broker import counters
from test_results_tenant import options, prepared
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


@pytest.fixture
def resources(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, list[Any]]]:
    """Record actual owned transport objects without replacing broker behavior."""
    acquired: list[tuple[Any, list[Any]]] = []
    original = Connection

    def recording_connection(*args: Any, **kwargs: Any) -> Any:
        connection = original(*args, **kwargs)
        channels: list[Any] = []
        original_channel = connection.channel

        def recording_channel() -> Any:
            channel = original_channel()
            channels.append(channel)
            return channel

        monkeypatch.setattr(connection, "channel", recording_channel)
        acquired.append((connection, channels))
        return connection

    monkeypatch.setattr(publisher, "Connection", recording_connection)
    return acquired


def assert_closed(resources: list[tuple[Any, list[Any]]], passes: int) -> None:
    assert len(resources) == passes
    for connection, channels in resources:
        assert not connection.connected
        assert len(channels) == 1
        assert not channels[0].is_open


def publisher_config(cfg: Any) -> publisher.TestPublisherConfig:
    return publisher.TestPublisherConfig(
        environment="test", broker_url=cfg.broker_url, queue=cfg.queue
    )


def queue_counts(app: Any, namespace: str) -> dict[str, int]:
    with app.connection_for_read() as connection:
        channel = connection.channel()
        try:
            return {
                name: channel.queue_declare(queue=name, passive=True).message_count
                for name in owned_queues(namespace)
            }
        finally:
            channel.close()


def declare_owned(app: Any, namespace: str) -> None:
    with app.connection_for_write() as connection:
        channel = connection.channel()
        try:
            for name in owned_queues(namespace):
                app.amqp.queues[name](channel).declare()
        finally:
            channel.close()


def test_real_owned_publisher_exact_id_only_fixed_phase_routes(
    scenario: Scenario, resources: list[tuple[Any, list[Any]]]
) -> None:
    results, completed = prepared(scenario)
    org = scenario.organizations[0]
    progress = Progress(results.database, results.token, results.settings)
    for url in ("https://synthetic.publisher.example/no-contact.html", None):
        job = new_job(progress, org, url)
        progress.start(org, job, progress.snapshot(org, job).revision)
    export = results.create(org, options(completed), "owned-routing")
    rows = progress.pending(org)
    export_row = results.pending(org)[0]
    cfg = config(scenario, Ledger(progress.database, progress.token, progress.settings))
    app, _ = create_worker(cfg)
    expected = {
        phase_queue(
            cfg.queue, "fixture_io" if row["work_kind"] == "discover" else "parse"
        ): ExecutionEvent(
            organization_id=str(org),
            job_id=str(row["job_id"]),
            item_id=str(row["item_id"]),
            event_id=str(row["event_id"]),
            generation=int(str(row["generation"])),
        ).model_dump()
        for row in rows
    }
    expected[phase_queue(cfg.queue, "export")] = ExportEvent(
        organization_id=str(org),
        export_id=str(export.id),
        event_id=str(export_row["event_id"]),
        generation=int(str(export_row["generation"])),
    ).model_dump()
    try:
        declare_owned(app, cfg.queue)
        with app.connection_for_write() as caller:
            caller_channel = caller.channel()
            try:
                counts = publisher.publish_once(publisher_config(cfg), app, progress, results, org)
                assert (counts.execution, counts.exports) == (2, 1)
                assert_closed(resources, 1)
                assert caller.connected and caller_channel.is_open
                assert queue_counts(app, cfg.queue) == {
                    name: int(name in expected) for name in owned_queues(cfg.queue)
                }
                for name, body in expected.items():
                    message = app.amqp.queues[name](caller_channel).get(no_ack=False)
                    assert message is not None
                    assert message.content_type == "application/json"
                    assert message.properties["delivery_mode"] == 2
                    assert message.delivery_info["routing_key"] == name
                    assert message.delivery_info["exchange"] == ""
                    assert message.headers["task"] == (
                        "emailmonitor.fixture.export"
                        if name.endswith("-export")
                        else "emailmonitor.fixture.execute"
                    )
                    args, kwargs, embedded = message.payload
                    assert args == [body] and kwargs == {}
                    assert embedded == {
                        "callbacks": None,
                        "errbacks": None,
                        "chain": None,
                        "chord": None,
                    }
                    message.ack()
                assert progress.pending(org) == results.pending(org) == []
            finally:
                caller_channel.close()
    finally:
        close_owned(app, cfg.queue)


@pytest.mark.parametrize("kind", ["execution", "export"])
def test_real_confirm_then_sql_failure_replays_duplicate_once(
    scenario: Scenario,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resources: list[tuple[Any, list[Any]]],
    kind: str,
) -> None:
    results, completed = prepared(scenario)
    org = scenario.organizations[0]
    progress = Progress(results.database, results.token, results.settings)
    administration = Administration(progress.database, progress.token, progress.settings)
    baseline = administration.usage(org).settled_resolution_units
    if kind == "execution":
        identifier = new_job(progress, org, "https://synthetic.publisher.example/no-contact.html")
        progress.start(org, identifier, progress.snapshot(org, identifier).revision)
        service: Any = progress
    else:
        identifier = results.create(org, options(completed), "owned-mark-replay").id
        service = results
    row = service.pending(org)[0]
    event = UUID(str(row["event_id"]))
    cfg = config(scenario, Ledger(progress.database, progress.token, progress.settings))
    app, _ = create_worker(cfg)
    phase = phase_queue(cfg.queue, "parse" if kind == "execution" else "export")
    original_confirmed = service.confirmed

    def sql_mark_failure(*args: Any, **kwargs: Any) -> None:
        # This boundary is reached only after actual confirmed broker publication.
        # Fail an actual SQL statement before the durable marker and roll back.
        with progress.database.tenant(progress.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
            c.execute(text("SELECT 1 / 0"))

    try:
        declare_owned(app, cfg.queue)
        monkeypatch.setattr(service, "confirmed", sql_mark_failure)
        with pytest.raises(publisher.PublisherError):
            publisher.publish_once(publisher_config(cfg), app, progress, results, org)
        assert_closed(resources, 1)
        assert queue_counts(app, cfg.queue)[phase] == 1
        assert service.pending(org)[0]["event_id"] == row["event_id"]
        monkeypatch.setattr(service, "confirmed", original_confirmed)
        counts = publisher.publish_once(publisher_config(cfg), app, progress, results, org)
        assert (counts.execution, counts.exports) == ((1, 0) if kind == "execution" else (0, 1))
        assert_closed(resources, 2)
        assert queue_counts(app, cfg.queue)[phase] == 2
        assert service.pending(org) == []
        with worker(cfg, tmp_path):
            if kind == "execution":
                wait_for(lambda: deliveries(progress, org, identifier, event) >= 2)
                assert progress.snapshot(org, identifier).state == "completed"
                with progress.database.tenant(
                    progress.token, org, Capability.READ_ORGANIZATION
                ) as (c, _):
                    assert (
                        c.execute(
                            text(
                                "SELECT count(*) FROM emailmonitor.execution_effects "
                                "WHERE organization_id=:org AND job_id=:job"
                            ),
                            {"org": org, "job": identifier},
                        ).scalar_one()
                        == 1
                    )
            else:
                wait_for(lambda: counters(results, org, identifier)[0] >= 2)
                assert counters(results, org, identifier)[1] == 1
                assert results.download(org, identifier).body
        usage = administration.usage(org)
        assert usage.settled_resolution_units == baseline + int(kind == "execution")
        assert usage.reserved_resolution_units == 0
    finally:
        close_owned(app, cfg.queue)


def test_real_partial_batch_broker_failure_preserves_mark_and_caller(
    scenario: Scenario,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resources: list[tuple[Any, list[Any]]],
) -> None:
    results, completed = prepared(scenario)
    org = scenario.organizations[0]
    progress = Progress(results.database, results.token, results.settings)
    job = new_job(progress, org, "https://synthetic.publisher.example/no-contact.html")
    progress.start(org, job, progress.snapshot(org, job).revision)
    export = results.create(org, options(completed), "owned-partial-batch")
    event = UUID(str(progress.pending(org)[0]["event_id"]))
    export_event = results.pending(org)[0]["event_id"]
    cfg = config(scenario, Ledger(progress.database, progress.token, progress.settings))
    app, _ = create_worker(cfg)
    original_producer = Producer
    sends = 0
    broker_failures: list[Exception] = []
    absent_exchange = "em-fixture-absent-" + uuid4().hex

    def failing_second_producer(*args: Any, **kwargs: Any) -> Any:
        producer = original_producer(*args, **kwargs)
        original_publish = producer.publish

        def publish(*args: Any, **kwargs: Any) -> Any:
            nonlocal sends
            sends += 1
            assert kwargs["retry"] is False
            if sends == 2:
                # RabbitMQ itself closes this channel with NOT_FOUND; no fake ack/nack.
                kwargs["exchange"] = absent_exchange
            try:
                return original_publish(*args, **kwargs)
            except Exception as error:
                broker_failures.append(error)
                raise

        monkeypatch.setattr(producer, "publish", publish)
        return producer

    monkeypatch.setattr(publisher, "Producer", failing_second_producer)
    try:
        declare_owned(app, cfg.queue)
        with app.connection_for_write() as caller:
            caller_channel = caller.channel()
            caller_queue = "em-fixture-caller-" + uuid4().hex
            caller_channel.queue_declare(
                queue=caller_queue, durable=False, exclusive=True, auto_delete=False
            )
            try:
                with pytest.raises(publisher.PublisherError):
                    publisher.publish_once(publisher_config(cfg), app, progress, results, org)
                assert sends == 2
                assert len(broker_failures) == 1
                assert getattr(broker_failures[0], "reply_code", None) == 404
                assert_closed(resources, 1)
                assert caller.connected and caller_channel.is_open
                assert caller_channel.queue_declare(queue=caller_queue, passive=True)
                assert progress.pending(org) == []
                assert results.pending(org)[0]["event_id"] == export_event
                counts = queue_counts(app, cfg.queue)
                assert counts[phase_queue(cfg.queue, "parse")] == 1
                assert counts[phase_queue(cfg.queue, "export")] == 0
                replay = publisher.publish_once(publisher_config(cfg), app, progress, results, org)
                assert (replay.execution, replay.exports) == (0, 1)
                assert sends == 3
                assert_closed(resources, 2)
                assert caller_channel.queue_declare(queue=caller_queue, passive=True)
                with worker(cfg, tmp_path):
                    wait_for(lambda: progress.snapshot(org, job).state == "completed")
                    wait_for(lambda: results.state(org, export.id).state == "ready")
                assert deliveries(progress, org, job, event) == 1
                assert counters(results, org, export.id) == (1, 1)
                usage = Administration(progress.database, progress.token, progress.settings).usage(
                    org
                )
                assert usage.settled_resolution_units == 2 and usage.reserved_resolution_units == 0
            finally:
                caller_channel.queue_delete(queue=caller_queue)
                caller_channel.close()
    finally:
        close_owned(app, cfg.queue)

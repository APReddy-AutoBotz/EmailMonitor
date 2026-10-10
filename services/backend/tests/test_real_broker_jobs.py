"""Disposable real broker and actual worker failure tests. Never a live source harness."""

import os
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from emailmonitor.jobs.broker import FixtureWorkerConfig, create_worker, publish
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.organizations.roles import Capability
from kombu.exceptions import OperationalError
from sqlalchemy import text
from test_durable_jobs import approved, snapshot
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario

ROOT = Path(__file__).resolve().parents[3]


def wait_for(condition: Callable[[], bool], seconds: int = 35) -> None:
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if condition():
            return
        time.sleep(0.1)
    raise AssertionError("Disposable worker did not reach expected durable state")


def config(s: Scenario, ledger: Ledger, **changes: object) -> FixtureWorkerConfig:
    url = os.environ.get("EM_TEST_BROKER_URL")
    if not url:
        if os.environ.get("EM_REQUIRE_REAL_BROKER") == "true":
            pytest.fail("Required real RabbitMQ evidence is missing")
        pytest.skip("Disposable RabbitMQ unavailable; EM005 broker acceptance remains pending")
    if os.environ.get("EM_TEST_DISPOSABLE_BROKER") != "true":
        pytest.fail("Explicit disposable synthetic broker marker required")
    return FixtureWorkerConfig.model_validate(
        {
            "environment": "test",
            "database_url": os.environ["EM_TEST_DATABASE_URL"],
            "broker_url": url,
            "organization": str(s.organizations[0]),
            "session_token": ledger.token,
            "queue": "em-fixture-" + uuid4().hex,
            **changes,
        }
    )


@contextmanager
def worker(cfg: FixtureWorkerConfig, directory: Path) -> Iterator[subprocess.Popen[bytes]]:
    path = directory / (cfg.queue + ".json")
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as file:
        file.write(cfg.model_dump_json())
    log = (directory / (cfg.queue + ".log")).open("wb")
    environment = {
        **os.environ,
        "EM_FIXTURE_WORKER": "true",
        "EM_FIXTURE_WORKER_CONFIG": str(path),
        "PYTHONPATH": str(ROOT / "services/backend/src"),
    }
    process = subprocess.Popen(
        [
            str(ROOT / "services/backend/.venv/bin/celery"),
            "-A",
            "emailmonitor.jobs.fixture_worker:app",
            "worker",
            "--pool=solo",
            "--concurrency=1",
            "--loglevel=WARNING",
            "--without-gossip",
            "--without-mingle",
            "--without-heartbeat",
        ],
        cwd=ROOT,
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        log.close()
        path.unlink(missing_ok=True)


def units(ledger: Ledger, org: UUID, job: UUID) -> int:
    with ledger.database.tenant(ledger.token, org, Capability.READ_ORGANIZATION) as (c, _):
        return int(
            c.execute(
                text("""SELECT count(*) FROM emailmonitor.usage_events
WHERE organization_id=:org AND job_id=:job"""),
                {"org": org, "job": job},
            ).scalar_one()
        )


def deliveries(ledger: Ledger, organization: UUID, event: UUID) -> int:
    with ledger.database.tenant(ledger.token, organization, Capability.READ_ORGANIZATION) as (c, _):
        return int(
            c.execute(
                text("""SELECT count(*) FROM emailmonitor.audit_events
WHERE organization_id=:org AND resource_id=:event AND action='fixture.delivery.received'"""),
                {"org": organization, "event": event},
            ).scalar_one()
        )


def test_real_delivery_duplicate_publish_and_ledger_replay(
    scenario: Scenario, tmp_path: Path
) -> None:
    ledger = approved(scenario)
    cfg = config(scenario, ledger)
    app, _ = create_worker(cfg)
    org = scenario.organizations[0]
    job = ledger.create_probe(org, 1)
    work = ledger.outbox(org)[0]
    try:
        with worker(cfg, tmp_path):
            assert publish(app, ledger, org) == 1
            # Normal at-least-once duplicate delivery has no second persistence effect.
            app.send_task(
                "emailmonitor.fixture.persist",
                args=[work.message()],
                queue=cfg.queue,
                routing_key=cfg.queue,
                retry=False,
            )
            wait_for(lambda: snapshot(ledger, org, job)["state"] == "completed")
            wait_for(lambda: deliveries(ledger, org, work.event) >= 2)
            assert units(ledger, org, job) == 1
            assert publish(app, ledger, org) == 1  # durable result notification
            assert ledger.reconcile(org, job) == 0
    finally:
        app.close()


def test_actual_worker_kill_before_commit_recovers_expired_lease(
    scenario: Scenario, tmp_path: Path
) -> None:
    ledger = approved(scenario)
    cfg = config(scenario, ledger, lease_seconds=2, diagnostic_delay_seconds=20)
    app, _ = create_worker(cfg)
    org = scenario.organizations[0]
    job = ledger.create_probe(org, 1)
    try:
        with worker(cfg, tmp_path) as process:
            publish(app, ledger, org)
            wait_for(lambda: snapshot(ledger, org, job)["state"] == "running")
            process.kill()
            assert process.wait(timeout=5) < 0
        assert units(ledger, org, job) == 0
        time.sleep(2.1)
        assert ledger.reconcile(org, job) == 1
        recovered = cfg.model_copy(update={"diagnostic_delay_seconds": 0})
        with worker(recovered, tmp_path):
            publish(app, ledger, org)
            wait_for(lambda: snapshot(ledger, org, job)["state"] == "completed")
        assert units(ledger, org, job) == 1
    finally:
        app.close()


def test_actual_exit_after_commit_before_ack_is_duplicate_safe(
    scenario: Scenario, tmp_path: Path
) -> None:
    ledger = approved(scenario)
    cfg = config(scenario, ledger, exit_after_commit=True)
    app, _ = create_worker(cfg)
    org = scenario.organizations[0]
    job = ledger.create_probe(org, 1)
    work = ledger.outbox(org)[0]
    try:
        with worker(cfg, tmp_path) as process:
            publish(app, ledger, org)
            wait_for(lambda: process.poll() is not None)
            assert process.returncode == 73
        assert units(ledger, org, job) == 1
        recovered = cfg.model_copy(update={"exit_after_commit": False})
        with worker(recovered, tmp_path):
            # Observe the original unacked broker delivery; do not mask it with republishing.
            wait_for(lambda: deliveries(ledger, org, work.event) >= 2)
            assert publish(app, ledger, org) == 1
            assert snapshot(ledger, org, job)["state"] == "completed"
        assert units(ledger, org, job) == 1
    finally:
        app.close()


def test_actual_disposable_broker_outage_preserves_unpublished_outbox(
    scenario: Scenario, tmp_path: Path
) -> None:
    ledger = approved(scenario)
    cfg = config(scenario, ledger)
    container = os.environ.get("EM_TEST_BROKER_CONTAINER", "")
    if os.environ.get("GITHUB_ACTIONS") != "true" or not container or not container.isalnum():
        pytest.fail("Broker failure gate requires its own disposable CI service container")
    app, _ = create_worker(cfg)
    org = scenario.organizations[0]
    job = ledger.create_probe(org, 1)
    command = ["docker", "exec", container, "rabbitmqctl"]
    try:
        subprocess.run([*command, "stop_app"], check=True, capture_output=True, timeout=30)
        with pytest.raises((OperationalError, OSError, ConnectionError)):
            publish(app, ledger, org)
        assert len(ledger.outbox(org)) == 1
        assert units(ledger, org, job) == 0
    finally:
        subprocess.run([*command, "start_app"], check=True, capture_output=True, timeout=30)
        app.close()
    app, _ = create_worker(cfg)
    try:
        with worker(cfg, tmp_path):
            ledger.reconcile(org, job)
            assert publish(app, ledger, org) == 1
            wait_for(lambda: snapshot(ledger, org, job)["state"] == "completed")
        assert units(ledger, org, job) == 1
    finally:
        app.close()

"""Actual isolated service logins, subprocess worker and confirmed broker transport."""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from emailmonitor.jobs.queues import owned_queues
from emailmonitor.organizations.database import AuthorizationDenied, digest
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.service import Progress
from emailmonitor.results.broker import ExportEvent
from emailmonitor.runtime.authority import ServiceProcess
from emailmonitor.runtime.database import ServiceDatabase
from emailmonitor.runtime.publisher import PublisherError
from emailmonitor.runtime.service_publisher import publish_service_once
from emailmonitor.runtime.worker import ServiceRuntimeConfig, broker_application
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from test_admission_broker import close_owned
from test_durable_jobs import SETTINGS
from test_real_broker_jobs import wait_for
from test_runtime_publisher_broker import declare_owned, queue_counts
from test_service_authority_tenant import ServiceCase
from test_service_authority_tenant import _service_ci_guard as _service_ci_guard
from test_service_authority_tenant import service_case as service_case
from test_tenant_foundation import scenario as scenario

ROOT = Path(__file__).resolve().parents[3]

PUBLICATION_LOCKS = {
    "job": "SELECT id FROM emailmonitor.jobs WHERE organization_id=:org AND id=:resource",
    "item": (
        "SELECT id FROM emailmonitor.execution_items "
        "WHERE organization_id=:org AND job_id=:resource AND id=:item"
    ),
    "outbox": (
        "SELECT event_id FROM emailmonitor.execution_outbox "
        "WHERE organization_id=:org AND job_id=:resource AND event_id=:event"
    ),
}


def publication_params(case: ServiceCase, *, confirm: bool = False) -> dict[str, object]:
    with case.admin.connect() as c:
        row = c.execute(
            text(
                "SELECT item_id,event_id,generation FROM emailmonitor.execution_outbox "
                "WHERE organization_id=:org AND job_id=:job AND published_at IS NULL"
            ),
            {"org": case.scope.organization, "job": case.scope.resource},
        ).one()
    return {
        "org": case.scope.organization,
        "resource": case.scope.resource,
        "purpose": "extraction",
        "generation": row.generation,
        "item": row.item_id,
        "event": row.event_id,
        "confirm": confirm,
    }


def publication_receipt(case: ServiceCase, event: object) -> object:
    with case.admin.connect() as c:
        return c.execute(
            text(
                "SELECT published_at FROM emailmonitor.execution_outbox "
                "WHERE organization_id=:org AND job_id=:job AND event_id=:event"
            ),
            {
                "org": case.scope.organization,
                "job": case.scope.resource,
                "event": event,
            },
        ).scalar_one()


def durable_job_state(case: ServiceCase) -> str:
    """Observe this synthetic job without competing with the worker's row lock."""
    with case.admin.connect() as c:
        return str(
            c.execute(
                text("SELECT state FROM emailmonitor.jobs WHERE organization_id=:org AND id=:job"),
                {"org": case.scope.organization, "job": case.scope.resource},
            ).scalar_one()
        )


@dataclass
class ExportClaimBarrier:
    """Only this event's owned, publisher-blocked claim establishes the race."""

    database: str
    worker_login: str
    publisher_login: str
    event: ExportEvent
    observed_pid: int | None = None

    def check_event(self, name: object, arguments: object) -> None:
        if name != "emailmonitor.service.export" or arguments != [self.event.model_dump()]:
            raise AssertionError("Unexpected export publication event")

    def settled(self, rows: Sequence[Mapping[str, object]], drained: Callable[[], bool]) -> bool:
        owned = [
            row
            for row in rows
            if row["datname"] == self.database and row["backend_type"] == "client backend"
        ]
        workers = [row for row in owned if row["usename"] == self.worker_login]
        publishers = [
            row
            for row in owned
            if row["usename"] == self.publisher_login
            and row["state"] == "idle in transaction"
            and row["query"] == "SELECT emailmonitor.service_publish_event($1,$2,$3,$4,$5,$6,$7)"
        ]
        if len(publishers) != 1:
            return False
        publisher = publishers[0]
        waiters = [
            row
            for row in workers
            if row["state"] == "active"
            and row["query"] == "SELECT emailmonitor.exports_claim($1,$2,$3,$4,$5,$6)"
            and row["wait_event_type"] == "Lock"
            and isinstance(row["blockers"], list)
            and publisher["pid"] in row["blockers"]
            and type(row["pid"]) is int
        ]
        if len(waiters) > 1:
            return False
        if waiters:
            pid = waiters[0]["pid"]
            assert type(pid) is int
            if self.observed_pid is None:
                self.observed_pid = pid
            return False
        previous = [row for row in workers if row["pid"] == self.observed_pid]
        if (
            self.observed_pid is None
            or len(previous) != 1
            or (
                previous[0]["state"] == "active"
                and previous[0]["query"] == "SELECT emailmonitor.exports_claim($1,$2,$3,$4,$5,$6)"
            )
        ):
            return False
        return drained()


@pytest.fixture
def publisher_config(service_case: ServiceCase) -> Iterator[ServiceRuntimeConfig]:
    case = service_case
    broker = os.environ.get("EM_TEST_BROKER_URL")
    if not broker:
        if os.environ.get("EM_REQUIRE_REAL_BROKER") == "true":
            pytest.fail("Required service broker acceptance unavailable")
        pytest.skip("Disposable service broker unavailable")
    if os.environ.get("EM_TEST_DISPOSABLE_BROKER") != "true":
        pytest.fail("Explicit disposable broker marker required")
    name, principal = "em_publisher_test_" + uuid4().hex, uuid4()
    url = make_url(case.url).set(username=name).render_as_string(hide_password=False)
    try:
        with case.admin.begin() as c:
            c.exec_driver_sql(
                f"CREATE ROLE {name} LOGIN NOSUPERUSER NOBYPASSRLS "
                "PASSWORD 'authored-disposable-service-only'"
            )
            c.exec_driver_sql(f"GRANT emailmonitor_publisher TO {name}")
            c.execute(
                text(
                    "INSERT INTO emailmonitor.service_principals "
                    "(id,organization_id,login_oid,login_name,kind,active) "
                    "SELECT :id,:org,oid,rolname,'publisher',true FROM pg_roles "
                    "WHERE rolname=:name"
                ),
                {"id": principal, "org": case.scope.organization, "name": name},
            )
        with case.progress.database.tenant(
            case.progress.token, case.scope.organization, Capability.ACQUIRE_SOURCE
        ) as (c, _):
            c.execute(
                text(
                    "SELECT emailmonitor.delegate_service_work("
                    ":org,:principal,:job,'extraction',21600)"
                ),
                {
                    "org": case.scope.organization,
                    "principal": principal,
                    "job": case.scope.resource,
                },
            )
        yield ServiceRuntimeConfig(
            environment="test",
            database_url=url,
            broker_url=broker,
            organization=case.scope.organization,
            queue="em-fixture-" + case.scope.organization.hex,
            process=ServiceProcess(kind="publisher", principal=principal),
            lease_seconds=5,
        )
    finally:
        with case.admin.begin() as c:
            c.execute(
                text("DELETE FROM emailmonitor.service_audit WHERE principal_id=:id"),
                {"id": principal},
            )
            c.execute(
                text("DELETE FROM emailmonitor.service_delegations WHERE principal_id=:id"),
                {"id": principal},
            )
            c.execute(
                text("DELETE FROM emailmonitor.service_principals WHERE id=:id"), {"id": principal}
            )
            c.exec_driver_sql(f"DROP ROLE IF EXISTS {name}")


@pytest.mark.parametrize("row", ["job", "item", "outbox"])
def test_service_publication_busy_row_defers_without_send_or_receipt(
    service_case: ServiceCase, publisher_config: ServiceRuntimeConfig, row: str
) -> None:
    case, config = service_case, publisher_config
    params = publication_params(case)
    application = broker_application(config)
    try:
        declare_owned(application, config.queue)
        with case.admin.begin() as holder:
            holder.execute(text(PUBLICATION_LOCKS[row] + " FOR UPDATE"), params).one()
            assert publish_service_once(config) == 0
            assert not any(queue_counts(application, config.queue).values())
            assert publication_receipt(case, params["event"]) is None
        # A separate finite pass after release publishes the same pending event.
        assert publish_service_once(config) == 1
        assert sum(queue_counts(application, config.queue).values()) == 1
        assert publication_receipt(case, params["event"]) is not None
    finally:
        close_owned(application, config.queue)


@pytest.mark.parametrize("row", ["job", "item", "outbox"])
def test_service_publication_confirm_busy_row_remains_fatal(
    service_case: ServiceCase, publisher_config: ServiceRuntimeConfig, row: str
) -> None:
    case, config = service_case, publisher_config
    params = publication_params(case, confirm=True)
    publisher = ServiceDatabase(config.database_url, config.process)
    sqlstates: list[str] = []
    try:
        with case.admin.begin() as holder:
            holder.execute(text(PUBLICATION_LOCKS[row] + " FOR UPDATE"), params).one()
            with pytest.raises(AuthorizationDenied):
                with publisher.tenant(
                    case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE
                ) as (c, _):
                    try:
                        c.execute(
                            text(
                                "SELECT emailmonitor.service_publish_event("
                                ":org,:resource,:purpose,:generation,:event,:item,:confirm)"
                            ),
                            params,
                        ).scalar_one()
                    except DBAPIError as error:
                        assert error.orig is not None
                        detail = error.orig.args[0]
                        assert isinstance(detail, dict)
                        sqlstates.append(str(detail.get("C")))
                        raise
        assert sqlstates == ["55P03"]
        assert publication_receipt(case, params["event"]) is None
    finally:
        publisher.engine.dispose()


@pytest.mark.parametrize("revoked", ["origin", "delegation"])
def test_service_publication_revocation_after_enumeration_is_not_busy_defer(
    service_case: ServiceCase,
    publisher_config: ServiceRuntimeConfig,
    monkeypatch: pytest.MonkeyPatch,
    revoked: str,
) -> None:
    from typing import Any

    from emailmonitor.runtime import service_publisher
    from kombu import Connection

    case, config = service_case, publisher_config
    params = publication_params(case)
    application = broker_application(config)
    original = Connection
    revoked_after_enumeration = False

    def revoke_then_connect(*args: Any, **kwargs: Any) -> Any:
        nonlocal revoked_after_enumeration
        # This constructor occurs after service_pending selected the exact event,
        # before the publisher's scoped transaction and before any broker send.
        with case.admin.begin() as c:
            if revoked == "origin":
                assert isinstance(case.progress.token, str)
                c.execute(
                    text(
                        "UPDATE emailmonitor.sessions SET revoked_at=clock_timestamp() "
                        "WHERE token_hash=:token"
                    ),
                    {"token": digest(case.progress.token)},
                )
            else:
                c.execute(
                    text(
                        "UPDATE emailmonitor.service_delegations "
                        "SET revoked_at=clock_timestamp() WHERE principal_id=:principal"
                    ),
                    {"principal": config.process.principal},
                )
        revoked_after_enumeration = True
        return original(*args, **kwargs)

    try:
        declare_owned(application, config.queue)
        monkeypatch.setattr(service_publisher, "Connection", revoke_then_connect)
        with case.admin.begin() as holder:
            holder.execute(text(PUBLICATION_LOCKS["job"] + " FOR UPDATE"), params).one()
            with pytest.raises(PublisherError, match="Service publication failed"):
                publish_service_once(config)
        assert revoked_after_enumeration
        assert not any(queue_counts(application, config.queue).values())
        assert publication_receipt(case, params["event"]) is None
    finally:
        close_owned(application, config.queue)


@contextmanager
def installed_worker(
    config: ServiceRuntimeConfig, directory: Path, *, crash_after_observation: bool = False
) -> Iterator[subprocess.Popen[bytes]]:
    # A distinct installed layout, no cwd/source-checkout or test-module imports.
    installed = directory / ("runtime-" + uuid4().hex)
    shutil.copytree(
        ROOT / "services/backend/src",
        installed / "services/backend/src",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(ROOT / "fixtures/html", installed / "fixtures/html")
    path = directory / (uuid4().hex + ".json")
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        stream.write(config.model_dump_json())
    command = [sys.executable, "-B", "-m", "emailmonitor.runtime.entrypoint"]
    if crash_after_observation:
        injection = directory / (uuid4().hex + ".py")
        injection.write_text("""
import os
from emailmonitor.progress.service import Progress
from emailmonitor.runtime.entrypoint import main
original = Progress.process_fixture
def crash(self, work, after_observation=None):
    return original(self, work, after_observation=lambda: os._exit(73))
Progress.process_fixture = crash
raise SystemExit(main())
""")
        command = [sys.executable, "-B", str(injection)]
    process = subprocess.Popen(
        [*command, "worker", "--config", str(path)],
        cwd=installed,
        env={**os.environ, "PYTHONPATH": str(installed / "services/backend/src")},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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
        path.unlink(missing_ok=True)


def test_service_real_installed_worker_survives_human_expiry_and_restart(
    service_case: ServiceCase,
    publisher_config: ServiceRuntimeConfig,
    tmp_path: Path,
) -> None:
    case, config = service_case, publisher_config
    worker_config = ServiceRuntimeConfig.model_validate(
        {
            **config.model_dump(),
            "database_url": case.url,
            "lease_seconds": 30,
            "process": ServiceProcess(kind="worker", principal=case.principal),
        }
    )
    application = broker_application(config)
    progress = Progress(case.database, case.scope, SETTINGS)
    try:
        declare_owned(application, config.queue)
        with case.admin.begin() as c:
            c.execute(
                text(
                    "UPDATE emailmonitor.sessions "
                    "SET expires_at=clock_timestamp()-interval '1 second' "
                    "WHERE token_hash=:token"
                ),
                {"token": digest(case.progress.token)},
            )
        # Empty-process restart is separate from the crash/lease tests below.
        with installed_worker(worker_config, tmp_path) as first:
            assert first.poll() is None
        with installed_worker(worker_config, tmp_path) as running:

            def complete() -> bool:
                assert running.poll() is None
                publish_service_once(config)
                return durable_job_state(case) == "completed_partial"

            wait_for(complete)
        snapshot = progress.snapshot(case.scope.organization, case.scope.resource)
        assert snapshot.state == "completed_partial"
        assert snapshot.counts.terminal == snapshot.counts.discovered == 4
        assert len(owned_queues(config.queue)) == 4
        with case.admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.execution_effects "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": case.scope.organization, "job": case.scope.resource},
                ).scalar_one()
                == 4
            )
    finally:
        close_owned(application, config.queue)


def broker_counts(queue: str) -> tuple[int, int, int]:
    """CI-only metadata probe; never retrieves messages or broker credentials."""
    import json
    import re

    container = os.environ.get("EM_TEST_BROKER_CONTAINER", "")
    if os.environ.get("GITHUB_ACTIONS") != "true" or not re.fullmatch(r"[a-f0-9]{64}", container):
        if os.environ.get("EM_REQUIRE_REAL_BROKER") == "true":
            pytest.fail("Required owned broker statistics unavailable")
        pytest.skip("Owned disposable broker statistics unavailable")
    result = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "rabbitmqctl",
            "list_queues",
            "--quiet",
            "--formatter=json",
            "name",
            "messages_ready",
            "messages_unacknowledged",
            "consumers",
        ],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert len(result.stdout) <= 1_048_576
    rows = json.loads(result.stdout)
    row = next(value for value in rows if value["name"] == queue)
    return int(row["messages_ready"]), int(row["messages_unacknowledged"]), int(row["consumers"])


def test_service_real_export_publish_claim_race_recovers_without_manual_delivery(
    service_case: ServiceCase,
    publisher_config: ServiceRuntimeConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typing import Any

    from emailmonitor.jobs.queues import phase_queue
    from emailmonitor.results.service import Results
    from emailmonitor.runtime import service_publisher
    from test_progress_tenant import drain
    from test_results_tenant import options

    case, config = service_case, publisher_config
    org, job = case.scope.organization, case.scope.resource
    drain(case.progress, org, job)
    human = Results(case.progress.database, case.progress.token, SETTINGS)
    artifact = human.create(org, options(job), str(uuid4()))
    with case.progress.database.tenant(case.progress.token, org, Capability.EXPORT_RESULTS) as (
        c,
        _,
    ):
        for principal in (case.principal, config.process.principal):
            c.execute(
                text(
                    "SELECT emailmonitor.delegate_service_work(:org,:principal,:id,'export',21600)"
                ),
                {"org": org, "principal": principal, "id": artifact.id},
            )
    worker_config = ServiceRuntimeConfig.model_validate(
        {
            **config.model_dump(),
            "database_url": case.url,
            "process": ServiceProcess(kind="worker", principal=case.principal),
        }
    )
    application = broker_application(config)
    queue = phase_queue(config.queue, "export")
    original = broker_application
    barrier_observed = False
    worker_url, publisher_url = make_url(case.url), make_url(config.database_url)
    assert worker_url.database and worker_url.username and publisher_url.username
    with case.admin.connect() as c:
        event = c.execute(
            text(
                "SELECT event_id,generation FROM emailmonitor.export_outbox "
                "WHERE organization_id=:org AND export_id=:id"
            ),
            {"org": org, "id": artifact.id},
        ).one()
    claim_barrier = ExportClaimBarrier(
        worker_url.database,
        worker_url.username,
        publisher_url.username,
        ExportEvent(
            organization_id=str(org),
            export_id=str(artifact.id),
            event_id=str(event.event_id),
            generation=event.generation,
        ),
    )

    def wrapped(configuration: ServiceRuntimeConfig) -> Any:
        app = original(configuration)
        send = app.send_task

        def barrier(*args: Any, **kwargs: Any) -> Any:
            nonlocal barrier_observed
            claim_barrier.check_event(args[0] if len(args) == 1 else None, kwargs.get("args"))
            receipt = send(*args, **kwargs)

            # Held publisher SQL transaction still owns the export SHARE lock.
            # Empty broker counts before delivery do not prove a claim occurred.
            def claim_settled() -> bool:
                with case.admin.connect() as c:
                    rows = (
                        c.execute(
                            text(
                                "SELECT pid,usename,datname,backend_type,state,wait_event_type,"
                                "btrim(query) AS query,pg_blocking_pids(pid) AS blockers "
                                "FROM pg_stat_activity WHERE datname=current_database() "
                                "AND usename IN (:worker,:publisher)"
                            ),
                            {
                                "worker": claim_barrier.worker_login,
                                "publisher": claim_barrier.publisher_login,
                            },
                        )
                        .mappings()
                        .all()
                    )
                return claim_barrier.settled(
                    [dict(row) for row in rows], lambda: broker_counts(queue)[:2] == (0, 0)
                )

            wait_for(claim_settled, seconds=20)
            with case.admin.connect() as c:
                row = c.execute(
                    text(
                        "SELECT state,attempts FROM emailmonitor.exports "
                        "WHERE organization_id=:org AND id=:id"
                    ),
                    {"org": org, "id": artifact.id},
                ).one()
                assert tuple(row) == ("queued", 0)
            barrier_observed = True
            return receipt

        app.send_task = barrier
        return app

    try:
        declare_owned(application, config.queue)
        with installed_worker(worker_config, tmp_path) as running:
            wait_for(lambda: broker_counts(queue)[2] == 1)
            with monkeypatch.context() as patch:
                patch.setattr(service_publisher, "broker_application", wrapped)
                assert publish_service_once(config) == 1
            assert barrier_observed and running.poll() is None

            def unpublished() -> bool:
                with case.admin.connect() as c:
                    return bool(
                        c.execute(
                            text(
                                "SELECT published_at IS NULL "
                                "FROM emailmonitor.export_outbox "
                                "WHERE organization_id=:org AND export_id=:id"
                            ),
                            {"org": org, "id": artifact.id},
                        ).scalar_one()
                    )

            # No manual SQL reconciliation or message injection: owned timer recovers.
            wait_for(unpublished)

            def ready() -> bool:
                assert running.poll() is None
                publish_service_once(config)
                return human.state(org, artifact.id).state == "ready"

            wait_for(ready)
        with case.admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.export_artifacts "
                        "WHERE organization_id=:org AND export_id=:id"
                    ),
                    {"org": org, "id": artifact.id},
                ).scalar_one()
                == 1
            )
    finally:
        close_owned(application, config.queue)


def test_service_real_post_observation_crash_original_redelivery_then_lease_recovery(
    service_case: ServiceCase,
    publisher_config: ServiceRuntimeConfig,
    tmp_path: Path,
) -> None:
    case, config = service_case, publisher_config
    worker_config = ServiceRuntimeConfig.model_validate(
        {
            **config.model_dump(),
            "database_url": case.url,
            "lease_seconds": 30,
            "process": ServiceProcess(kind="worker", principal=case.principal),
        }
    )
    application = broker_application(config)
    progress = Progress(case.database, case.scope, SETTINGS)
    params = {"org": case.scope.organization, "job": case.scope.resource}
    try:
        declare_owned(application, config.queue)
        with installed_worker(worker_config, tmp_path, crash_after_observation=True) as crashed:

            def exited() -> bool:
                if crashed.poll() is not None:
                    return True
                publish_service_once(config)
                return False

            wait_for(exited)
            assert crashed.returncode == 73
        with case.admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    params,
                ).scalar_one()
                == 1
            )
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.association_batches "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    params,
                ).scalar_one()
                == 0
            )
            item: UUID = c.execute(
                text(
                    "SELECT id FROM emailmonitor.execution_items "
                    "WHERE organization_id=:org AND job_id=:job AND state='running'"
                ),
                params,
            ).scalar_one()
        with installed_worker(worker_config, tmp_path) as resumed:
            # No publisher call until the broker's original delivery is counted.
            def original_redelivered() -> bool:
                assert resumed.poll() is None
                with case.admin.connect() as c:
                    return bool(
                        c.execute(
                            text(
                                "SELECT o.deliveries>=2 AND i.lease_until>clock_timestamp() "
                                "FROM emailmonitor.execution_outbox o "
                                "JOIN emailmonitor.execution_items i "
                                "ON i.organization_id=o.organization_id AND i.job_id=o.job_id "
                                "AND i.id=o.item_id WHERE o.organization_id=:org "
                                "AND o.job_id=:job AND o.item_id=:item"
                            ),
                            {**params, "item": item},
                        ).scalar_one()
                    )

            wait_for(original_redelivered, seconds=15)

            def completed() -> bool:
                assert resumed.poll() is None
                publish_service_once(config)
                return durable_job_state(case) == "completed_partial"

            wait_for(completed, seconds=60)
        snapshot = progress.snapshot(case.scope.organization, case.scope.resource)
        assert snapshot.state == "completed_partial"
        assert snapshot.counts.terminal == snapshot.counts.discovered == 4
        with case.admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.execution_effects "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    params,
                ).scalar_one()
                == 4
            )
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    params,
                ).scalar_one()
                == 4
            )
    finally:
        close_owned(application, config.queue)


def test_service_publisher_skips_ineligible_older_resource_before_limit(
    service_case: ServiceCase,
    publisher_config: ServiceRuntimeConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from emailmonitor.discovery.service import Discovery
    from emailmonitor.jobs import ledger as ledger_module
    from emailmonitor.jobs.models import JobRequest
    from emailmonitor.lifecycle.models import RetentionUpdate
    from emailmonitor.lifecycle.service import Lifecycle
    from emailmonitor.runtime.database import ServiceDatabase
    from test_job_contracts import request_body
    from test_progress_tenant import claim

    case, config = service_case, publisher_config
    org, old_job = case.scope.organization, case.scope.resource
    case.progress.process_fixture(claim(case.progress, org, old_job))
    with case.admin.connect() as c:
        target = c.execute(
            text(
                "SELECT i.id,o.event_id FROM emailmonitor.execution_items i "
                "JOIN emailmonitor.execution_outbox o ON o.organization_id=i.organization_id "
                "AND o.job_id=i.job_id AND o.item_id=i.id WHERE i.organization_id=:org "
                "AND i.job_id=:job AND i.input_url=:url"
            ),
            {
                "org": org,
                "job": old_job,
                "url": "https://synthetic.publisher.example/article-a.html",
            },
        ).one()
    work = case.progress.claim(org, old_job, target[0], target[1])
    assert work is not None
    case.progress.process_fixture(work)
    lifecycle = Lifecycle(case.progress.database, case.progress.token, SETTINGS)
    retention = lifecycle.retention(org)
    lifecycle.update_retention(
        org,
        RetentionUpdate(
            expected_revision=retention.revision,
            retention=retention.retention.model_copy(update={"excerpt_days": 0}),
        ),
    )
    body = request_body()
    body["input"] = {"type": "url", "url": "https://synthetic.publisher.example/no-contact.html"}
    # Force the valid resource after the stale one to exercise LIMIT starvation.
    last = UUID(int=(1 << 128) - 1)
    assert old_job < last
    identifiers = iter((last, uuid4()))
    with monkeypatch.context() as patch:
        patch.setattr(ledger_module, "uuid4", lambda: next(identifiers))
        job = ledger_module.Ledger(case.progress.database, case.progress.token, SETTINGS).create(
            org, JobRequest.model_validate(body), str(uuid4())
        )
    Discovery(case.progress.database, case.progress.token, SETTINGS).plan(org, job, 1)
    case.progress.start(org, job, case.progress.snapshot(org, job).revision)
    with case.progress.database.tenant(case.progress.token, org, Capability.ACQUIRE_SOURCE) as (
        c,
        _,
    ):
        c.execute(
            text(
                "SELECT emailmonitor.delegate_service_work(:org,:principal,:job,'extraction',21600)"
            ),
            {"org": org, "principal": config.process.principal, "job": job},
        )
    publisher = ServiceDatabase(config.database_url, config.process)
    application = broker_application(config)
    try:
        with publisher.engine.begin() as c:
            rows: Sequence[UUID] = (
                c.execute(
                    text("SELECT resource_id FROM emailmonitor.service_pending(:principal,1)"),
                    {"principal": config.process.principal},
                )
                .scalars()
                .all()
            )
        assert rows == [job]
        declare_owned(application, config.queue)
        bounded = config.model_copy(
            update={"process": config.process.model_copy(update={"pass_limit": 1})}
        )
        assert publish_service_once(bounded) == 1
        with case.admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.execution_outbox "
                        "WHERE job_id=:job AND published_at IS NOT NULL"
                    ),
                    {"job": job},
                ).scalar_one()
                == 1
            )
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.execution_outbox "
                        "WHERE job_id=:job AND published_at IS NULL"
                    ),
                    {"job": old_job},
                ).scalar_one()
                > 0
            )
    finally:
        publisher.engine.dispose()
        close_owned(application, config.queue)

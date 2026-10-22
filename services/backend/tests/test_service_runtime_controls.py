"""Pure runtime lifecycle/readiness controls; no SQL, broker or identity connections."""

import socket
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock, call
from uuid import UUID

import pytest
from api_client import APIClient
from emailmonitor.config import Settings
from emailmonitor.identity.oidc import OIDCProvider
from emailmonitor.runtime import database as database_module
from emailmonitor.runtime import entrypoint
from emailmonitor.runtime import service_api as api_module
from emailmonitor.runtime import worker as worker_module
from emailmonitor.runtime.assembly import TestRuntimeConfig as RuntimeConfig
from emailmonitor.runtime.authority import ServiceProcess, ServiceWork, WorkPurpose
from emailmonitor.runtime.delegation import ServiceBinding, ServiceBindings
from emailmonitor.runtime.service_api import ServiceAPIConfig
from emailmonitor.runtime.worker import ServiceRuntimeConfig, ServiceWorker

SECRET = "synthetic-runtime-cleanup-secret"
ORGANIZATION = UUID(int=11)
PRINCIPAL = UUID(int=12)
RUNTIME_URL = f"postgresql+pg8000://runtime:{SECRET}@127.0.0.1:5432/disposable"
AUTH_URL = f"postgresql+pg8000://authenticator:{SECRET}@127.0.0.1:5432/disposable"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Pure service controls must not open network connections")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def configuration(*, kind: str = "worker") -> ServiceRuntimeConfig:
    return ServiceRuntimeConfig(
        environment="test",
        database_url=RUNTIME_URL,
        broker_url=f"pyamqp://authored:{SECRET}@127.0.0.1:5672/disposable",
        queue="em-fixture-" + ORGANIZATION.hex,
        organization=ORGANIZATION,
        process=ServiceProcess.model_validate(
            {"kind": kind, "principal": PRINCIPAL, "pass_limit": 2}
        ),
    )


def work(resource: int, purpose: WorkPurpose = "extraction") -> dict[str, object]:
    return {
        "organization_id": ORGANIZATION,
        "resource_id": UUID(int=resource),
        "purpose": purpose,
        "generation": 3,
    }


@dataclass
class WorkerHarness:
    worker: ServiceWorker
    database: MagicMock
    connection: MagicMock
    progress: Mock
    results: Mock
    clock: Mock

    def rows(self, values: list[dict[str, object]]) -> None:
        self.connection.execute.return_value.mappings.return_value.all.return_value = values

    def query_parameters(self) -> dict[str, object]:
        parameters: dict[str, object] = self.connection.execute.call_args.args[1]
        return parameters


@pytest.fixture
def owned(monkeypatch: pytest.MonkeyPatch) -> Iterator[WorkerHarness]:
    database = MagicMock(organization=ORGANIZATION)
    connection = database.engine.begin.return_value.__enter__.return_value
    monkeypatch.setattr(worker_module, "ServiceDatabase", Mock(return_value=database))
    clock = Mock(return_value=100.0)
    monkeypatch.setattr(worker_module, "time", SimpleNamespace(monotonic=clock))
    progress, results = Mock(), Mock()
    monkeypatch.setattr(worker_module, "Progress", progress)
    monkeypatch.setattr(worker_module, "Results", results)
    worker = ServiceWorker(configuration())
    actual_close = worker.application.close
    try:
        yield WorkerHarness(worker, database, connection, progress, results, clock)
    finally:
        # Close the real, connection-free Celery object even when a test replaces close.
        actual_close()


def reconciler_step(owned: WorkerHarness, consumer: object) -> Any:
    steps = [
        step
        for step in owned.worker.application.steps["consumer"]
        if step.__name__ == "ReconcileStep"
    ]
    assert len(steps) == 1
    assert steps[0].requires == ("celery.worker.consumer.tasks:Tasks",)
    return steps[0](consumer)


@pytest.mark.parametrize("action", ["stop", "shutdown", "terminate"])
def test_reconciler_timer_cancels_once_and_can_restart(owned: WorkerHarness, action: str) -> None:
    timer = Mock()
    first, second = Mock(), Mock()
    timer.call_repeatedly.side_effect = [first, second]
    consumer = SimpleNamespace(timer=timer)
    step = reconciler_step(owned, consumer)
    for method in ("stop", "shutdown", "terminate"):
        getattr(step, method)(consumer)
    timer.call_repeatedly.assert_not_called()
    step.start(consumer)
    timer.call_repeatedly.assert_called_once_with(5.0, owned.worker.reconcile_safe)
    assert step.timer is first
    getattr(step, action)(consumer)
    assert step.timer is None
    for method in ("stop", "shutdown", "terminate"):
        getattr(step, method)(consumer)
    first.cancel.assert_called_once_with()
    step.start(consumer)
    assert step.timer is second
    getattr(step, action)(consumer)
    second.cancel.assert_called_once_with()
    assert step.timer is None
    assert timer.call_repeatedly.call_count == 2


@pytest.mark.parametrize("action", ["stop", "shutdown", "terminate"])
def test_reconciler_failed_cancellation_keeps_handle_for_retry(
    owned: WorkerHarness, action: str
) -> None:
    consumer = SimpleNamespace(timer=Mock())
    handle = consumer.timer.call_repeatedly.return_value
    failure = RuntimeError(SECRET)
    handle.cancel.side_effect = [failure, None]
    step = reconciler_step(owned, consumer)
    step.start(consumer)
    with pytest.raises(RuntimeError) as caught:
        getattr(step, action)(consumer)
    assert caught.value is failure
    assert step.timer is handle
    getattr(step, action)(consumer)
    assert step.timer is None and handle.cancel.call_count == 2


def test_reconciler_schedule_failure_leaves_no_timer(owned: WorkerHarness) -> None:
    consumer = SimpleNamespace(timer=Mock())
    consumer.timer.call_repeatedly.side_effect = RuntimeError(SECRET)
    step = reconciler_step(owned, consumer)
    with pytest.raises(RuntimeError):
        step.start(consumer)
    assert step.timer is None
    for action in ("stop", "shutdown", "terminate"):
        getattr(step, action)(consumer)
    consumer.timer.call_repeatedly.assert_called_once()


def test_reconcile_applies_sql_bounds_and_advances_then_wraps_cursor(
    owned: WorkerHarness,
) -> None:
    def outside_worklist_transaction(*args: object) -> None:
        owned.database.engine.begin.return_value.__exit__.assert_called_once_with(None, None, None)

    owned.progress.return_value.reconcile.side_effect = outside_worklist_transaction
    owned.results.return_value.reconcile.side_effect = outside_worklist_transaction
    owned.rows([work(21), work(22, "export")])
    assert owned.worker.reconcile() == 2
    assert owned.query_parameters() == {
        "principal": PRINCIPAL,
        "purpose": None,
        "resource": None,
        "limit": 2,
    }
    timeout_sql = str(owned.connection.execute.call_args_list[0].args[0])
    assert "'statement_timeout','2000ms',true" in timeout_sql
    assert "'lock_timeout','2000ms',true" in timeout_sql
    assert "emailmonitor.service_worklist(" in str(
        owned.connection.execute.call_args_list[1].args[0]
    )
    owned.database.engine.begin.return_value.__exit__.assert_called_once_with(None, None, None)
    for factory, resource, purpose in (
        (owned.progress, 21, "extraction"),
        (owned.results, 22, "export"),
    ):
        scope = ServiceWork.model_validate(
            dict(
                organization=ORGANIZATION,
                resource=UUID(int=resource),
                purpose=purpose,
                generation=3,
            )
        )
        factory.assert_called_once_with(owned.database, scope, owned.worker.settings)
        factory.return_value.reconcile.assert_called_once_with(ORGANIZATION, UUID(int=resource))
    assert owned.worker.cursor == ("export", UUID(int=22))
    owned.progress.return_value.reconcile.side_effect = None
    owned.results.return_value.reconcile.side_effect = None
    owned.rows([work(23, "export")])
    assert owned.worker.reconcile() == 1
    assert owned.query_parameters() == {
        "principal": PRINCIPAL,
        "purpose": "export",
        "resource": UUID(int=22),
        "limit": 2,
    }
    assert owned.worker.cursor is None
    assert owned.worker.reconcile_errors == 0


def test_empty_worklist_wraps_cursor_without_domain_work(owned: WorkerHarness) -> None:
    owned.worker.cursor = ("export", UUID(int=22))
    owned.rows([])
    assert owned.worker.reconcile() == 0
    assert owned.query_parameters()["resource"] == UUID(int=22)
    assert owned.worker.cursor is None
    owned.progress.assert_not_called()
    owned.results.assert_not_called()


@pytest.mark.parametrize("elapsed", [10.0, 10.001, 100.0])
def test_reconcile_exhausted_before_first_row_preserves_previous_cursor(
    owned: WorkerHarness, elapsed: float
) -> None:
    previous = ("extraction", UUID(int=20))
    owned.worker.cursor = previous
    owned.rows([work(21)])  # Even a short page must not reset an unprocessed cursor.
    owned.clock.side_effect = [100.0, 100.0 + elapsed]
    assert owned.worker.reconcile() == 0
    assert owned.worker.cursor == previous
    owned.progress.assert_not_called()
    owned.results.assert_not_called()
    assert owned.worker.reconcile_errors == 0


def test_reconcile_budget_stops_before_next_row_and_resumes_from_last_attempt(
    owned: WorkerHarness,
) -> None:
    owned.rows([work(21), work(22, "export")])
    owned.clock.side_effect = [100.0, 109.999, 110.0]
    assert owned.worker.reconcile() == 1
    assert owned.worker.cursor == ("extraction", UUID(int=21))
    owned.results.assert_not_called()
    owned.rows([work(22, "export")])
    owned.clock.side_effect = [120.0, 120.0]
    assert owned.worker.reconcile() == 1
    assert owned.query_parameters()["purpose"] == "extraction"
    assert owned.query_parameters()["resource"] == UUID(int=21)
    owned.results.return_value.reconcile.assert_called_once_with(ORGANIZATION, UUID(int=22))
    assert owned.worker.cursor is None


@pytest.mark.parametrize("failed_purpose", ["extraction", "export"])
def test_per_resource_failure_is_counted_without_stalling_other_work(
    owned: WorkerHarness,
    failed_purpose: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    owned.rows([work(21), work(22, "export")])
    failed = owned.progress if failed_purpose == "extraction" else owned.results
    failed.return_value.reconcile.side_effect = RuntimeError(SECRET)
    assert owned.worker.reconcile() == 1
    assert owned.worker.cursor == ("export", UUID(int=22))
    assert owned.worker.reconcile_errors == 1
    owned.progress.return_value.reconcile.assert_called_once()
    owned.results.return_value.reconcile.assert_called_once()
    assert capsys.readouterr() == ("", "")


def test_safe_reconcile_retries_worklist_failure_without_printing_details(
    owned: WorkerHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    previous = ("extraction", UUID(int=20))
    owned.worker.cursor = previous
    owned.connection.execute.side_effect = [MagicMock(), RuntimeError(SECRET)]
    owned.worker.reconcile_safe()
    assert owned.worker.cursor == previous
    assert owned.worker.reconcile_errors == 1
    owned.connection.execute.side_effect = None
    owned.rows([work(21)])
    owned.worker.reconcile_safe()
    assert owned.worker.reconcile_errors == 1 and owned.worker.cursor is None
    owned.progress.return_value.reconcile.assert_called_once_with(ORGANIZATION, UUID(int=21))
    assert capsys.readouterr() == ("", "")


def test_reconcile_does_not_swallow_process_cancellation(owned: WorkerHarness) -> None:
    owned.rows([work(21), work(22, "export")])
    cancellation = KeyboardInterrupt()
    owned.progress.return_value.reconcile.side_effect = cancellation
    with pytest.raises(KeyboardInterrupt) as caught:
        owned.worker.reconcile_safe()
    assert caught.value is cancellation
    assert owned.worker.cursor is None and owned.worker.reconcile_errors == 0
    owned.results.assert_not_called()


@pytest.mark.parametrize("failed_resource", ["application", "database", "both"])
def test_worker_close_revokes_admission_and_attempts_each_cleanup_once(
    owned: WorkerHarness, monkeypatch: pytest.MonkeyPatch, failed_resource: str
) -> None:
    events: list[str] = []

    def close_application() -> None:
        assert owned.worker.closed
        events.append("application")
        if failed_resource in {"application", "both"}:
            raise RuntimeError(SECRET)

    def dispose_database() -> None:
        assert owned.worker.closed
        events.append("database")
        if failed_resource in {"database", "both"}:
            raise RuntimeError(SECRET)

    monkeypatch.setattr(owned.worker.application, "close", close_application)
    owned.database.engine.dispose.side_effect = dispose_database
    with pytest.raises(RuntimeError):
        owned.worker.close()
    assert events == ["application", "database"]
    owned.worker.close()
    assert events == ["application", "database"]
    for operation in (
        owned.worker.reconcile,
        lambda: owned.worker.execute({}),
        lambda: owned.worker.export({}),
    ):
        with pytest.raises(RuntimeError, match="^Worker closed$"):
            operation()
    owned.database.engine.begin.assert_not_called()
    owned.progress.assert_not_called()
    owned.results.assert_not_called()


def test_worker_successful_close_is_once_only(owned: WorkerHarness) -> None:
    owned.worker.close()
    owned.worker.close()
    assert owned.worker.closed
    owned.database.engine.dispose.assert_called_once_with()


@pytest.mark.parametrize("failed_cleanup", ["none", "application", "database", "both"])
def test_partial_worker_initialization_attempts_both_cleanup_steps(
    monkeypatch: pytest.MonkeyPatch, failed_cleanup: str
) -> None:
    database = MagicMock(organization=ORGANIZATION)
    application = Mock()
    application.task.side_effect = RuntimeError("initialization-" + SECRET)
    events = Mock()
    events.attach_mock(application.close, "close")
    events.attach_mock(database.engine.dispose, "dispose")
    if failed_cleanup in {"application", "both"}:
        application.close.side_effect = RuntimeError("application-" + SECRET)
    if failed_cleanup in {"database", "both"}:
        database.engine.dispose.side_effect = RuntimeError("database-" + SECRET)
    monkeypatch.setattr(worker_module, "ServiceDatabase", Mock(return_value=database))
    monkeypatch.setattr(worker_module, "broker_application", Mock(return_value=application))
    with pytest.raises(RuntimeError):
        ServiceWorker(configuration())
    assert events.mock_calls == [call.close(), call.dispose()]


def test_worker_tenant_mismatch_disposes_pool_before_broker_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = MagicMock(organization=UUID(int=999))
    broker = Mock()
    monkeypatch.setattr(worker_module, "ServiceDatabase", Mock(return_value=database))
    monkeypatch.setattr(worker_module, "broker_application", broker)
    with pytest.raises(ValueError, match="Registered service tenant must match queue tenant"):
        ServiceWorker(configuration())
    database.engine.dispose.assert_called_once_with()
    broker.assert_not_called()


def test_publisher_principal_cannot_construct_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    database = Mock()
    monkeypatch.setattr(worker_module, "ServiceDatabase", database)
    with pytest.raises(ValueError, match="Worker principal required"):
        ServiceWorker(configuration(kind="publisher"))
    database.assert_not_called()


@pytest.mark.parametrize("command", ["worker", "reconcile-once"])
@pytest.mark.parametrize(
    "work_fails,cleanup_fails",
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_cli_returns_failure_and_only_fixed_diagnostics_for_cleanup_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    command: str,
    work_fails: bool,
    cleanup_fails: bool,
) -> None:
    path = tmp_path / "synthetic-service.json"
    config = configuration()
    path.write_text(config.model_dump_json())
    worker = Mock()
    controller = worker.application.Worker.return_value
    controller.exitcode = 0
    operation = worker.reconcile if command == "reconcile-once" else controller.start
    operation.return_value = 7
    if work_fails:
        operation.side_effect = RuntimeError(f"{SECRET}: {RUNTIME_URL}")
    if cleanup_fails:
        worker.close.side_effect = RuntimeError(f"cleanup-{SECRET}: {config.broker_url}")
    factory = Mock(return_value=worker)
    monkeypatch.setattr(worker_module, "ServiceWorker", factory)
    monkeypatch.setattr(sys, "argv", ["emailmonitor-service", command, "--config", str(path)])
    assert entrypoint.main() == int(work_fails or cleanup_fails)
    factory.assert_called_once_with(config)
    worker.close.assert_called_once_with()
    if command == "worker":
        worker.application.Worker.assert_called_once_with(
            pool="solo",
            concurrency=1,
            loglevel="CRITICAL",
            without_gossip=True,
            without_mingle=True,
            without_heartbeat=True,
            redirect_stdouts=False,
            quiet=True,
        )
        controller.start.assert_called_once_with()
        controller.stop.assert_called_once_with()
    captured = capsys.readouterr()
    assert captured.out == (
        "reconciled=7\n" if command == "reconcile-once" and not work_fails else ""
    )
    assert captured.err == (
        ("service_runtime_failed\n" if work_fails else "")
        + ("service_runtime_cleanup_failed\n" if cleanup_fails else "")
    )
    assert SECRET not in captured.out + captured.err + caplog.text
    assert "Traceback" not in captured.out + captured.err


def test_cli_check_disposal_failure_cannot_report_ready_or_leak_details(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "synthetic-service.json"
    path.write_text(configuration().model_dump_json())
    database = MagicMock(organization=ORGANIZATION)
    database.engine.dispose.side_effect = RuntimeError(f"cleanup-{SECRET}: {RUNTIME_URL}")
    monkeypatch.setattr(database_module, "ServiceDatabase", Mock(return_value=database))
    monkeypatch.setattr(sys, "argv", ["emailmonitor-service", "check", "--config", str(path)])
    assert entrypoint.main() == 1
    database.engine.dispose.assert_called_once_with()
    assert capsys.readouterr() == ("", "service_runtime_failed\n")


class NoExchange:
    def exchange(self, code: str, verifier: str, redirect_uri: str) -> str:
        raise AssertionError("Pure readiness tests must not exchange identity tokens")


@dataclass
class APIHarness:
    config: ServiceAPIConfig
    provider: OIDCProvider
    database: MagicMock
    authentication: MagicMock
    runtime_result: MagicMock
    authentication_result: MagicMock

    def deny(self, reason: str) -> None:
        if reason == "authentication-denied":
            self.authentication_result.scalar_one.return_value = False
        elif reason == "authentication-error":
            self.authentication_result.scalar_one.side_effect = RuntimeError(SECRET)
        elif reason == "runtime-error":
            self.runtime_result.scalar_one.side_effect = RuntimeError(SECRET)
        elif reason == "first-binding-denied":
            self.runtime_result.scalar_one.side_effect = [False]
        elif reason == "second-binding-denied":
            self.runtime_result.scalar_one.side_effect = [True, False]
        else:
            raise AssertionError("Unknown authored readiness failure")


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> APIHarness:
    database, authentication = MagicMock(), MagicMock()
    monkeypatch.setattr(api_module, "Database", Mock(return_value=database))
    monkeypatch.setattr(api_module, "AuthenticationDatabase", Mock(return_value=authentication))
    runtime_result = database.transaction.return_value.__enter__.return_value.execute.return_value
    auth_result = (
        authentication.transaction.return_value.__enter__.return_value.execute.return_value
    )
    runtime_result.scalar_one.return_value = True
    auth_result.scalar_one.return_value = True
    bindings = ServiceBindings(
        tenants=(
            ServiceBinding(organization=ORGANIZATION, worker=PRINCIPAL, publisher=UUID(int=13)),
            ServiceBinding(organization=UUID(int=31), worker=UUID(int=32), publisher=UUID(int=33)),
        )
    )
    config = ServiceAPIConfig(
        RuntimeConfig(
            settings=Settings(environment="test", fixture_mode=True, identity_stub=True),
            runtime_database_url=RUNTIME_URL,
            authentication_database_url=AUTH_URL,
        ),
        bindings,
    )
    provider = OIDCProvider(
        issuer="https://identity.example.test",
        client_id="authored-readiness",
        authorization_endpoint="https://identity.example.test/authorize",
        redirect_uri="https://app.example.test/api/v1/auth/callback",
        verification_keys={"authored": "unused-synthetic-public-key"},
        exchange_adapter=NoExchange(),
        test_only=True,
    )
    return APIHarness(config, provider, database, authentication, runtime_result, auth_result)


READINESS_FAILURES = [
    "authentication-denied",
    "authentication-error",
    "runtime-error",
    "first-binding-denied",
    "second-binding-denied",
]


def test_api_empty_bindings_fail_before_constructing_pools(
    api: APIHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_factory, authentication_factory = Mock(), Mock()
    monkeypatch.setattr(api_module, "Database", runtime_factory)
    monkeypatch.setattr(api_module, "AuthenticationDatabase", authentication_factory)
    config = ServiceAPIConfig(api.config.runtime, ServiceBindings())
    with (
        pytest.raises(ValueError, match="^Explicit tenant service bindings required$"),
        api_module.service_api(config, api.provider),
    ):
        pytest.fail("Empty bindings must not yield an API")
    runtime_factory.assert_not_called()
    authentication_factory.assert_not_called()


def test_api_partial_initialization_disposes_only_constructed_pool(
    api: APIHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = RuntimeError(SECRET)
    monkeypatch.setattr(api_module, "AuthenticationDatabase", Mock(side_effect=failure))
    with (
        pytest.raises(RuntimeError) as caught,
        api_module.service_api(api.config, api.provider),
    ):
        pytest.fail("Failed authentication construction must not yield an API")
    assert caught.value is failure
    api.database.engine.dispose.assert_called_once_with()
    api.authentication.engine.dispose.assert_not_called()
    api.database.transaction.assert_not_called()


@pytest.mark.parametrize("reason", READINESS_FAILURES)
def test_api_startup_refuses_missing_dependencies_and_disposes_both_pools(
    api: APIHarness, reason: str
) -> None:
    api.deny(reason)
    with (
        pytest.raises(ValueError, match="^Exact service schema and registered bindings required$"),
        api_module.service_api(api.config, api.provider),
    ):
        pytest.fail("An unready service API must not be yielded")
    api.authentication.engine.dispose.assert_called_once_with()
    api.database.engine.dispose.assert_called_once_with()
    if reason.startswith("authentication-"):
        api.database.transaction.assert_not_called()


@pytest.mark.parametrize("reason", READINESS_FAILURES)
def test_api_readiness_rechecks_dependencies_and_never_discloses_errors(
    api: APIHarness, reason: str
) -> None:
    with api_module.service_api(api.config, api.provider) as application:
        client = APIClient(application, "https://app.example.test")
        assert client.get("/readyz").json() == {"api_dependencies_ready": True}
        api.deny(reason)
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json() == {"api_dependencies_ready": False}
        assert response.headers["cache-control"] == "no-store"
        assert SECRET not in response.text
        api.runtime_result.scalar_one.side_effect = None
        api.authentication_result.scalar_one.side_effect = None
        api.authentication_result.scalar_one.return_value = True
        recovered = client.get("/readyz")
        assert recovered.status_code == 200
        assert recovered.json() == {"api_dependencies_ready": True}
    calls = (api.database.transaction.call_count, api.authentication.transaction.call_count)
    closed = client.get("/readyz")
    assert closed.status_code == 503
    assert closed.json() == {"detail": "Test runtime is closed"}
    assert calls == (api.database.transaction.call_count, api.authentication.transaction.call_count)


def test_api_readiness_checks_every_exact_binding_and_keeps_profile_truthful(
    api: APIHarness,
) -> None:
    with api_module.service_api(api.config, api.provider) as application:
        connection = api.database.transaction.return_value.__enter__.return_value
        assert [item.args[1] for item in connection.execute.call_args_list] == [
            {"org": binding.organization, "worker": binding.worker, "publisher": binding.publisher}
            for binding in api.config.bindings.tenants
        ]
        assert all(
            "emailmonitor.service_api_binding_ready(" in str(item.args[0])
            for item in connection.execute.call_args_list
        )
        client = APIClient(application, "https://app.example.test")
        response = client.get("/api/v1/runtime-profile")
        assert response.status_code == 200
        assert response.json() == {
            "profile": "authored-html-service-reference",
            "production_ready": False,
            "xml_available": False,
            "pdf_available": False,
            "dynamic_browser_available": False,
            "live_sources_available": False,
        }


def test_api_cleanup_failure_still_closes_admission_and_attempts_other_pool(
    api: APIHarness,
) -> None:
    failure = RuntimeError(SECRET)
    api.authentication.engine.dispose.side_effect = failure
    events = Mock()
    events.attach_mock(api.authentication.engine.dispose, "authentication")
    events.attach_mock(api.database.engine.dispose, "runtime")
    with pytest.raises(RuntimeError) as caught:
        with api_module.service_api(api.config, api.provider) as application:
            client = APIClient(application, "https://app.example.test")
            assert client.get("/readyz").status_code == 200
    assert caught.value is failure
    assert events.mock_calls == [call.authentication(), call.runtime()]
    api.database.transaction.reset_mock()
    api.authentication.transaction.reset_mock()
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"detail": "Test runtime is closed"}
    api.database.transaction.assert_not_called()
    api.authentication.transaction.assert_not_called()


@pytest.mark.parametrize("exitcode", [1, 7, "unclassified"])
def test_cli_preserves_worker_failure_status_and_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    exitcode: object,
) -> None:
    path = tmp_path / "synthetic-worker.json"
    path.write_text(configuration().model_dump_json())
    worker = Mock()
    controller = worker.application.Worker.return_value
    controller.exitcode = exitcode
    monkeypatch.setattr(worker_module, "ServiceWorker", Mock(return_value=worker))
    monkeypatch.setattr(sys, "argv", ["service", "worker", "--config", str(path)])
    assert entrypoint.main() == 1
    controller.start.assert_called_once_with()
    controller.stop.assert_called_once_with()
    worker.close.assert_called_once_with()
    assert capsys.readouterr() == ("", "service_runtime_failed\n")


def test_cli_controller_stop_failure_still_closes_database_application(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "synthetic-worker.json"
    path.write_text(configuration().model_dump_json())
    worker = Mock()
    controller = worker.application.Worker.return_value
    controller.exitcode = 0
    controller.stop.side_effect = RuntimeError(SECRET)
    monkeypatch.setattr(worker_module, "ServiceWorker", Mock(return_value=worker))
    monkeypatch.setattr(sys, "argv", ["service", "worker", "--config", str(path)])
    assert entrypoint.main() == 1
    worker.close.assert_called_once_with()
    assert capsys.readouterr() == ("", "service_runtime_cleanup_failed\n")


def test_cli_actual_celery_controller_keeps_fixed_failure_streams(tmp_path: Path) -> None:
    import subprocess

    path = tmp_path / "synthetic-worker.json"
    path.write_text(configuration().model_dump_json())
    source = """
import socket, sys
sys.path.insert(0,sys.argv[2])
from types import SimpleNamespace
from emailmonitor.runtime import entrypoint
from emailmonitor.runtime.worker import broker_application
from emailmonitor.runtime import worker as worker_module
config = entrypoint.load_config(__import__('pathlib').Path(sys.argv[1]))
app = broker_application(config)
original = app.Worker
streams = (sys.stdout, sys.stderr)
def forbidden(*args, **kwargs):
    raise AssertionError('No connection permitted in pure controller probe')
socket.socket.connect = forbidden
socket.create_connection = forbidden
def controller(**options):
    value = original(**options)
    value.on_start()
    assert (sys.stdout, sys.stderr) == streams
    assert value.quiet and not value.redirect_stdouts
    def fail(*args, **kwargs):
        raise SystemExit(7)
    value.blueprint.start = fail
    return value
app.Worker = controller
worker_module.ServiceWorker = lambda supplied: SimpleNamespace(application=app,close=app.close)
sys.argv = ['service','worker','--config',sys.argv[1]]
assert entrypoint.main() == 1
assert (sys.stdout, sys.stderr) == streams
"""
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            source,
            str(path),
            str(Path(worker_module.__file__).resolve().parents[2]),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr.endswith("service_runtime_failed\n")
    assert SECRET not in result.stdout + result.stderr

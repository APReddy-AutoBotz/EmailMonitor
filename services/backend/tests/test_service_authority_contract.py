"""Service scope is closed metadata, never a human token or grant credential."""

import ast
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from emailmonitor.runtime.authority import (
    MAX_WORK_SECONDS,
    ServiceProcess,
    ServiceWork,
    WorkLifetime,
)
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError


@pytest.mark.parametrize("seconds", [0, -1, 21_601, True, "21600", 21_600.0])
def test_work_lifetime_refuses_unbounded_or_coerced_duration(seconds: object) -> None:
    with pytest.raises(ValidationError):
        WorkLifetime.model_validate({"seconds": seconds})


def test_lifetime_intersects_bounds_and_does_not_extend_prior_authority() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    source = start + timedelta(hours=24)
    resource = start + timedelta(days=90)
    lifetime = WorkLifetime()
    initial = lifetime.deadline(start, source_expires_at=source, resource_expires_at=resource)
    assert initial == start + timedelta(seconds=MAX_WORK_SECONDS)
    assert (
        lifetime.deadline(
            start + timedelta(hours=1),
            source_expires_at=source,
            resource_expires_at=resource,
            prior_deadline=initial,
        )
        == initial
    )
    assert lifetime.deadline(
        start,
        source_expires_at=start + timedelta(minutes=5),
        resource_expires_at=resource,
    ) == start + timedelta(minutes=5)
    assert lifetime.deadline(
        start, source_expires_at=source, resource_expires_at=start + timedelta(minutes=2)
    ) == start + timedelta(minutes=2)
    assert WorkLifetime(seconds=60).deadline(
        start, source_expires_at=source, resource_expires_at=resource
    ) == start + timedelta(seconds=60)


def test_lifetime_refuses_naive_or_exhausted_times() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for source in (start.replace(tzinfo=None), start, start - timedelta(seconds=1)):
        with pytest.raises(ValueError):
            WorkLifetime().deadline(
                start, source_expires_at=source, resource_expires_at=start + timedelta(days=1)
            )
    with pytest.raises(ValueError):
        WorkLifetime().deadline(
            start,
            source_expires_at=start + timedelta(days=1),
            resource_expires_at=start + timedelta(days=1),
            prior_deadline=start,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_token", "synthetic-browser-token"),
        ("session_hash", "a" * 64),
        ("requester", uuid4()),
        ("role", "owner"),
        ("grant", uuid4()),
        ("purpose", "retention"),
        ("generation", True),
        ("generation", 0),
    ],
)
def test_service_work_cannot_supply_authentication_or_widen_purpose(
    field: str, value: object
) -> None:
    body = dict(organization=uuid4(), resource=uuid4(), purpose="extraction", generation=1)
    body[field] = value
    with pytest.raises(ValidationError):
        ServiceWork.model_validate(body)


@pytest.mark.parametrize("purpose", ["extraction", "export"])
def test_service_work_is_frozen_identifier_scope(purpose: str) -> None:
    work = ServiceWork.model_validate(
        dict(organization=uuid4(), resource=uuid4(), purpose=purpose, generation=1)
    )
    assert work.purpose == purpose
    with pytest.raises(ValidationError):
        work.generation = 2


@pytest.mark.parametrize(
    "override",
    [
        {"principal": UUID(int=0)},
        {"kind": "owner"},
        {"work_seconds": 21_601},
        {"pass_limit": 101},
        {"session_token": "synthetic-browser-token"},
        {"role": "emailmonitor_owner"},
    ],
)
def test_service_process_requires_bounded_closed_configuration(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ServiceProcess.model_validate(dict(kind="worker", principal=uuid4()) | override)


def test_service_binding_is_closed_and_unique() -> None:
    from uuid import uuid4

    from emailmonitor.runtime.delegation import ServiceBinding, ServiceBindings

    org, worker, publisher = uuid4(), uuid4(), uuid4()
    binding = ServiceBinding(organization=org, worker=worker, publisher=publisher)
    assert binding.seconds == 21600
    with pytest.raises(ValueError):
        ServiceBinding(organization=org, worker=worker, publisher=worker)
    with pytest.raises(ValueError):
        ServiceBindings(tenants=(binding, binding))


def test_service_worker_apps_do_not_share_principals(monkeypatch: pytest.MonkeyPatch) -> None:
    from uuid import uuid4

    from emailmonitor.runtime import worker
    from emailmonitor.runtime.authority import ServiceProcess

    organization = uuid4()

    class Pool:
        def dispose(self) -> None:
            pass

    class Database:
        def __init__(self, url: str, process: ServiceProcess) -> None:
            self.process = process
            self.engine = Pool()
            self.organization = organization

    monkeypatch.setattr(worker, "ServiceDatabase", Database)

    def configuration() -> worker.ServiceRuntimeConfig:
        return worker.ServiceRuntimeConfig(
            environment="test",
            database_url="postgresql+pg8000://authored:fixture@127.0.0.1:5432/test",
            broker_url="pyamqp://authored:fixture@127.0.0.1:5672/test",
            queue="em-fixture-" + organization.hex,
            organization=organization,
            process=ServiceProcess(kind="worker", principal=uuid4()),
        )

    first, second = worker.ServiceWorker(configuration()), worker.ServiceWorker(configuration())
    try:
        for owned in (first, second):
            for task, method in (("execute", owned.execute), ("export", owned.export)):
                assert owned.application.tasks[f"emailmonitor.service.{task}"].run == method
            assert owned.application.conf.worker_pool == "solo"
            assert owned.application.conf.worker_concurrency == 1
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize(
    "override",
    [
        {"GITHUB_ACTIONS": "false"},
        {"EM_TEST_ADMIN_DATABASE_URL": "postgresql+pg8000://user@database.example.test/live"},
        {"EM_TEST_DATABASE_URL": "postgresql+pg8000://owner@127.0.0.1:5432/postgres"},
    ],
)
def test_service_role_mutation_tests_refuse_non_disposable_targets(
    override: dict[str, str],
) -> None:
    from test_service_authority_tenant import require_service_sql_ci

    environment = {
        "GITHUB_ACTIONS": "true",
        "EM_TEST_ADMIN_DATABASE_URL": "postgresql+pg8000://postgres:emailmonitor-ci-only@127.0.0.1:5432/postgres",
        "EM_TEST_DATABASE_URL": "postgresql+pg8000://em_ci_runtime:emailmonitor-ci-runtime-only@127.0.0.1:5432/postgres",
        "EM_TEST_AUTH_DATABASE_URL": "postgresql+pg8000://em_ci_authenticator:emailmonitor-ci-auth-only@127.0.0.1:5432/postgres",
    }
    require_service_sql_ci(environment)
    with pytest.raises(RuntimeError, match="Exact disposable CI"):
        require_service_sql_ci(environment | override)


def test_work_audit_closed_actions_cover_every_existing_literal_call_site() -> None:
    """Retain compatibility coverage even when actual PostgreSQL tests skip."""
    backend = Path(__file__).resolve().parents[1]
    actions: set[str] = set()
    for path in (backend / "src/emailmonitor").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_audit"
            ):
                assert len(node.args) == 4, path
                action = node.args[3]
                assert isinstance(action, ast.Constant) and isinstance(action.value, str), path
                actions.add(action.value)
    assert actions == {
        "discovery.planned",
        "discovery.page_committed",
        "discovery.delivery.received",
        "extraction.observation_committed",
    }
    migration = (backend / "migrations/versions/0014_service_authority.sql").read_text()
    function = migration.split("CREATE FUNCTION emailmonitor.work_audit(", 1)[1].split(
        "END $$;", 1
    )[0]
    allowlists = re.findall(r"p_action(?: IS NULL OR p_action)? NOT IN \(([^)]+)\)", function)
    assert len(allowlists) == 2
    assert set(re.findall(r"'([^']+)'", allowlists[0])) == actions
    assert set(re.findall(r"'([^']+)'", allowlists[1])) == {
        "discovery.page_committed",
        "extraction.observation_committed",
    }
    service, human = function.split(" ELSE\n", 1)
    assert "service_scope_allowed(p_org,p_resource,'extraction')" in service
    assert "job_permission_fence(p_org,p_resource)" in service
    assert "COALESCE(emailmonitor.execution_write_allowed(p_org,p_resource),false)" in service
    assert "human_work_tenant_allowed(p_org)" in human
    assert "execution_write_allowed" not in human and "job_permission_fence" not in human


def test_publication_busy_defer_is_only_pre_send_extraction_row_contention() -> None:
    migration = (
        Path(__file__).resolve().parents[1] / "migrations/versions/0014_service_authority.sql"
    ).read_text()
    function = migration.split("CREATE FUNCTION emailmonitor.service_publish_event(", 1)[1].split(
        "END $$;", 1
    )[0]
    before, guarded = function.split(" BEGIN\n", 1)
    guarded, after = guarded.split(" END;\n", 1)
    assert "service_authority_fence(p_org,delegation,'publisher')" in before
    assert "privacy_source_state(p_org)" in before
    assert "publication_job_state(p_org,p_resource)" in before
    assert "max_parallel_parse" in before
    assert "FOR SHARE NOWAIT" in guarded and "FOR UPDATE OF o NOWAIT" in guarded
    assert "EXCEPTION WHEN lock_not_available THEN" in guarded
    assert "IF p_confirm IS FALSE THEN RETURN NULL; END IF;\n RAISE;" in guarded
    assert "UPDATE emailmonitor.execution_outbox" in after
    assert "ELSIF p_purpose='export'" in after
    assert "EXCEPTION WHEN" not in before + after


@pytest.mark.parametrize("result", ["deferred", "confirmed", "55P03", "EM017", "XX000"])
def test_service_publisher_defers_null_but_preserves_post_send_failure(
    monkeypatch: pytest.MonkeyPatch, result: str
) -> None:
    from emailmonitor.runtime import service_publisher
    from emailmonitor.runtime.publisher import PublisherError
    from emailmonitor.runtime.worker import ServiceRuntimeConfig

    organization, resource, event, item = uuid4(), uuid4(), uuid4(), uuid4()
    config = ServiceRuntimeConfig(
        environment="test",
        database_url="postgresql+pg8000://authored:fixture@127.0.0.1:5432/test",
        broker_url="pyamqp://authored:fixture@127.0.0.1:5672/test",
        queue="em-fixture-" + organization.hex,
        organization=organization,
        process=ServiceProcess(kind="publisher", principal=uuid4()),
    )
    database = MagicMock()
    database.organization = organization
    pending = database.engine.begin.return_value.__enter__.return_value
    pending.execute.return_value.mappings.return_value.all.return_value = [
        {
            "organization_id": organization,
            "resource_id": resource,
            "purpose": "extraction",
            "generation": 1,
            "event_id": event,
            "item_id": item,
        }
    ]
    work = MagicMock()
    transaction = database.tenant.return_value
    transaction.__enter__.return_value = (work, object())
    first, second = MagicMock(), MagicMock()
    first.scalar_one.return_value = None if result == "deferred" else "fixture_io"
    second.scalar_one.return_value = "fixture_io"
    failure = DBAPIError(
        "synthetic receipt query", {}, Exception({"C": result, "M": "synthetic"}), False
    )
    work.execute.side_effect = [
        first,
        second if result in {"deferred", "confirmed"} else failure,
    ]
    application, connection, channel = MagicMock(), MagicMock(), MagicMock()
    connection.channel.return_value = channel
    monkeypatch.setattr(service_publisher, "ServiceDatabase", lambda *_: database)
    monkeypatch.setattr(service_publisher, "broker_application", lambda _: application)
    monkeypatch.setattr(service_publisher, "Connection", lambda *_, **__: connection)
    monkeypatch.setattr(service_publisher, "Producer", lambda _: object())

    if result in {"deferred", "confirmed"}:
        assert service_publisher.publish_service_once(config) == (result == "confirmed")
        assert transaction.__exit__.call_args.args == (None, None, None)
    else:
        with pytest.raises(PublisherError, match="Service publication failed") as caught:
            service_publisher.publish_service_once(config)
        assert caught.value.__cause__ is None and caught.value.__suppress_context__
        assert transaction.__exit__.call_args.args[:2] == (DBAPIError, failure)
    assert application.send_task.call_count == (0 if result == "deferred" else 1)
    assert work.execute.call_count == (1 if result == "deferred" else 2)
    if result != "deferred":
        assert application.send_task.call_args.kwargs["retry"] is False
    for owned in (application, connection, channel):
        owned.close.assert_called_once_with()
    database.engine.dispose.assert_called_once_with()

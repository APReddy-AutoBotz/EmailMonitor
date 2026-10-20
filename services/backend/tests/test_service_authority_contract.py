"""Service scope is closed metadata, never a human token or grant credential."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from emailmonitor.runtime.authority import (
    MAX_WORK_SECONDS,
    ServiceProcess,
    ServiceWork,
    WorkLifetime,
)
from pydantic import ValidationError


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

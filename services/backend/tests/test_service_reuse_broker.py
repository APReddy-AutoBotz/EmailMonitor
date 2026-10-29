"""Guarded disposable-CI broker crash/redelivery proof for retained reuse."""

from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from test_admission_broker import close_owned
from test_durable_jobs import SETTINGS
from test_real_broker_jobs import wait_for
from test_runtime_publisher_broker import declare_owned
from test_service_authority_tenant import ServiceCase
from test_service_authority_tenant import _service_ci_guard as _service_ci_guard
from test_service_authority_tenant import service_case as service_case
from test_service_reuse_tenant import prepare_service_reuse
from test_service_runtime_broker import installed_worker
from test_service_runtime_broker import publisher_config as publisher_config
from test_tenant_foundation import scenario as scenario

from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.service import Progress
from emailmonitor.runtime.authority import ServiceProcess, ServiceWork
from emailmonitor.runtime.service_publisher import publish_service_once
from emailmonitor.runtime.worker import ServiceRuntimeConfig, broker_application


@pytest.mark.parametrize("service_case", ["html", "pdf", "article_xml", "provider"], indirect=True)
def test_reused_observation_survives_worker_crash_and_original_redelivery(
    service_case: ServiceCase,
    publisher_config: ServiceRuntimeConfig,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    case, config = service_case, publisher_config
    org = case.scope.organization
    route = request.node.callspec.params["service_case"]  # type: ignore[attr-defined]
    target, source_batch = prepare_service_reuse(case, route)
    with case.progress.database.tenant(case.progress.token, org, Capability.ACQUIRE_SOURCE) as (
        c,
        _,
    ):
        c.execute(
            text(
                "SELECT emailmonitor.delegate_service_work(:org,:principal,:job,'extraction',21600)"
            ),
            {"org": org, "principal": config.process.principal, "job": target},
        )
    worker_config = ServiceRuntimeConfig.model_validate(
        {
            **config.model_dump(),
            "database_url": case.url,
            "lease_seconds": 30,
            "process": ServiceProcess(kind="worker", principal=case.principal),
        }
    )
    application = broker_application(config)
    params = {"org": org, "job": target}
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
                        "WHERE organization_id=:org AND job_id=:job "
                        "AND reused_source_batch=:batch"
                    ),
                    {**params, "batch": source_batch},
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

            def redelivered() -> bool:
                assert resumed.poll() is None
                with case.admin.connect() as c:
                    return bool(
                        c.execute(
                            text(
                                "SELECT o.deliveries>=2 AND i.lease_until>clock_timestamp() "
                                "FROM emailmonitor.execution_outbox o "
                                "JOIN emailmonitor.execution_items i "
                                "ON i.organization_id=o.organization_id AND i.job_id=o.job_id "
                                "AND i.id=o.item_id "
                                "WHERE o.organization_id=:org AND o.job_id=:job AND o.item_id=:item"
                            ),
                            {**params, "item": item},
                        ).scalar_one()
                    )

            wait_for(redelivered, seconds=15)

            def completed() -> bool:
                assert resumed.poll() is None
                publish_service_once(config)
                with case.admin.connect() as c:
                    return (
                        c.execute(
                            text(
                                "SELECT state FROM emailmonitor.jobs "
                                "WHERE organization_id=:org AND id=:job"
                            ),
                            params,
                        ).scalar_one()
                        == "completed"
                    )

            wait_for(completed, seconds=60)
        scope = ServiceWork(organization=org, resource=target, purpose="extraction", generation=1)
        assert Progress(case.database, scope, SETTINGS).snapshot(org, target).counts.by_outcome == {
            "needs_review": 1
        }
        with case.admin.connect() as c:
            for table in ("article_observations", "association_batches", "execution_effects"):
                assert (
                    c.execute(
                        text(
                            f"SELECT count(*) FROM emailmonitor.{table} "
                            "WHERE organization_id=:org AND job_id=:job"
                        ),
                        params,
                    ).scalar_one()
                    == 1
                )
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.audit_events "
                        "WHERE organization_id=:org AND resource_id=:job "
                        "AND action='extraction.observation_committed'"
                    ),
                    params,
                ).scalar_one()
                == 0
            )
    finally:
        close_owned(application, config.queue)

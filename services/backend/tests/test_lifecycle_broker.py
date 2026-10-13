"""Actual owned RabbitMQ lifecycle tick delivery/replay, disposable synthetic PG only."""

from pathlib import Path
from uuid import uuid4

from emailmonitor.jobs.broker import create_worker
from emailmonitor.lifecycle.broker import publish
from emailmonitor.lifecycle.models import Retention, RetentionUpdate
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.roles import Capability
from sqlalchemy import text
from test_durable_jobs import SETTINGS
from test_real_broker_jobs import config, wait_for, worker
from test_results_tenant import prepared
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def test_real_identifier_tick_purges_once_and_confirms_duplicate_delivery(
    scenario: Scenario, tmp_path: Path
) -> None:
    from emailmonitor.jobs.ledger import Ledger

    results, job = prepared(scenario)
    org = scenario.organizations[0]
    service = Lifecycle(results.database, results.token, SETTINGS)
    old = service.retention(org)
    service.update_retention(
        org, RetentionUpdate(expected_revision=old.revision, retention=Retention(contact_days=0))
    )
    cfg = config(
        scenario,
        Ledger(results.database, results.token, SETTINGS),
        queue="em-fixture-life-" + uuid4().hex,
    )
    app, _ = create_worker(cfg)
    from sqlalchemy import create_engine

    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        assert publish(app, service, org) == 1
        assert publish(app, service, org) == 1
        with worker(cfg, tmp_path):

            def complete() -> bool:
                with results.database.tenant(results.token, org, Capability.READ_ORGANIZATION) as (
                    c,
                    _,
                ):
                    return (
                        c.execute(
                            text("SELECT emailmonitor.lifecycle_schedule(:org,:id)"),
                            {"org": org, "id": uuid4()},
                        ).first()
                        is None
                    )

            wait_for(complete)

            def duplicate_observed() -> bool:
                with admin.connect() as c:
                    return (
                        c.execute(
                            text(
                                "SELECT min(deliveries)>=2 FROM emailmonitor.lifecycle_ticks "
                                "WHERE organization_id=:org"
                            ),
                            {"org": org},
                        ).scalar_one()
                        is True
                    )

            wait_for(duplicate_observed)
        assert service.schedule(org) == ()
        assert service.tick(org) == 0
    finally:
        admin.dispose()
        app.close()

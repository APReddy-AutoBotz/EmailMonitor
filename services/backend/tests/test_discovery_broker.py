"""Real disposable RabbitMQ discovery, replay and worker restart evidence."""

from pathlib import Path
from uuid import UUID

from emailmonitor.discovery.broker import DiscoveryEvent, publish_discovery
from emailmonitor.discovery.state import DiscoveryState
from emailmonitor.jobs.broker import create_worker
from emailmonitor.organizations.roles import Capability
from sqlalchemy import text
from test_discovery_tenant import approved_ledger, begin
from test_real_broker_jobs import config, wait_for, worker
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def test_real_discovery_broker_restart_between_pages_and_duplicate_delivery(
    scenario: Scenario, tmp_path: Path
) -> None:
    discovery, job = begin(scenario)
    org = scenario.organizations[0]
    cfg = config(scenario, approved_ledger(discovery))
    app, _ = create_worker(cfg)
    first = discovery.pending(org)[0]
    event = DiscoveryEvent(
        organization_id=str(org),
        job_id=str(job),
        event_id=str(first["event_id"]),
        generation=1,
        revision=1,
    )
    try:
        with worker(cfg, tmp_path):
            assert publish_discovery(app, discovery, org) == 1
            wait_for(lambda: discovery.read(org, job)["revision"] == 2)
        # New worker process, durable successor selected from PostgreSQL. No
        # in-memory cursor or local file is needed to recover the second page.
        with worker(cfg, tmp_path):
            app.send_task(
                "emailmonitor.fixture.discover",
                args=[event.model_dump()],
                queue=cfg.queue,
                routing_key=cfg.queue,
                retry=False,
            )
            assert publish_discovery(app, discovery, org) == 1
            wait_for(lambda: discovery.read(org, job)["revision"] == 3)
            assert DiscoveryState.model_validate(
                discovery.read(org, job)["checkpoint"]
            ).articles == [
                "https://synthetic.publisher.example/article-a.html",
                "https://synthetic.publisher.example/article-b.html",
                "https://synthetic.publisher.example/tooltip.html",
                "https://synthetic.publisher.example/no-contact.html",
            ]
            with discovery.database.tenant(discovery.token, org, Capability.READ_ORGANIZATION) as (
                c,
                _,
            ):

                def received() -> bool:
                    return (
                        int(
                            c.execute(
                                text("""SELECT count(*) FROM emailmonitor.audit_events
WHERE organization_id=:org AND resource_id=:event AND action='discovery.delivery.received'"""),
                                {"org": org, "event": UUID(event.event_id)},
                            ).scalar_one()
                        )
                        >= 2
                    )

                wait_for(received)
            assert publish_discovery(app, discovery, org) == 0
    finally:
        app.close()

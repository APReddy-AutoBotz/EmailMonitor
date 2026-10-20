"""Finite identifier-only publisher with owned connection and current SQL fences."""

import time
from typing import Literal, cast
from uuid import UUID

from kombu import Connection, Producer
from sqlalchemy import text

from emailmonitor.jobs.queues import phase_queue
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.broker import ExecutionEvent
from emailmonitor.results.broker import ExportEvent
from emailmonitor.runtime.authority import ServiceWork
from emailmonitor.runtime.database import ServiceDatabase
from emailmonitor.runtime.publisher import PublisherCleanupError, PublisherError
from emailmonitor.runtime.worker import ServiceRuntimeConfig, broker_application


def publish_service_once(config: ServiceRuntimeConfig) -> int:
    if config.process.kind != "publisher":
        raise ValueError("Publisher principal required")
    database = ServiceDatabase(config.database_url, config.process)
    application = connection = channel = None
    failed = False
    count = 0
    started = time.monotonic()
    try:
        if database.organization != config.organization:
            raise ValueError("Registered service tenant must match queue tenant")
        application = broker_application(config)
        with database.engine.begin() as c:
            c.execute(
                text(
                    "SELECT set_config('statement_timeout','2000ms',true), "
                    "set_config('lock_timeout','2000ms',true)"
                )
            )
            rows = (
                c.execute(
                    text("SELECT * FROM emailmonitor.service_pending(:principal,:limit)"),
                    {"principal": config.process.principal, "limit": config.process.pass_limit},
                )
                .mappings()
                .all()
            )
        if not rows:
            return 0
        connection = Connection(
            config.broker_url,
            connect_timeout=3,
            transport_options={"confirm_publish": True, "read_timeout": 3, "write_timeout": 3},
        )
        connection.ensure_connection(max_retries=0)
        channel = connection.channel()
        producer = Producer(channel)
        for row in rows:
            if time.monotonic() - started >= 10:
                break
            scope = ServiceWork(
                organization=row["organization_id"],
                resource=row["resource_id"],
                purpose=row["purpose"],
                generation=row["generation"],
            )
            event_id: UUID = row["event_id"]
            item_id: UUID | None = row["item_id"]
            if scope.purpose == "extraction":
                if item_id is None:
                    raise ValueError("Execution item required")
                body = ExecutionEvent(
                    organization_id=str(scope.organization),
                    job_id=str(scope.resource),
                    event_id=str(event_id),
                    item_id=str(item_id),
                    generation=scope.generation,
                ).model_dump()
                name = "emailmonitor.service.execute"
            else:
                body = ExportEvent(
                    organization_id=str(scope.organization),
                    export_id=str(scope.resource),
                    event_id=str(event_id),
                    generation=scope.generation,
                ).model_dump()
                name = "emailmonitor.service.export"
            params = {
                "org": scope.organization,
                "resource": scope.resource,
                "purpose": scope.purpose,
                "generation": scope.generation,
                "event": event_id,
                "item": item_id,
                "confirm": False,
            }
            statement = text(
                "SELECT emailmonitor.service_publish_event("
                ":org,:resource,:purpose,:generation,:event,:item,:confirm)"
            )
            capability = (
                Capability.ACQUIRE_SOURCE
                if scope.purpose == "extraction"
                else Capability.EXPORT_RESULTS
            )
            with database.tenant(scope, scope.organization, capability) as (c, _):
                phase: str | None = c.execute(statement, params).scalar_one()
                if phase is None:
                    continue
                if phase not in {"fixture_io", "parse", "export"}:
                    raise ValueError("Closed publication phase required")
                queue = phase_queue(
                    config.queue, cast(Literal["fixture_io", "parse", "export"], phase)
                )
                application.send_task(
                    name,
                    args=[body],
                    queue=queue,
                    routing_key=queue,
                    delivery_mode=2,
                    mandatory=True,
                    retry=False,
                    producer=producer,
                    timeout=3,
                    confirm_timeout=3,
                    ignore_result=True,
                    serializer="json",
                    exchange="",
                )
                # A crash after broker confirmation but before this commit permits
                # duplicate delivery. Claim/effect idempotency remains in SQL.
                params["confirm"] = True
                if c.execute(statement, params).scalar_one() != phase:
                    raise PublisherError("Publication receipt changed")
            count += 1
        return count
    except Exception:
        failed = True
        raise PublisherError("Service publication failed") from None
    except BaseException:
        failed = True
        raise
    finally:
        cleanup_failed = False
        for resource in (channel, connection, application):
            if resource is not None:
                try:
                    resource.close()
                except BaseException:
                    cleanup_failed = True
        try:
            database.engine.dispose()
        except BaseException:
            cleanup_failed = True
        if cleanup_failed and not failed:
            raise PublisherCleanupError("Service publication cleanup failed") from None

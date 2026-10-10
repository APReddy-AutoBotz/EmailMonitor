"""Synthetic loopback broker harness. This is not a production worker identity design."""

import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from celery import Celery
from kombu import Exchange, Queue
from pydantic import Field, model_validator

from emailmonitor.config import Settings
from emailmonitor.jobs.ledger import Ledger, Work
from emailmonitor.jobs.models import StrictModel
from emailmonitor.organizations.database import Database


class FixtureWorkerConfig(StrictModel):
    environment: str
    database_url: str
    broker_url: str
    organization: str
    session_token: str = Field(min_length=16, max_length=200)
    queue: str = Field(pattern=r"^em-fixture-[a-z0-9-]{1,60}$")
    lease_seconds: int = Field(default=30, ge=1, le=300)
    diagnostic_delay_seconds: int = Field(default=0, ge=0, le=30)
    exit_after_commit: bool = False

    @model_validator(mode="after")
    def synthetic_boundary(self) -> "FixtureWorkerConfig":
        if self.environment != "test":
            raise ValueError("Worker is unavailable outside explicit synthetic test mode")
        for url, scheme in ((self.database_url, "postgresql+pg8000"), (self.broker_url, "pyamqp")):
            parsed = urlsplit(url)
            if (
                parsed.scheme != scheme
                or parsed.hostname != "127.0.0.1"
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Disposable loopback dependencies required")
        UUID(self.organization)
        return self


def create_worker(config: FixtureWorkerConfig) -> tuple[Any, Ledger]:
    """No global tenant grant: every transaction resolves the current configured test session."""
    ledger = Ledger(
        Database(config.database_url),
        config.session_token,
        Settings(environment="test", fixture_mode=True),
    )
    application = Celery("emailmonitor_fixture", broker=config.broker_url, backend=None)
    application.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_ignore_result=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_default_queue=config.queue,
        task_default_exchange=config.queue,
        task_default_routing_key=config.queue,
        worker_detect_quorum_queues=True,
        task_queues=(
            Queue(
                config.queue,
                Exchange(config.queue, type="direct", durable=True),
                routing_key=config.queue,
                durable=True,
                queue_arguments={"x-queue-type": "quorum"},
            ),
        ),
        task_default_delivery_mode="persistent",
        task_create_missing_queues=False,
        broker_transport_options={"confirm_publish": True},
        broker_connection_timeout=3,
        broker_connection_retry_on_startup=False,
        task_publish_retry=False,
        worker_enable_remote_control=False,
        worker_send_task_events=False,
        worker_hijack_root_logger=False,
    )

    def persist(body: dict[str, object]) -> None:
        work = Work.parse(body)
        if str(work.organization) != config.organization:
            raise ValueError("Unexpected diagnostic organization")
        lease = ledger.claim(work, config.lease_seconds)
        if lease is None:
            return
        if config.diagnostic_delay_seconds:
            time.sleep(config.diagnostic_delay_seconds)
        committed = ledger.commit(lease)
        if committed and config.exit_after_commit:
            # Explicit disposable fixture failure injection, unavailable in production.
            os._exit(73)

    application.task(name="emailmonitor.fixture.persist", typing=False)(persist)
    return application, ledger


def publish(application: Any, ledger: Ledger, organization: UUID) -> int:
    """Confirm broker acceptance before marking outbox; uncertain delivery can be replayed."""
    count = 0
    for work in ledger.outbox(organization):
        application.send_task(
            "emailmonitor.fixture.persist",
            args=[ledger.envelope(work)],
            queue=application.conf.task_default_queue,
            routing_key=application.conf.task_default_queue,
            delivery_mode=2,
            mandatory=True,
            retry=False,
        )
        ledger.confirmed(work)
        count += 1
    return count


def from_environment() -> Any:
    if os.environ.get("EM_FIXTURE_WORKER") != "true":
        raise ValueError("Synthetic worker harness must be explicitly selected")
    config = FixtureWorkerConfig.model_validate_json(
        Path(os.environ["EM_FIXTURE_WORKER_CONFIG"]).read_text()
    )
    return create_worker(config)[0]

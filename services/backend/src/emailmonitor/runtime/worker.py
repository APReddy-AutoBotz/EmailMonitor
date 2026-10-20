"""Independent service-login worker for the bounded authored-source runtime.

Only identifier events enter tasks. Each event obtains a fresh SQL delegation and
lease; no caller-supplied role, browser session or executor selector is accepted.
"""

import time
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from celery import Celery, bootsteps
from kombu import Exchange, Queue
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from emailmonitor.config import Settings
from emailmonitor.jobs.callback_wake import FixtureCallbackWake
from emailmonitor.jobs.queues import owned_queues
from emailmonitor.progress.broker import ExecutionEvent
from emailmonitor.progress.broker import process as execute
from emailmonitor.progress.execution import ExecutionDispatcher
from emailmonitor.progress.service import Progress
from emailmonitor.results.broker import ExportEvent
from emailmonitor.results.broker import process as export
from emailmonitor.results.service import Results
from emailmonitor.runtime.assembly import _database_target
from emailmonitor.runtime.authority import ServiceProcess, ServiceWork
from emailmonitor.runtime.database import ServiceDatabase
from emailmonitor.runtime.publisher import TestPublisherConfig
from emailmonitor.runtime.signal_wake import SignalWakeState, register_signal_wake

if TYPE_CHECKING:
    from emailmonitor.runtime.controlled_channel import ControlledChannel


class ServiceRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    environment: Literal["test"]
    database_url: str = Field(repr=False)
    broker_url: str = Field(repr=False)
    queue: str
    organization: UUID
    process: ServiceProcess
    lease_seconds: int = Field(default=30, ge=1, le=120)
    profile: Literal["authored-html-service-reference", "controlled-xml-service-reference"] = (
        "authored-html-service-reference"
    )

    @model_validator(mode="after")
    def isolated(self) -> "ServiceRuntimeConfig":
        if self.queue != "em-fixture-" + self.organization.hex:
            raise ValueError("Tenant-isolated queue namespace required")
        _database_target(self.database_url)
        TestPublisherConfig(
            environment=self.environment, broker_url=self.broker_url, queue=self.queue
        )
        return self


def broker_application(config: ServiceRuntimeConfig) -> Any:
    application = Celery("emailmonitor_service", broker=config.broker_url, backend=None)
    application.steps["consumer"].add(FixtureCallbackWake)
    application.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_ignore_result=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        worker_pool="solo",
        worker_concurrency=1,
        task_default_queue=config.queue,
        task_default_exchange=config.queue,
        task_default_routing_key=config.queue,
        worker_detect_quorum_queues=True,
        task_queues=tuple(
            Queue(
                name,
                Exchange(name, type="direct", durable=True),
                routing_key=name,
                durable=True,
                queue_arguments={"x-queue-type": "quorum"},
            )
            for name in owned_queues(config.queue)
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
    return application


class ServiceWorker:
    """Own one pool and one application; caller quiesces tasks before close."""

    channel: "ControlledChannel | None" = None

    def __init__(
        self, config: ServiceRuntimeConfig, *, controlled_channel: "ControlledChannel | None" = None
    ) -> None:
        if config.process.kind != "worker":
            raise ValueError("Worker principal required")
        if (config.profile == "controlled-xml-service-reference") != (
            controlled_channel is not None
        ):
            raise ValueError("Explicit controlled profile and owned capability must agree")
        self.channel = controlled_channel
        self.config = config
        self.signal_wake = SignalWakeState()
        try:
            self.database = ServiceDatabase(config.database_url, config.process)
            self._initialize(config)
        except BaseException:
            try:
                if hasattr(self, "application"):
                    self.application.close()
            finally:
                try:
                    if hasattr(self, "database"):
                        self.database.engine.dispose()
                finally:
                    if self.channel is not None:
                        self.channel.close()
            raise

    def _initialize(self, config: ServiceRuntimeConfig) -> None:
        if self.database.organization != config.organization:
            raise ValueError("Registered service tenant must match queue tenant")
        self.application = broker_application(config)
        self.closed = False
        self.cursor: tuple[str, UUID] | None = None
        self.reconcile_errors = 0
        self.settings = Settings(environment="test", fixture_mode=True)
        self.application.task(name="emailmonitor.service.execute", shared=False, typing=False)(
            self.execute
        )
        self.application.task(name="emailmonitor.service.export", shared=False, typing=False)(
            self.export
        )
        owner = self

        class ReconcileStep(bootsteps.StartStopStep):  # type: ignore[misc]
            requires = ("celery.worker.consumer.tasks:Tasks",)

            def __init__(self, consumer: Any, **kwargs: Any) -> None:
                super().__init__(consumer, **kwargs)
                self.timer: Any = None

            def start(self, consumer: Any) -> None:
                self.timer = consumer.timer.call_repeatedly(5.0, owner.reconcile_safe)

            def stop(self, consumer: Any) -> None:
                if self.timer is not None:
                    self.timer.cancel()
                    self.timer = None

            shutdown = stop
            terminate = stop

        self.application.steps["consumer"].add(ReconcileStep)
        register_signal_wake(self.application, self.signal_wake)

    def reconcile_safe(self) -> None:
        try:
            self.reconcile()
        except Exception:
            # Fixed local count only; a later bounded pass retries current work.
            self.reconcile_errors += 1

    def reconcile(self) -> int:
        if self.closed:
            raise RuntimeError("Worker closed")
        started = time.monotonic()
        with self.database.engine.begin() as c:
            c.execute(
                text(
                    "SELECT set_config('statement_timeout','2000ms',true), "
                    "set_config('lock_timeout','2000ms',true)"
                )
            )
            rows = (
                c.execute(
                    text(
                        "SELECT * FROM emailmonitor.service_worklist("
                        ":principal,:purpose,:resource,:limit)"
                    ),
                    {
                        "principal": self.config.process.principal,
                        "purpose": self.cursor[0] if self.cursor else None,
                        "resource": self.cursor[1] if self.cursor else None,
                        "limit": self.config.process.pass_limit,
                    },
                )
                .mappings()
                .all()
            )
        count = 0
        exhausted = False
        for row in rows:
            if time.monotonic() - started >= 10:
                exhausted = True
                break
            scope = ServiceWork(
                organization=row["organization_id"],
                resource=row["resource_id"],
                purpose=row["purpose"],
                generation=row["generation"],
            )
            try:
                if scope.purpose == "extraction":
                    Progress(self.database, scope, self.settings).reconcile(
                        scope.organization,
                        scope.resource,
                    )
                else:
                    Results(self.database, scope, self.settings).reconcile(
                        scope.organization,
                        scope.resource,
                    )
                count += 1
            except Exception:
                self.reconcile_errors += 1
            self.cursor = (scope.purpose, scope.resource)
        if not exhausted and len(rows) < self.config.process.pass_limit:
            self.cursor = None
        return count

    def execute(self, body: dict[str, object]) -> bool:
        if self.closed:
            raise RuntimeError("Worker closed")
        event = ExecutionEvent.model_validate(body)
        if event.organization_id != str(self.config.organization):
            raise ValueError("Unexpected service tenant")
        scope = ServiceWork(
            organization=UUID(event.organization_id),
            resource=UUID(event.job_id),
            generation=event.generation,
            purpose="extraction",
        )
        return execute(
            Progress(self.database, scope, self.settings),
            scope.organization,
            event.model_dump(),
            seconds=self.config.lease_seconds,
            executor_factory=self.executor,
        )

    def executor(self, progress: Progress) -> ExecutionDispatcher:
        if self.channel is None:
            return ExecutionDispatcher(progress)
        return ExecutionDispatcher(progress, self.channel, parser=self.channel.parse)

    def export(self, body: dict[str, object]) -> bool:
        if self.closed:
            raise RuntimeError("Worker closed")
        event = ExportEvent.model_validate(body)
        if event.organization_id != str(self.config.organization):
            raise ValueError("Unexpected service tenant")
        scope = ServiceWork(
            organization=UUID(event.organization_id),
            resource=UUID(event.export_id),
            generation=event.generation,
            purpose="export",
        )
        return export(
            Results(self.database, scope, self.settings),
            scope.organization,
            event.model_dump(),
            seconds=self.config.lease_seconds,
        )

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                self.signal_wake.close()
            finally:
                try:
                    self.application.close()
                finally:
                    try:
                        self.database.engine.dispose()
                    finally:
                        if self.channel is not None:
                            self.channel.close()

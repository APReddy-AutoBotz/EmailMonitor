"""Finite test publication on an explicitly owned, non-pooled AMQP connection.

SQL remains the authority. This uses explicit connection, publish and confirmation
timeouts, not a whole-batch, channel-operation or SQL deadline. It does not drain
workers or stop global pools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from celery.backends.base import DisabledBackend  # type: ignore[import-untyped]
from kombu import Connection, Producer

from emailmonitor.config import Settings
from emailmonitor.jobs.queues import owned_queues, phase_queue
from emailmonitor.progress.broker import publish as publish_execution
from emailmonitor.progress.service import Progress
from emailmonitor.results.broker import publish as publish_exports
from emailmonitor.results.service import Results

_TIMEOUT = 3


class PublisherError(RuntimeError):
    """Fixed public failure category; never includes broker or SQL details."""


class PublisherCleanupError(RuntimeError):
    """Every acquired resource was offered cleanup; one or more failed."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TestPublisherConfig:
    """Trusted Python configuration for an already provisioned disposable broker."""

    environment: str
    broker_url: str = field(repr=False)
    queue: str

    def __post_init__(self) -> None:
        try:
            if type(self.environment) is not str or self.environment != "test":
                raise ValueError
            value = self.broker_url
            if type(value) is not str or any(c.isspace() for c in value):
                raise ValueError
            parsed = urlsplit(value)
            if (
                parsed.scheme != "pyamqp"
                or parsed.hostname != "127.0.0.1"
                or parsed.port is None
                or not 1 <= parsed.port <= 65535
                or not parsed.username
                or not parsed.password
                or not parsed.path.removeprefix("/")
                or any(c in value for c in "?#;")
                or parsed.netloc.count("@") != 1
                or type(self.queue) is not str
            ):
                raise ValueError
            owned_queues(self.queue)
        except Exception:
            raise ValueError(
                "Explicit disposable loopback test publisher configuration required"
            ) from None


@dataclass(frozen=True, slots=True)
class PublishCounts:
    execution: int
    exports: int


def _validate_scope(
    config: TestPublisherConfig,
    application: Any,
    progress: Progress,
    results: Results,
    organization: UUID,
) -> None:
    try:
        if type(organization) is not UUID:
            raise ValueError
        for service, expected in ((progress, Progress), (results, Results)):
            if not isinstance(service, expected) or type(service.settings) is not Settings:
                raise ValueError
            settings = Settings.model_validate(service.settings.model_dump(warnings="error"))
            if settings.environment != "test" or settings.fixture_mode is not True:
                raise ValueError
        if (
            progress.settings != results.settings
            or progress.database is not results.database
            or type(progress.token) is not str
            or not progress.token
            or progress.token != results.token
        ):
            raise ValueError
        conf = application.conf
        # AsyncResult resolves app.backend even when publication ignores results.
        # Inspect the cached backend only: validation must not initialize a backend
        # (some backend constructors can create tables or open another transport).
        if (
            conf.result_backend is not None
            or application.backend_cls is not None
            or (
                application._backend is not None
                and type(application._backend) is not DisabledBackend
            )
        ):
            raise ValueError
        if (
            conf.broker_url != config.broker_url
            or (conf.broker_write_url or conf.broker_url) != config.broker_url
            or conf.task_default_queue != config.queue
            or conf.task_serializer != "json"
            or set(conf.accept_content) != {"json"}
            or conf.task_create_missing_queues is not False
            or conf.broker_transport_options.get("confirm_publish") is not True
        ):
            raise ValueError
        # Celery caches routing independently of conf; inspect the effective
        # declarations too, without replacing or mutating borrowed application state.
        if conf.task_routes or application.amqp.router.routes:
            raise ValueError
        for declarations in (
            tuple(conf.task_queues),
            tuple(application.amqp.queues.values()),
            tuple(application.amqp.router.queues.values()),
        ):
            if {q.name for q in declarations} != set(owned_queues(config.queue)):
                raise ValueError
            if len(declarations) != len(owned_queues(config.queue)):
                raise ValueError
            for queue in declarations:
                if (
                    queue.durable is not True
                    or queue.auto_delete
                    or queue.exclusive
                    or queue.queue_arguments != {"x-queue-type": "quorum"}
                    or queue.routing_key != queue.name
                    or queue.exchange.name != queue.name
                    or queue.exchange.type != "direct"
                    or queue.exchange.durable is not True
                    or queue.exchange.auto_delete
                ):
                    raise ValueError
    except Exception:
        raise ValueError("Matching test publisher application and service scope required") from None


class _Publisher:
    """Private adapter, valid only during the owner's single publication pass."""

    def __init__(self, application: Any, producer: Any, namespace: str) -> None:
        self.conf = application.conf
        self._application = application
        self._producer = producer
        self._namespace = namespace
        self.active = True

    def send_task(self, name: str, **options: Any) -> Any:
        routes = {
            "emailmonitor.fixture.execute": {
                phase_queue(self._namespace, "fixture_io"),
                phase_queue(self._namespace, "parse"),
            },
            "emailmonitor.fixture.export": {phase_queue(self._namespace, "export")},
        }
        if (
            not self.active
            or name not in routes
            or options.get("queue") not in routes[name]
            or options.get("routing_key") != options.get("queue")
            or options.get("delivery_mode") != 2
            or options.get("mandatory") is not True
            or options.get("retry") is not False
            or set(options)
            != {"args", "queue", "routing_key", "delivery_mode", "mandatory", "retry"}
        ):
            raise PublisherError("Owned test publication scope refused")
        return self._application.send_task(
            name,
            **options,
            producer=self._producer,
            timeout=_TIMEOUT,
            confirm_timeout=_TIMEOUT,
            ignore_result=True,
            serializer="json",
            exchange="",
        )


def publish_once(
    config: TestPublisherConfig,
    application: Any,
    progress: Progress,
    results: Results,
    organization: UUID,
) -> PublishCounts:
    """Publish each existing bounded outbox once, then close channel and connection.

    Celery may access producer-pool metadata and a lazy acquire callback. Passing
    the concrete producer prevents an actual pooled acquisition. Confirmed SQL
    writes are unchanged: a publish/confirmation failure leaves replay possible.
    """
    if type(config) is not TestPublisherConfig:
        raise ValueError("Trusted Python test publisher configuration required")
    validated = TestPublisherConfig(
        environment=config.environment,
        broker_url=config.broker_url,
        queue=config.queue,
    )
    _validate_scope(validated, application, progress, results, organization)
    connection = channel = adapter = None
    primary_error: BaseException | None = None
    cleanup_failed = False
    stage = "connection"
    try:
        connection = Connection(
            validated.broker_url,
            connect_timeout=_TIMEOUT,
            transport_options={
                "confirm_publish": True,
                "read_timeout": _TIMEOUT,
                "write_timeout": _TIMEOUT,
            },
        )
        # No retry for initial establishment. Public channel() may reconnect if
        # the connection has already become locally marked disconnected.
        connection.ensure_connection(max_retries=0)
        channel = connection.channel()
        producer = Producer(channel)
        adapter = _Publisher(application, producer, validated.queue)
        stage = "execution"
        execution = publish_execution(adapter, progress, organization)
        stage = "exports"
        exports = publish_exports(adapter, results, organization)
        return PublishCounts(execution, exports)
    except Exception:
        error = PublisherError(f"Owned test publisher {stage} failed")
        primary_error = error
        raise error from None
    except BaseException as error:
        primary_error = error
        raise
    finally:
        if adapter is not None:
            adapter.active = False
        # Producer.close/release is a no-op; close the actual channel first.
        for resource in (channel, connection):
            if resource is not None:
                try:
                    resource.close()
                except BaseException:
                    cleanup_failed = True
        if cleanup_failed:
            if primary_error is None:
                raise PublisherCleanupError("Owned test publisher cleanup failed") from None
            try:
                BaseException.add_note(primary_error, "Owned test publisher cleanup failed")
            except Exception:
                pass

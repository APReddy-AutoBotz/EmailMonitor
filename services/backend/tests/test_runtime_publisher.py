"""Pure ownership/replay regressions; real SQL/AMQP acceptance is separate."""

import traceback
from collections.abc import Iterator
from dataclasses import FrozenInstanceError, dataclass, field, replace
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from celery import Celery
from celery.backends.base import DisabledBackend  # type: ignore[import-untyped]
from emailmonitor.config import Settings
from emailmonitor.jobs.queues import owned_queues
from emailmonitor.progress.broker import publish as publish_execution
from emailmonitor.progress.service import Progress
from emailmonitor.results.service import Results
from emailmonitor.runtime import publisher as p
from kombu import Exchange, Queue

URL = "pyamqp://synthetic:secret-value@127.0.0.1:5678/test-vhost"
QUEUE = "em-fixture-owned-publisher"
ORG = uuid4()


def config() -> p.TestPublisherConfig:
    return p.TestPublisherConfig(environment="test", broker_url=URL, queue=QUEUE)


def application() -> Any:
    app = Celery("owned_publisher_test", broker=URL, backend=None)
    app.conf.update(
        task_default_queue=QUEUE,
        task_serializer="json",
        accept_content=["json"],
        task_create_missing_queues=False,
        task_ignore_result=True,
        broker_transport_options={"confirm_publish": True},
        task_queues=tuple(
            Queue(
                name,
                Exchange(name, type="direct", durable=True),
                routing_key=name,
                durable=True,
                queue_arguments={"x-queue-type": "quorum"},
            )
            for name in owned_queues(QUEUE)
        ),
    )
    return app


@dataclass
class Harness:
    events: list[str] = field(default_factory=list)
    sent: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    fail: str = ""
    fail_close: set[str] = field(default_factory=set)
    connection_options: dict[str, Any] = field(default_factory=dict)
    producer: Any = None
    connection: Any = None
    channel: Any = None

    def connect(self, url: str, **options: Any) -> Any:
        self.events.append("construct")
        assert url == URL
        self.connection_options = options
        if self.fail == "construct":
            raise RuntimeError(URL)
        owner = self

        class Channel:
            def close(self) -> None:
                owner.events.append("channel.close")
                if "channel" in owner.fail_close:
                    raise RuntimeError(URL)

        class Connection:
            def ensure_connection(self, **kwargs: Any) -> None:
                assert kwargs == {"max_retries": 0}
                owner.events.append("ensure")
                if owner.fail == "ensure":
                    raise RuntimeError(URL)

            def channel(self) -> Any:
                owner.events.append("channel")
                if owner.fail == "channel":
                    raise RuntimeError(URL)
                owner.channel = Channel()
                return owner.channel

            def close(self) -> None:
                owner.events.append("connection.close")
                if "connection" in owner.fail_close:
                    raise RuntimeError(URL)

        self.connection = Connection()
        return self.connection

    def produce(self, channel: Any) -> Any:
        self.events.append("producer")
        assert channel is self.channel
        if self.fail == "producer":
            raise RuntimeError(URL)
        self.producer = object()
        return self.producer

    def send(self, name: str, **options: Any) -> None:
        self.events.append("send")
        assert options["producer"] is self.producer
        assert options["ignore_result"] is True
        assert options["timeout"] == options["confirm_timeout"] == 3
        assert options["mandatory"] is True
        assert options["retry"] is False
        assert options["delivery_mode"] == 2
        if self.fail == "send":
            raise RuntimeError(URL)
        self.sent.append((name, options))


class Outbox:
    def __init__(self, export: bool = False) -> None:
        self.rows: list[dict[str, object]] = [
            {
                "event_id": uuid4(),
                "generation": 1,
                **(
                    {"export_id": uuid4()}
                    if export
                    else {"job_id": uuid4(), "item_id": uuid4(), "work_kind": "discover"}
                ),
            }
        ]
        self.fail_pending = False
        self.fail_confirm = False
        self.confirmations = 0

    def pending(self, org: UUID) -> list[dict[str, object]]:
        assert org == ORG
        if self.fail_pending:
            raise RuntimeError(URL)
        return list(self.rows)

    def confirmed(self, *args: Any) -> None:
        assert args[0] == ORG
        if self.fail_confirm:
            raise RuntimeError(URL)
        self.confirmations += 1
        self.rows.clear()


@pytest.fixture
def setup(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Any, Progress, Results, Harness, Outbox, Outbox]]:
    app = application()
    database = object()
    settings = Settings(environment="test", fixture_mode=True)
    progress = object.__new__(Progress)
    results = object.__new__(Results)
    execution, exports = Outbox(), Outbox(True)
    for service, box in ((progress, execution), (results, exports)):
        service.database = cast(Any, database)
        service.token = "synthetic-token-value"
        service.settings = settings
        monkeypatch.setattr(service, "pending", box.pending)
        monkeypatch.setattr(service, "confirmed", box.confirmed)
    harness = Harness()
    monkeypatch.setattr(p, "Connection", harness.connect)
    monkeypatch.setattr(p, "Producer", harness.produce)
    monkeypatch.setattr(app, "send_task", harness.send)
    yield app, progress, results, harness, execution, exports
    app.close()


@pytest.mark.parametrize(
    "url",
    [
        "pyamqp://u:p@localhost:5678/v",
        "amqp://u:p@127.0.0.1:5678/v",
        "pyamqp://u:p@127.0.0.1/v",
        "pyamqp://u:p@127.0.0.1:0/v",
        "pyamqp://u:p@127.0.0.1:65536/v",
        "pyamqp://u@127.0.0.1:5678/v",
        "pyamqp://:p@127.0.0.1:5678/v",
        "pyamqp://u:p@127.0.0.1:5678/",
        URL + "?",
        URL + "#",
        URL + ";" + URL,
        " " + URL,
        "pyamqp://u:p@127.0.0.1:5678/v\n",
        None,
        [URL],
    ],
)
def test_invalid_url_redacted(url: Any) -> None:
    with pytest.raises(ValueError) as caught:
        p.TestPublisherConfig(environment="test", broker_url=url, queue=QUEUE)
    assert "secret-value" not in str(caught.value)
    assert "secret-value" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    "changes",
    [{"environment": "production"}, {"queue": "celery"}, {"queue": QUEUE + "\n"}, {"queue": 1}],
)
def test_invalid_boundary(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        replace(config(), **changes)


def test_frozen_redacted() -> None:
    value = config()
    assert "secret-value" not in repr(value)
    with pytest.raises(FrozenInstanceError):
        value.queue = "other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        p.PublishCounts(1, 2).execution = 3  # type: ignore[misc]


def test_revalidate_before_io(setup: Any) -> None:
    app, progress, results, h, _, _ = setup
    value = config()
    object.__setattr__(value, "broker_url", "unsafe")
    with pytest.raises(ValueError):
        p.publish_once(value, app, progress, results, ORG)
    assert h.events == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("broker_url", "pyamqp://u:p@127.0.0.1:5678/other"),
        ("broker_write_url", "pyamqp://u:p@127.0.0.1:5678/other"),
        ("task_default_queue", "other"),
        ("task_serializer", "pickle"),
        ("accept_content", ["json", "pickle"]),
        ("task_create_missing_queues", True),
        ("broker_transport_options", {"confirm_publish": False}),
        ("task_queues", ()),
    ],
)
def test_application_refusal_before_io(setup: Any, field: str, value: Any) -> None:
    app, progress, results, h, _, _ = setup
    setattr(app.conf, field, value)
    with pytest.raises(ValueError):
        p.publish_once(config(), app, progress, results, ORG)
    assert h.events == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("durable", False),
        ("exclusive", True),
        ("auto_delete", True),
        ("queue_arguments", {}),
        ("routing_key", "other"),
        ("exchange", Exchange("other", durable=True)),
    ],
)
def test_declaration_refusal(setup: Any, field: str, value: Any) -> None:
    app, progress, results, h, _, _ = setup
    setattr(app.conf.task_queues[1], field, value)
    with pytest.raises(ValueError):
        p.publish_once(config(), app, progress, results, ORG)
    assert h.events == []


@pytest.mark.parametrize(
    "change", ["database", "token", "settings", "forged_settings", "organization"]
)
def test_service_scope_refusal(setup: Any, change: str) -> None:
    app, progress, results, h, _, _ = setup
    org: Any = ORG
    if change == "database":
        results.database = object()
    elif change == "token":
        results.token = "different-token"
    elif change == "settings":
        results.settings = Settings(environment="test", fixture_mode=True, identity_stub=True)
    elif change == "forged_settings":
        results.settings = Settings.model_construct(environment="production", fixture_mode=True)
    else:
        org = str(ORG)
    with pytest.raises(ValueError):
        p.publish_once(config(), app, progress, results, org)
    assert h.events == []


def test_success_and_replay(setup: Any) -> None:
    app, progress, results, h, execution, exports = setup
    assert p.publish_once(config(), app, progress, results, ORG) == p.PublishCounts(1, 1)
    assert h.events[-2:] == ["channel.close", "connection.close"]
    assert h.connection_options == {
        "connect_timeout": 3,
        "transport_options": {"confirm_publish": True, "read_timeout": 3, "write_timeout": 3},
    }
    assert execution.confirmations == exports.confirmations == 1
    assert [name for name, _ in h.sent] == [
        "emailmonitor.fixture.execute",
        "emailmonitor.fixture.export",
    ]
    assert p.publish_once(config(), app, progress, results, ORG) == p.PublishCounts(0, 0)
    assert len(h.sent) == 2


@pytest.mark.parametrize(
    "stage,closed",
    [
        ("construct", []),
        ("ensure", ["connection.close"]),
        ("channel", ["connection.close"]),
        ("producer", ["channel.close", "connection.close"]),
        ("send", ["channel.close", "connection.close"]),
    ],
)
def test_partial_acquisition_failure(setup: Any, stage: str, closed: list[str]) -> None:
    app, progress, results, h, execution, exports = setup
    h.fail = stage
    with pytest.raises(p.PublisherError) as caught:
        p.publish_once(config(), app, progress, results, ORG)
    assert [event for event in h.events if event.endswith(".close")] == closed
    assert execution.confirmations == exports.confirmations == 0
    assert "secret-value" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    "box_name,operation",
    [
        ("execution", "pending"),
        ("execution", "confirm"),
        ("exports", "pending"),
        ("exports", "confirm"),
    ],
)
def test_sql_failure_preserves_replay(setup: Any, box_name: str, operation: str) -> None:
    app, progress, results, h, execution, exports = setup
    box = execution if box_name == "execution" else exports
    setattr(box, "fail_" + operation, True)
    with pytest.raises(p.PublisherError):
        p.publish_once(config(), app, progress, results, ORG)
    assert box.confirmations == 0
    assert box.rows
    assert h.events[-2:] == ["channel.close", "connection.close"]
    setattr(box, "fail_" + operation, False)
    counts = p.publish_once(config(), app, progress, results, ORG)
    assert counts.exports == 1
    assert counts.execution == (1 if box_name == "execution" else 0)
    assert execution.confirmations == exports.confirmations == 1


@pytest.mark.parametrize("primary", [False, True])
def test_cleanup_attempts_both(setup: Any, primary: bool) -> None:
    app, progress, results, h, _, _ = setup
    h.fail_close = {"channel", "connection"}
    h.fail = "send" if primary else ""
    with pytest.raises(p.PublisherError if primary else p.PublisherCleanupError) as caught:
        p.publish_once(config(), app, progress, results, ORG)
    assert h.events[-2:] == ["channel.close", "connection.close"]
    assert "secret-value" not in "".join(traceback.format_exception(caught.value))


def test_real_celery_explicit_producer_without_pool_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = application()
    published: list[dict[str, Any]] = []
    app.conf.task_serializer = "pickle"
    _ = app.amqp.send_task_message  # cache an unsafe default, then restore config
    app.conf.task_serializer = "json"
    from contextlib import nullcontext

    class ExplicitProducer:
        connection = SimpleNamespace(_reraise_as_library_errors=nullcontext)

        def publish(self, body: Any, **kwargs: Any) -> None:
            published.append(kwargs)

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Pooled acquisition or global shutdown")

    # Celery does read this pool's metadata and its lazy acquire callback.
    monkeypatch.setattr(app.producer_pool, "acquire", refuse)
    monkeypatch.setattr(app.backend, "on_task_call", refuse)
    from kombu import pools

    monkeypatch.setattr(pools, "reset", refuse)
    adapter = p._Publisher(app, ExplicitProducer(), QUEUE)
    try:
        adapter.send_task(
            "emailmonitor.fixture.execute",
            args=[{}],
            queue=QUEUE + "-parse",
            routing_key=QUEUE + "-parse",
            delivery_mode=2,
            mandatory=True,
            retry=False,
        )
        assert len(published) == 1
        assert published[0]["serializer"] == "json"
        assert published[0]["exchange"] == ""
        assert published[0]["routing_key"] == QUEUE + "-parse"
        assert published[0]["timeout"] == published[0]["confirm_timeout"] == 3
        assert published[0]["mandatory"] is True and published[0]["retry"] is False
        adapter.active = False
        with pytest.raises(p.PublisherError):
            adapter.send_task("emailmonitor.fixture.execute")
    finally:
        app.close()


def test_environment_broker_override_refused(setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    app, progress, results, h, _, _ = setup
    monkeypatch.setenv("CELERY_BROKER_WRITE_URL", "pyamqp://u:p@127.0.0.1:5678/other")
    with pytest.raises(ValueError):
        p.publish_once(config(), app, progress, results, ORG)
    assert h.events == []


def test_second_send_failure_preserves_first_confirmation(
    setup: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, progress, results, h, execution, exports = setup
    calls = 0

    def send(name: str, **options: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError(URL)
        h.send(name, **options)

    monkeypatch.setattr(app, "send_task", send)
    with pytest.raises(p.PublisherError, match="exports"):
        p.publish_once(config(), app, progress, results, ORG)
    assert execution.confirmations == 1
    assert exports.confirmations == 0
    assert h.events[-2:] == ["channel.close", "connection.close"]
    assert p.publish_once(config(), app, progress, results, ORG) == p.PublishCounts(0, 1)


def test_adapter_invalid_before_cleanup(setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    app, progress, results, h, _, _ = setup
    adapters: list[Any] = []
    original = publish_execution

    def retain(adapter: Any, service: Progress, org: UUID) -> int:
        adapters.append(adapter)
        return original(adapter, service, org)

    monkeypatch.setattr(p, "publish_execution", retain)
    p.publish_once(config(), app, progress, results, ORG)
    assert len(adapters) == 1 and adapters[0].active is False
    with pytest.raises(p.PublisherError):
        adapters[0].send_task(
            "emailmonitor.fixture.execute",
            args=[{}],
            queue=QUEUE + "-parse",
            routing_key=QUEUE + "-parse",
            delivery_mode=2,
            mandatory=True,
            retry=False,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "unrelated.task"},
        {"queue": "other"},
        {"routing_key": "other"},
        {"retry": True},
        {"mandatory": False},
        {"delivery_mode": 1},
        {"producer": object()},
        {"connection": object()},
    ],
)
def test_private_adapter_refuses_scope_expansion(setup: Any, changes: dict[str, Any]) -> None:
    app, _, _, h, _, _ = setup
    adapter = p._Publisher(app, object(), QUEUE)
    options = {
        "name": "emailmonitor.fixture.execute",
        "args": [{}],
        "queue": QUEUE + "-parse",
        "routing_key": QUEUE + "-parse",
        "delivery_mode": 2,
        "mandatory": True,
        "retry": False,
        **changes,
    }
    with pytest.raises(p.PublisherError):
        adapter.send_task(**options)
    assert not h.sent


def test_interrupt_attempts_cleanup(setup: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    app, progress, results, h, execution, exports = setup

    def interrupt(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(app, "send_task", interrupt)
    with pytest.raises(KeyboardInterrupt):
        p.publish_once(config(), app, progress, results, ORG)
    assert h.events[-2:] == ["channel.close", "connection.close"]
    assert execution.confirmations == exports.confirmations == 0


def test_explicit_root_vhost_valid() -> None:
    root = replace(config(), broker_url="pyamqp://synthetic:secret-value@127.0.0.1:5678//")
    assert root.queue == QUEUE


@pytest.mark.parametrize("cached", [False, True])
def test_routes_refused_before_io(setup: Any, cached: bool) -> None:
    app, progress, results, h, _, _ = setup
    if cached:
        app.amqp.router.routes = [{"emailmonitor.fixture.execute": {"exchange": "other"}}]
    else:
        app.conf.task_routes = {"emailmonitor.fixture.execute": {"exchange": "other"}}
    with pytest.raises(ValueError):
        p.publish_once(config(), app, progress, results, ORG)
    assert not h.events


def test_cached_queue_refused_before_io(setup: Any) -> None:
    app, progress, results, h, _, _ = setup
    app.amqp.queues[QUEUE + "-parse"] = Queue(QUEUE + "-parse", durable=False)
    # The public declarations remain valid, while the cached routing copy differs.
    assert app.conf.task_queues[2].durable is True
    with pytest.raises(ValueError):
        p.publish_once(config(), app, progress, results, ORG)
    assert not h.events


@pytest.mark.parametrize("selector", ["config", "environment", "class", "cached"])
def test_result_backend_refused_before_io(
    setup: Any,
    monkeypatch: pytest.MonkeyPatch,
    selector: str,
) -> None:
    app, progress, results, h, _, _ = setup
    if selector == "config":
        app.conf.result_backend = "rpc://"
    elif selector == "environment":
        monkeypatch.setenv("CELERY_RESULT_BACKEND", "rpc://")
    elif selector == "class":
        app.backend_cls = "rpc"
    else:
        app._backend = SimpleNamespace(thread_safe=False)
    with pytest.raises(ValueError):
        p.publish_once(config(), app, progress, results, ORG)
    assert not h.events


def test_cached_disabled_backend_accepted(setup: Any) -> None:
    app, progress, results, _, _, _ = setup
    assert type(app.backend) is DisabledBackend
    assert p.publish_once(config(), app, progress, results, ORG) == p.PublishCounts(1, 1)


def test_disabled_backend_subclass_refused(setup: Any) -> None:
    app, progress, results, h, _, _ = setup

    class CustomBackend(DisabledBackend):  # type: ignore[misc]
        pass

    app._backend = CustomBackend(app=app)
    with pytest.raises(ValueError):
        p.publish_once(config(), app, progress, results, ORG)
    assert not h.events

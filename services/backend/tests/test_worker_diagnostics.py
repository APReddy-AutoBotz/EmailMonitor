"""Pure opt-in fixture diagnostics preserve worker behavior and reveal no task data."""

import json
import multiprocessing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from celery import signals
from emailmonitor.jobs.broker import FixtureWorkerConfig, create_worker
from emailmonitor.jobs.diagnostics import MAX_SNAPSHOTS, PREFIX, STAGES, TASK, WorkerDiagnostics
from emailmonitor.jobs.queues import owned_queues
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.progress.broker import process
from emailmonitor.progress.service import Progress
from operator_ui_protocol import WORKER_PREFIX, WORKER_STAGES, completion_worker_snapshot

ROOT = Path(__file__).resolve().parents[3]
NAMESPACE = "em-fixture-diagnostics"


def body() -> dict[str, object]:
    return {
        "organization_id": str(uuid4()),
        "job_id": str(uuid4()),
        "item_id": str(uuid4()),
        "event_id": str(uuid4()),
        "generation": 1,
    }


@pytest.mark.parametrize("outcome", ["success", "empty", "claim_error", "process_error"])
@pytest.mark.parametrize("enabled", [False, True])
def test_process_stage_observations_preserve_returns_and_exact_errors(
    outcome: str, enabled: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    event = body()
    original = RuntimeError("secret exception content")
    stages: list[Any] = []
    calls: list[Any] = []
    work = SimpleNamespace(lease=SimpleNamespace(generation=1))

    def claim(*args: object) -> object:
        calls.append(args)
        if outcome == "claim_error":
            raise original
        return None if outcome == "empty" else work

    def after() -> None:
        pass

    def fixture(selected: object, hook: object) -> None:
        assert selected is work and hook is after
        if outcome == "process_error":
            raise original

    progress = cast(Progress, SimpleNamespace(claim=claim, process_fixture=fixture))
    arguments = {"diagnostic": stages.append} if enabled else {}
    if outcome.endswith("error"):
        with pytest.raises(RuntimeError) as caught:
            process(
                progress,
                UUID(str(event["organization_id"])),
                event,
                seconds=17,
                after_observation=after,
                **arguments,
            )
        assert caught.value is original
    else:
        assert process(
            progress,
            UUID(str(event["organization_id"])),
            event,
            seconds=17,
            after_observation=after,
            **arguments,
        ) is (outcome == "success")
    assert calls == [
        (
            UUID(str(event["organization_id"])),
            UUID(str(event["job_id"])),
            UUID(str(event["item_id"])),
            UUID(str(event["event_id"])),
            17,
            1,
        )
    ]
    expected = ["validated", "claim_enter"]
    expected += (
        ["claim_empty"]
        if outcome == "empty"
        else ["claim_error"]
        if outcome == "claim_error"
        else ["claim_acquired", "process_enter", outcome.replace("success", "process_return")]
    )
    assert stages == (expected if enabled else [])
    assert capsys.readouterr() == ("", "")


def test_failed_observer_cannot_replace_task_exception_or_empty_return() -> None:
    event = body()
    org = UUID(str(event["organization_id"]))
    original = ValueError("original")

    def broken(_: object) -> None:
        raise RuntimeError("diagnostic failure")

    def claim(*_: object) -> None:
        raise original

    with pytest.raises(ValueError) as caught:
        process(cast(Progress, SimpleNamespace(claim=claim)), org, event, diagnostic=broken)
    assert caught.value is original
    empty = cast(Progress, SimpleNamespace(claim=lambda *_: None))
    assert process(empty, org, event, diagnostic=broken) is False


def test_validation_and_tenant_refusals_do_not_claim_or_emit_validated() -> None:
    stages: list[Any] = []
    event = body()
    with pytest.raises(AuthorizationDenied):
        process(cast(Progress, object()), uuid4(), event, diagnostic=stages.append)
    assert stages == []


class SignalObject:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


def recorder() -> tuple[WorkerDiagnostics, Any, Any, Any, list[str]]:
    output: list[str] = []
    app = SimpleNamespace(tasks={})
    info = {"routing_key": NAMESPACE + "-parse", "exchange": NAMESPACE + "-parse"}
    task = SignalObject(app=app, name=TASK, request=SimpleNamespace(delivery_info=info))
    app.tasks[TASK] = task
    request = SimpleNamespace(app=app, task=task, delivery_info=info)
    consumer = SignalObject(
        app=app,
        task_consumer=SimpleNamespace(
            queues=[SimpleNamespace(name=name) for name in owned_queues(NAMESPACE)]
        ),
    )
    return WorkerDiagnostics(app, NAMESPACE, output.append), task, request, consumer, output


def test_supported_signals_emit_only_closed_cumulative_counters() -> None:
    observer, task, request, consumer, output = recorder()
    observer.connect()
    try:
        signals.worker_ready.send(sender=consumer)
        signals.task_received.send(sender=consumer, request=request)
        observer.record("execute_enter")
        signals.task_failure.send(sender=task, exception=RuntimeError("secret"), args=["secret"])
        signals.task_postrun.send(sender=task, task_id="secret-id", retval="secret")
    finally:
        signals.worker_ready.disconnect(observer.ready)
        signals.task_received.disconnect(observer.received)
        signals.task_failure.disconnect(observer.failure)
        signals.task_postrun.disconnect(observer.postrun)
    snapshot = completion_worker_snapshot("".join(output).encode())
    assert snapshot["status"] == "available" and snapshot["last_stage"] == "task_postrun"
    assert sum(cast(dict[str, int], snapshot["counts"]).values()) == 5
    assert "secret" not in "".join(output) and NAMESPACE not in "".join(output)
    assert "ack" not in "".join(output).lower()


@pytest.mark.parametrize("foreign", ["app", "task", "task_identity", "queue", "exchange"])
def test_foreign_task_signals_are_ignored(foreign: str) -> None:
    observer, task, request, consumer, output = recorder()
    if foreign == "app":
        task.app = request.app = consumer.app = SimpleNamespace()
    elif foreign == "task":
        task.name = "emailmonitor.fixture.export"
    elif foreign == "task_identity":
        observer.application.tasks[TASK] = SimpleNamespace()
    elif foreign == "queue":
        request.delivery_info["routing_key"] = request.delivery_info["exchange"] = "foreign"
    else:
        request.delivery_info["exchange"] = "foreign"
    observer.received(sender=consumer, request=request)
    observer.postrun(sender=task)
    observer.failure(sender=task, exception=RuntimeError("secret"))
    assert output == []


@pytest.mark.parametrize("foreign", ["app", "queues"])
def test_readiness_is_filtered_to_exact_app_and_owned_queues(foreign: str) -> None:
    observer, _, _, consumer, output = recorder()
    if foreign == "app":
        consumer.app = SimpleNamespace()
    else:
        consumer.task_consumer.queues.append(SimpleNamespace(name="foreign"))
    observer.ready(sender=consumer)
    assert output == []


def test_snapshots_are_bounded_and_cumulative_even_when_log_prefix_is_lost() -> None:
    observer, _, _, _, output = recorder()
    for _ in range(MAX_SNAPSHOTS + 10):
        observer.record("claim_empty")
    assert len(output) == MAX_SNAPSHOTS
    assert max(len(value.encode()) for value in output) <= 1024
    tail = b"partial secret log line\n" + "".join(output[-2:]).encode()
    snapshot = completion_worker_snapshot(tail, truncated=True)
    assert snapshot["status"] == "truncated" and snapshot["saturated"] is True
    assert cast(dict[str, int], snapshot["counts"])["claim_empty"] == MAX_SNAPSHOTS


def sample() -> dict[str, object]:
    counts = dict.fromkeys(STAGES, 0)
    counts["worker_ready"] = 1
    return {"counts": counts, "last_stage": "worker_ready", "saturated": False}


def frame(value: dict[str, object]) -> bytes:
    return WORKER_PREFIX + json.dumps(value).encode() + b"\n"


@pytest.mark.parametrize(
    "change",
    [
        "unknown_key",
        "unknown_stage",
        "unknown_count",
        "bool",
        "negative",
        "oversize",
        "text",
        "sum",
        "saturated",
    ],
)
def test_snapshot_parser_refuses_invalid_fields_without_echoing_them(change: str) -> None:
    value = sample()
    counts = cast(dict[str, object], value["counts"])
    if change == "unknown_key":
        value["secret"] = "password"
    elif change == "unknown_stage":
        value["last_stage"] = "secret"
    elif change == "unknown_count":
        counts["secret"] = 1
    elif change == "bool":
        counts["worker_ready"] = True
    elif change == "negative":
        counts["claim_enter"] = -1
    elif change == "oversize":
        counts["worker_ready"] = 513
    elif change == "text":
        counts["worker_ready"] = "password"
    elif change == "sum":
        counts["claim_enter"] = 512
    else:
        value["saturated"] = True
    result = completion_worker_snapshot(frame(value))
    assert result == {"status": "invalid", "counts": None, "last_stage": None, "saturated": None}


@pytest.mark.parametrize(
    "raw,status",
    [
        (b"secret plaintext\n", "unavailable"),
        (b"", "unavailable"),
        (b"EM_UI_WORKER_V1 {", "truncated"),
        (b"EM_UI_WORKER_V1 secret\n", "invalid"),
        (b"EM_UI_WORKER_V1 " + b"x" * 1024 + b"\n", "invalid"),
        (b"x" * 65537, "invalid"),
        (b'EM_UI_WORKER_V1 {"counts":{},"counts":{}}\n', "invalid"),
    ],
)
def test_snapshot_absence_and_truncation_are_not_zero_counts(raw: bytes, status: str) -> None:
    result = completion_worker_snapshot(raw)
    assert result["status"] == status and result["counts"] is None
    assert "secret" not in json.dumps(result)


def test_snapshot_parser_does_not_reset_or_accept_replayed_counters() -> None:
    assert completion_worker_snapshot(frame(sample()) * 2)["status"] == "invalid"
    wrong_stage = sample()
    cast(dict[str, int], wrong_stage["counts"])["claim_enter"] = 1
    assert completion_worker_snapshot(frame(sample()) + frame(wrong_stage))["status"] == "invalid"
    assert completion_worker_snapshot(b"partial", truncated=True)["status"] == "truncated"
    assert completion_worker_snapshot(frame(sample())[:-1])["status"] == "truncated"
    assert completion_worker_snapshot(frame(sample()))["status"] == "available"


def _check_worker_config(enabled: bool) -> None:
    # A real worker starts with a fresh interpreter. Celery's process-global
    # shared task registration must not reuse another test application's closure.
    from emailmonitor.jobs import broker

    monkeypatch = pytest.MonkeyPatch()

    output: list[str] = []
    callbacks: list[object] = []
    monkeypatch.setattr(broker, "Database", lambda _: SimpleNamespace())
    monkeypatch.setattr(
        broker, "WorkerDiagnostics", lambda app, queue: WorkerDiagnostics(app, queue, output.append)
    )

    def execute(*_: object, **kwargs: object) -> bool:
        callbacks.append(kwargs["diagnostic"])
        return False

    monkeypatch.setattr(broker, "execute_process", execute)
    config = FixtureWorkerConfig(
        environment="test",
        database_url="postgresql+pg8000://fixture@127.0.0.1/test",
        broker_url="pyamqp://fixture@127.0.0.1/",
        organization=str(uuid4()),
        session_token="synthetic-session-only",
        queue=NAMESPACE,
        ui_diagnostics=enabled,
    )
    app, _ = create_worker(config)
    task = app.tasks[TASK]
    try:
        for queue in [NAMESPACE + "-parse", "foreign"]:
            task.push_request(delivery_info={"routing_key": queue, "exchange": queue})
            try:
                task.run({})
            finally:
                task.pop_request()
        assert (callbacks[0] is not None) is enabled and callbacks[1] is None
        assert len(output) == int(enabled)
    finally:
        app.close()
        monkeypatch.undo()


@pytest.mark.parametrize("enabled", [False, True])
def test_fixture_worker_diagnostics_are_explicitly_opt_in_and_queue_scoped(enabled: bool) -> None:
    child = multiprocessing.get_context("spawn").Process(
        target=_check_worker_config, args=(enabled,)
    )
    child.start()
    try:
        child.join(timeout=10)
        assert child.exitcode == 0
    finally:
        if child.is_alive():
            child.kill()
            child.join(timeout=5)
        child.close()


def test_diagnostic_wire_parity_and_existing_ui_controls_are_unchanged() -> None:
    assert tuple(STAGES) == WORKER_STAGES and PREFIX.encode() == WORKER_PREFIX
    source = (ROOT / "scripts/isolation/test_operator_ui_acceptance.py").read_text()
    assert "ui_diagnostics=True" in source
    assert "wait_for(complete, seconds=8)" in source
    assert "wait_for(consumer_ready)" in source
    assert "file.read(65536)" in source
    assert '"worker_stages": worker_snapshot' in source
    assert FixtureWorkerConfig.model_fields["ui_diagnostics"].default is False

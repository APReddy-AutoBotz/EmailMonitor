"""Pure opt-in fixture diagnostics preserve worker behavior and reveal no task data."""

import json
import multiprocessing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from celery import signals
from emailmonitor.fetching.safety import FetchDenied, IsolationUnavailable
from emailmonitor.jobs.broker import FixtureWorkerConfig, create_worker
from emailmonitor.jobs.diagnostics import (
    FAILURE_CLASSES,
    FAILURE_REASONS,
    MAX_SNAPSHOTS,
    PREFIX,
    STAGES,
    TASK,
    WorkerDiagnostics,
)
from emailmonitor.jobs.queues import owned_queues
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.progress.broker import process
from emailmonitor.progress.service import Progress
from operator_ui_protocol import (
    WORKER_FAILURE_CLASSES,
    WORKER_FAILURE_REASONS,
    WORKER_PREFIX,
    WORKER_STAGES,
    completion_worker_snapshot,
)

ROOT = Path(__file__).resolve().parents[3]
NAMESPACE = "em-fixture-diagnostics"


class PrivateFailure(Exception):
    pass


class UnpickleableFailure(Exception):
    def __reduce__(self) -> Any:
        raise TypeError("synthetic non-pickleable exception")


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
    info = {"routing_key": NAMESPACE + "-parse", "exchange": ""}
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
    assert snapshot["last_failure"] == {
        "phase": "other",
        "class": "RuntimeError",
        "reason": "other",
    }
    assert "secret" not in "".join(output) and NAMESPACE not in "".join(output)
    assert "ack" not in "".join(output).lower()


@pytest.mark.parametrize(
    "foreign",
    [
        "app",
        "task",
        "task_identity",
        "queue",
        "exchange",
        "named_exchange",
        "missing_exchange",
        "null_exchange",
    ],
)
def test_foreign_task_signals_are_ignored(foreign: str) -> None:
    observer, task, request, consumer, output = recorder()
    if foreign == "app":
        task.app = request.app = consumer.app = SimpleNamespace()
    elif foreign == "task":
        task.name = "emailmonitor.fixture.export"
    elif foreign == "task_identity":
        observer.application.tasks[TASK] = SimpleNamespace()
    elif foreign == "queue":
        request.delivery_info["routing_key"] = "foreign"
    elif foreign == "named_exchange":
        request.delivery_info["exchange"] = request.delivery_info["routing_key"]
    elif foreign == "missing_exchange":
        del request.delivery_info["exchange"]
    elif foreign == "null_exchange":
        request.delivery_info["exchange"] = None
    else:
        request.delivery_info["exchange"] = "foreign"
    observer.received(sender=consumer, request=request)
    observer.postrun(sender=task)
    observer.failure(sender=task, exception=RuntimeError("secret"))
    assert output == []
    assert observer.last_failure is None


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
    return {
        "counts": counts,
        "last_stage": "worker_ready",
        "last_failure": None,
        "saturated": False,
    }


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
    assert result == {
        "status": "invalid",
        "counts": None,
        "last_stage": None,
        "last_failure": None,
        "saturated": None,
    }


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
            task.push_request(delivery_info={"routing_key": queue, "exchange": ""})
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
    assert tuple(label for _, label in FAILURE_CLASSES) + ("other",) == WORKER_FAILURE_CLASSES
    assert FAILURE_REASONS + ("other",) == WORKER_FAILURE_REASONS
    source = (ROOT / "scripts/isolation/test_operator_ui_acceptance.py").read_text()
    assert "ui_diagnostics=True" in source
    assert "wait_for(complete, seconds=8)" in source
    assert "wait_for(consumer_ready)" in source
    assert "file.read(65536)" in source
    assert '"worker_stages": worker_snapshot' in source
    assert FixtureWorkerConfig.model_fields["ui_diagnostics"].default is False


def _check_published_delivery(
    kind: str, outcome: str, failure_kind: str = "runtime", enabled: bool = True
) -> None:
    """Pinned publication metadata, genuine Request and actual Celery trace signals."""
    import socket
    from contextlib import nullcontext
    from importlib import import_module

    from emailmonitor.jobs import broker
    from emailmonitor.jobs.queues import phase_queue
    from emailmonitor.progress.broker import publish

    monkeypatch = pytest.MonkeyPatch()
    output: list[str] = []
    publications: list[tuple[object, dict[str, Any]]] = []
    confirmations: list[object] = []
    calls: list[str] = []
    org, job, item, event = (uuid4() for _ in range(4))
    errors = {
        "runtime": RuntimeError("synthetic-task-failure"),
        "fetch": FetchDenied("source_entitlement_denied"),
        "isolation": IsolationUnavailable("private synthetic reason"),
        "unknown": PrivateFailure("synthetic-task-failure"),
        "unpickleable": UnpickleableFailure("synthetic-task-failure"),
    }
    original = errors[failure_kind]
    seen_failures: list[object] = []

    def capture_failure(exception: object, **_: object) -> None:
        seen_failures.append(exception)

    def no_socket(*_: object, **__: object) -> None:
        raise AssertionError("No network in publication/trace regression")

    def claim(*_: object) -> object:
        calls.append("claim")
        if outcome == "claim_error":
            raise original
        return None if outcome == "empty" else SimpleNamespace(lease=SimpleNamespace(generation=1))

    def fixture(*_: object) -> None:
        calls.append("process")
        if outcome == "process_error":
            raise original

    progress = SimpleNamespace(
        claim=claim,
        process_fixture=fixture,
        pending=lambda _: [
            {
                "job_id": job,
                "item_id": item,
                "event_id": event,
                "generation": 1,
                "work_kind": kind,
            }
        ],
        confirmed=lambda *args: confirmations.append(args),
    )

    class Producer:
        connection = SimpleNamespace(_reraise_as_library_errors=nullcontext)

        def publish(self, value: object, **options: Any) -> None:
            publications.append((value, options))

    monkeypatch.setattr(socket, "socket", no_socket)
    monkeypatch.setattr(broker, "Database", lambda _: SimpleNamespace())
    monkeypatch.setattr(broker, "Progress", lambda *_: progress)
    monkeypatch.setattr(
        broker, "WorkerDiagnostics", lambda app, queue: WorkerDiagnostics(app, queue, output.append)
    )
    config = FixtureWorkerConfig(
        environment="test",
        database_url="postgresql+pg8000://fixture@127.0.0.1/test",
        broker_url="pyamqp://fixture@127.0.0.1/",
        organization=str(org),
        session_token="synthetic-session-only",
        queue=NAMESPACE,
        ui_diagnostics=enabled,
    )
    app, _ = create_worker(config)
    monkeypatch.setattr(app, "producer_or_acquire", lambda _: nullcontext(Producer()))
    task = app.tasks[TASK]
    signals.task_failure.connect(capture_failure, sender=task, weak=False)
    try:
        assert publish(app, cast(Progress, progress), org) == 1
        assert confirmations == [(org, job, event)]
        value, options = publications[0]
        queue = phase_queue(NAMESPACE, "fixture_io" if kind == "discover" else "parse")
        # Assert actual pinned send_task metadata rather than fabricating the
        # exchange/routing pair that blinded the first diagnostic version.
        assert options["exchange"] == "" and options["routing_key"] == queue
        assert options["mandatory"] is True
        content_type, encoding, serialized = import_module("kombu.serialization").dumps(
            value, serializer=options["serializer"]
        )
        message = import_module("kombu.message").Message(
            body=serialized,
            content_type=content_type,
            content_encoding=encoding,
            headers=options["headers"],
            properties={"correlation_id": options["correlation_id"]},
            delivery_info={"exchange": options["exchange"], "routing_key": options["routing_key"]},
        )
        request = import_module("celery.worker.request").Request(message, app=app, task=task)
        assert request.app is app and request.task is task
        consumer = SignalObject(app=app)
        signals.task_received.send(sender=consumer, request=request)
        traced = import_module("celery.app.trace").trace_task(
            task, request.id, request.args, request.kwargs, request=request.request_dict, app=app
        )
        assert (traced.info is not None) is outcome.endswith("error")
        if traced.info is not None:
            assert traced.info.retval is original
            assert len(seen_failures) == 1
            if failure_kind == "unpickleable":
                wrapper = import_module("celery.utils.serialization").UnpickleableExceptionWrapper
                assert type(seen_failures[0]) is wrapper
            else:
                assert seen_failures[0] is original
        else:
            assert seen_failures == []
        expected = ["task_received", "execute_enter", "validated", "claim_enter"]
        if outcome == "empty":
            expected += ["claim_empty"]
        elif outcome == "claim_error":
            expected += ["claim_error", "task_failure"]
        else:
            expected += ["claim_acquired", "process_enter"]
            expected += (
                ["process_error", "task_failure"]
                if outcome == "process_error"
                else ["process_return"]
            )
        expected += ["task_postrun"]
        snapshots = [json.loads(line.removeprefix(PREFIX)) for line in output]
        assert [snapshot["last_stage"] for snapshot in snapshots] == (expected if enabled else [])
        assert calls == (["claim"] if outcome in {"empty", "claim_error"} else ["claim", "process"])
        parsed = completion_worker_snapshot("".join(output).encode())
        assert parsed["status"] == ("available" if enabled else "unavailable")
        if enabled:
            assert cast(dict[str, int], parsed["counts"])["task_postrun"] == 1
        assert parsed["last_failure"] == (
            {
                "phase": "claim" if outcome == "claim_error" else "process",
                "class": {
                    "runtime": "RuntimeError",
                    "fetch": "FetchDenied",
                    "isolation": "IsolationUnavailable",
                    "unknown": "other",
                    "unpickleable": "other",
                }[failure_kind],
                "reason": "source_entitlement_denied" if failure_kind == "fetch" else "other",
            }
            if enabled and outcome.endswith("error")
            else None
        )
        assert not any(
            value in "".join(output)
            for value in [
                str(org),
                str(job),
                str(item),
                str(event),
                queue,
                config.session_token,
                "synthetic-task-failure",
                "private synthetic reason",
                "PrivateFailure",
                "UnpickleableFailure",
            ]
        )
    finally:
        signals.task_failure.disconnect(capture_failure, sender=task)
        app.close()
        monkeypatch.undo()


@pytest.mark.parametrize("kind", ["discover", "article"])
@pytest.mark.parametrize("outcome", ["success", "empty", "claim_error", "process_error"])
def test_real_published_routing_and_celery_request_trace_signals(kind: str, outcome: str) -> None:
    child = multiprocessing.get_context("spawn").Process(
        target=_check_published_delivery, args=(kind, outcome)
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


@pytest.mark.parametrize("kind", ["discover", "article"])
@pytest.mark.parametrize("outcome", ["claim_error", "process_error"])
@pytest.mark.parametrize("failure_kind", ["fetch", "isolation", "unknown", "unpickleable"])
def test_real_trace_failure_metadata(kind: str, outcome: str, failure_kind: str) -> None:
    child = multiprocessing.get_context("spawn").Process(
        target=_check_published_delivery, args=(kind, outcome, failure_kind)
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


@pytest.mark.parametrize("outcome", ["claim_error", "process_error"])
def test_real_trace_failure_has_no_diagnostics_when_disabled(outcome: str) -> None:
    child = multiprocessing.get_context("spawn").Process(
        target=_check_published_delivery, args=("article", outcome, "fetch", False)
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


@pytest.mark.parametrize("kind,label", FAILURE_CLASSES)
def test_failure_class_mapping_uses_only_exact_types(kind: type[BaseException], label: str) -> None:
    observer, task, _, _, output = recorder()
    observer.record("claim_error")
    observer.failure(sender=task, exception=kind("secret https://example.test/?token=private"))
    snapshot = completion_worker_snapshot("".join(output).encode())
    assert snapshot["last_failure"] == {"phase": "claim", "class": label, "reason": "other"}
    assert "secret" not in "".join(output) and "private" not in "".join(output)


@pytest.mark.parametrize("reason", FAILURE_REASONS)
def test_exact_fetch_reasons_survive_success_and_truncated_tail(reason: str) -> None:
    observer, task, _, _, output = recorder()
    observer.record("process_error")
    observer.failure(
        sender=task, exception=FetchDenied(reason), traceback="secret", args=["secret"]
    )
    expected = {"phase": "process", "class": "FetchDenied", "reason": reason}
    # A later successful task must not erase the previous failure or expose data.
    for stage in ("task_postrun", "execute_enter", "process_return", "task_postrun"):
        observer.record(stage)
    parsed = completion_worker_snapshot("".join(output).encode())
    assert parsed["last_failure"] == expected
    tail = completion_worker_snapshot(b"partial secret\n" + output[-1].encode(), truncated=True)
    assert tail["status"] == "truncated" and tail["last_failure"] == expected
    assert "secret" not in "".join(output)
    # A subsequent failure before claim/process must not inherit the old phase.
    observer.record("execute_enter")
    observer.failure(sender=task, exception=ValueError("private validation body"))
    assert completion_worker_snapshot("".join(output).encode())["last_failure"] == {
        "phase": "other",
        "class": "ValueError",
        "reason": "other",
    }


@pytest.mark.parametrize(
    "arguments",
    [
        (),
        ("source_policy_denied", "secret"),
        ("source_policy_denied secret",),
        ("secret source_policy_denied",),
        ("source_policy_denied\n",),
        ("SOURCE_POLICY_DENIED",),
        ("https://example.test/?token=secret",),
        ({"source_policy_denied": "secret"},),
        (b"source_policy_denied",),
        ("source_policy_denied" * 10000,),
    ],
)
def test_unknown_fetch_reason_arguments_are_never_emitted(arguments: tuple[object, ...]) -> None:
    observer, task, _, _, output = recorder()
    observer.failure(sender=task, exception=FetchDenied(*arguments))
    assert completion_worker_snapshot("".join(output).encode())["last_failure"] == {
        "phase": "other",
        "class": "FetchDenied",
        "reason": "other",
    }
    assert "secret" not in "".join(output)


def test_unknown_exception_subclasses_and_argument_objects_are_not_inspected() -> None:
    class HostileFetch(FetchDenied):
        def __getattribute__(self, name: str) -> Any:
            raise AssertionError("must not inspect unknown exception")

        def __str__(self) -> str:
            raise AssertionError("must not stringify unknown exception")

        def __repr__(self) -> str:
            raise AssertionError("must not repr unknown exception")

    class HostileString(str):
        def __eq__(self, other: object) -> bool:
            raise AssertionError("must not compare unknown string type")

    for error, label in [
        (HostileFetch("secret"), "other"),
        (type("FetchDenied", (Exception,), {})("source_policy_denied"), "other"),
        (FetchDenied(HostileString("source_policy_denied")), "FetchDenied"),
        (RuntimeError("source_policy_denied"), "RuntimeError"),
        (IsolationUnavailable("source_policy_denied"), "IsolationUnavailable"),
    ]:
        observer, task, _, _, output = recorder()
        observer.failure(sender=task, exception=error)
        assert completion_worker_snapshot("".join(output).encode())["last_failure"] == {
            "phase": "other",
            "class": label,
            "reason": "other",
        }
        assert "secret" not in "".join(output)


@pytest.mark.parametrize("broken", ["writer", "classifier"])
def test_failure_diagnostic_errors_are_isolated(
    broken: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from emailmonitor.jobs import diagnostics

    observer, task, _, _, output = recorder()

    def fail(*_: object) -> Any:
        raise RuntimeError("diagnostic failure")

    if broken == "writer":
        observer.writer = fail
    else:
        monkeypatch.setattr(diagnostics, "failure_metadata", fail)
    original = FetchDenied("source_policy_denied")
    observer.failure(sender=task, exception=original)
    assert output == [] and original.args == ("source_policy_denied",)


def test_failure_at_snapshot_cap_is_retained_without_further_output_or_mutation() -> None:
    observer, task, _, _, output = recorder()
    for _ in range(MAX_SNAPSHOTS - 2):
        observer.record("claim_empty")
    observer.record("process_error")
    observer.failure(sender=task, exception=FetchDenied("source_resource_scope_denied"))
    saved = observer.last_failure
    observer.record("execute_enter")
    observer.failure(sender=task, exception=ValueError("secret"))
    assert len(output) == MAX_SNAPSHOTS and observer.last_failure is saved
    assert max(len(line.encode()) for line in output) <= 1024
    parsed = completion_worker_snapshot(
        b"partial\n" + "".join(output[-2:]).encode(), truncated=True
    )
    assert parsed["status"] == "truncated" and parsed["saturated"] is True
    assert parsed["last_failure"] == saved


def failure_sample() -> dict[str, object]:
    value = sample()
    cast(dict[str, int], value["counts"]).update(process_error=1, task_failure=1)
    value["last_stage"] = "task_failure"
    value["last_failure"] = {
        "phase": "process",
        "class": "FetchDenied",
        "reason": "source_policy_denied",
    }
    return value


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "null",
        "extra",
        "missing_field",
        "phase",
        "class",
        "reason",
        "type",
        "list",
        "no_failure",
        "no_phase_error",
        "reason_class",
        "number",
    ],
)
def test_failure_snapshot_schema_is_closed_and_consistent(change: str) -> None:
    value = failure_sample()
    failure = cast(dict[str, object], value["last_failure"])
    counts = cast(dict[str, int], value["counts"])
    if change == "missing":
        del value["last_failure"]
    elif change == "null":
        value["last_failure"] = None
    elif change == "extra":
        failure["message"] = "secret"
    elif change == "missing_field":
        del failure["class"]
    elif change in {"phase", "class", "reason"}:
        failure[change] = "secret"
    elif change == "type":
        failure["class"] = True
    elif change == "list":
        value["last_failure"] = [failure]
    elif change == "no_failure":
        counts["task_failure"] = 0
        value["last_stage"] = "process_error"
    elif change == "no_phase_error":
        counts["process_error"] = 0
    elif change == "reason_class":
        failure["class"] = "RuntimeError"
    else:
        failure["reason"] = 1
    result = completion_worker_snapshot(frame(value))
    assert result["status"] == "invalid" and result["last_failure"] is None
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("change", ["clear", "replace", "wrong_phase", "duplicate"])
def test_failure_snapshot_metadata_cannot_change_without_matching_failure(change: str) -> None:
    first = failure_sample()
    second = failure_sample()
    counts = cast(dict[str, int], second["counts"])
    second["last_stage"] = "task_postrun"
    counts["task_postrun"] = 1
    if change == "clear":
        second["last_failure"] = None
    elif change == "replace":
        cast(dict[str, str], second["last_failure"])["reason"] = "source_entitlement_denied"
    elif change == "wrong_phase":
        second["last_stage"] = "task_failure"
        counts["task_postrun"] = 0
        counts["task_failure"] = 2
    raw = frame(first) + frame(second)
    if change == "duplicate":
        raw = raw.replace(b'"phase": "process"', b'"phase": "process", "phase": "other"')
    assert completion_worker_snapshot(raw)["status"] == "invalid"


def test_foreign_failure_does_not_replace_prior_scoped_failure() -> None:
    observer, task, _, _, output = recorder()
    observer.record("process_error")
    observer.failure(sender=task, exception=FetchDenied("source_policy_denied"))
    before = "".join(output)
    task.request.delivery_info["routing_key"] = "foreign"
    observer.failure(sender=task, exception=ValueError("private"))
    assert "".join(output) == before
    assert observer.last_failure == {
        "phase": "process",
        "class": "FetchDenied",
        "reason": "source_policy_denied",
    }


def test_incomplete_final_snapshot_preserves_last_known_failure() -> None:
    observer, task, _, _, output = recorder()
    observer.record("process_error")
    observer.failure(sender=task, exception=FetchDenied("source_policy_denied"))
    observer.postrun(sender=task)
    raw = "".join(output[:-1]).encode() + output[-1].encode()[:-1]
    parsed = completion_worker_snapshot(raw)
    assert parsed["status"] == "truncated" and parsed["last_stage"] == "task_failure"
    assert parsed["last_failure"] == observer.last_failure

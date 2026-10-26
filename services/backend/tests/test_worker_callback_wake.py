"""Pinned real solo/handler regression and bounded no-network wake lifecycle."""

import errno
import multiprocessing
import os
import socket
import time
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from celery import signals
from emailmonitor.jobs.broker import FixtureWorkerConfig, create_worker
from emailmonitor.jobs.callback_wake import FixtureCallbackWake, ReadyCallbackWake
from emailmonitor.jobs.diagnostics import TASK
from owned_phase_trace import Mark, PhaseTrace, callback_entry, quiet_mark, receipt, resources

Hub = import_module("kombu.asynchronous.hub").Hub
NAMESPACE = "em-fixture-callback-wake"


def closed_fds(fds: tuple[int | None, int | None]) -> None:
    for fd in fds:
        assert fd is not None
        with pytest.raises(OSError) as caught:
            os.fstat(fd)
        assert caught.value.errno == errno.EBADF


def test_wake_is_idempotent_nonblocking_cloexec_and_one_byte() -> None:
    hub = Hub()
    wake = ReadyCallbackWake.install(hub)
    fds = (wake.read_fd, wake.write_fd)
    calls: list[str] = []
    try:
        assert ReadyCallbackWake.install(hub) is wake
        for fd in fds:
            assert fd is not None
            assert not os.get_blocking(fd) and not os.get_inheritable(fd)
        for _ in range(20):
            wake.before_poll()
        assert not wake.signaled and hub.poller.poll(0) == []
        promise = hub.call_soon(calls.append, "original")
        for _ in range(20):
            wake.before_poll()
        assert wake.signaled and calls == [] and hub._ready == {promise}
        assert wake.read_fd is not None
        assert os.read(wake.read_fd, 2) == b"\0"
        with pytest.raises(BlockingIOError):
            os.read(wake.read_fd, 1)
        wake.drain()  # An empty/nonblocking drain is safe, with no callback run.
        assert not wake.signaled and hub._ready == {promise}
        wake.before_poll()
        wake.drain()
        assert not wake.signaled and hub.poller.poll(0) == []
        assert hub._pop_ready() == {promise}
        promise()
        assert calls == ["original"]
    finally:
        wake.close()
        wake.close()
        hub.close()
    closed_fds(fds)
    assert not hub.on_tick and not hub.on_close and not hub.readers


@pytest.mark.parametrize("reset", [False, True])
def test_hub_close_and_reconnect_do_not_reopen_poller_or_accumulate_hooks(reset: bool) -> None:
    hub = Hub()
    step = FixtureCallbackWake(SimpleNamespace())
    consumer = SimpleNamespace(hub=hub)
    original_close_hook = lambda _: None  # noqa: E731
    hub.on_close.add(original_close_hook)
    for _ in range(5):
        step.start(consumer)
        wake = step.wake
        assert wake is not None
        fds = (wake.read_fd, wake.write_fd)
        step.start(consumer)
        assert step.wake is wake and len(hub.on_close) == 2
        if reset:
            hub.reset()
            assert hub._poller is not None
        else:
            hub.close()
            assert hub._poller is None
        closed_fds(fds)
        assert wake.closed and wake.read_fd is None and wake.write_fd is None
        assert not hub.on_tick and not hub.readers
        assert len(hub.on_close) == 2  # One inert hook until safe detachment.
        step.start(consumer)
        assert step.wake is not wake and len(hub.on_close) == 2
        fresh = step.wake
        assert fresh is not None
        fresh_fds = (fresh.read_fd, fresh.write_fd)
        step.stop(consumer)
        step.shutdown(consumer)
        step.terminate(consumer)
        closed_fds(fresh_fds)
        assert not hub.on_tick and not hub.readers
        assert hub.on_close == {original_close_hook}
    hub.close()
    assert hub._poller is None


def test_changed_hub_closes_previous_pair_before_reinstall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = Hub(), Hub()
    consumer = SimpleNamespace(hub=first)
    step = FixtureCallbackWake(consumer)
    step.start(consumer)
    assert step.wake is not None
    fds = (step.wake.read_fd, step.wake.write_fd)
    consumer.hub = second
    pipe2 = os.pipe2
    allocations: list[bool] = []

    def allocate(flags: int) -> tuple[int, int]:
        # Check before allocation: the OS may immediately reuse both numbers.
        closed_fds(fds)
        allocations.append(True)
        return pipe2(flags)

    monkeypatch.setattr(os, "pipe2", allocate)
    try:
        step.start(consumer)
        assert allocations == [True]
        assert not first.on_tick and not first.on_close and not first.readers
        assert step.wake is not None and step.wake.hub is second
    finally:
        step.stop(consumer)
        first.close()
        second.close()


@pytest.mark.parametrize("field", ["_ready", "_ready_lock"])
def test_incompatible_private_hub_contract_refuses_before_allocating(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = Hub()
    monkeypatch.setattr(hub, field, None)

    def forbidden(*_: object) -> None:
        raise AssertionError("No descriptor allocation for incompatible hub")

    monkeypatch.setattr(os, "pipe2", forbidden)
    with pytest.raises(RuntimeError, match="Unsupported fixture worker ready queue"):
        ReadyCallbackWake.install(hub)
    monkeypatch.undo()
    hub.close()


@pytest.mark.parametrize("stage", ["pipe", "reader", "tick", "close_hook"])
def test_installation_failure_closes_every_allocated_fd(
    stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = Hub()
    allocated: list[int] = []
    original = RuntimeError("installation failed")
    pipe2 = os.pipe2

    def pipe(flags: int) -> tuple[int, int]:
        if stage == "pipe":
            raise original
        fds = pipe2(flags)
        allocated.extend(fds)
        return fds

    class RefuseAdd(set[Any]):
        def add(self, value: Any) -> None:
            super().add(value)  # Exercise failure after partial registration.
            raise original

    add_reader = hub.add_reader

    def reader(*args: Any) -> None:
        add_reader(*args)
        raise original

    monkeypatch.setattr(os, "pipe2", pipe)
    if stage == "reader":
        monkeypatch.setattr(hub, "add_reader", reader)
    if stage == "tick":
        hub.on_tick = RefuseAdd()
    if stage == "close_hook":
        hub.on_close = RefuseAdd()
    with pytest.raises(RuntimeError) as caught:
        ReadyCallbackWake.install(hub)
    assert caught.value is original
    assert not hub.on_tick and not hub.on_close and not hub.readers
    if allocated:
        closed_fds((allocated[0], allocated[1]))
    hub.close()


@pytest.mark.parametrize("stage", ["write", "short_write", "read", "eof"])
def test_io_failures_close_adapter_and_propagate(
    stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = Hub()
    wake = ReadyCallbackWake.install(hub)
    fds = (wake.read_fd, wake.write_fd)
    original = OSError(errno.EIO, "synthetic I/O failure")

    def fail(*_: Any) -> Any:
        raise original

    try:
        hub.call_soon(lambda: None)
        if stage in {"write", "short_write"}:
            monkeypatch.setattr(os, "write", fail if stage == "write" else lambda *_: 0)
            action = wake.before_poll
        else:
            wake.before_poll()
            monkeypatch.setattr(os, "read", fail if stage == "read" else lambda *_: b"")
            action = wake.drain
        with pytest.raises((OSError, RuntimeError)) as caught:
            action()
        if stage in {"write", "read"}:
            assert caught.value is original
        assert wake.closed and not hub.on_tick and not hub.on_close and not hub.readers
        closed_fds(fds)
    finally:
        monkeypatch.undo()
        wake.close()
        hub.close()


def test_full_pipe_is_already_readable_and_cleanup_closes_both_after_remove_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = Hub()
    wake = ReadyCallbackWake.install(hub)
    fds = (wake.read_fd, wake.write_fd)
    assert wake.write_fd is not None
    os.write(wake.write_fd, b"\0")

    def full(*_: object) -> None:
        raise BlockingIOError(errno.EAGAIN, "already readable")

    monkeypatch.setattr(os, "write", full)
    hub.call_soon(lambda: None)
    wake.before_poll()
    assert wake.signaled and hub.poller.poll(0)
    wake.drain()
    assert not wake.signaled
    remove = hub.remove_reader
    original = RuntimeError("remove failed")

    def remove_failed(fd: int) -> None:
        remove(fd)
        raise original

    monkeypatch.setattr(hub, "remove_reader", remove_failed)
    with pytest.raises(RuntimeError) as caught:
        wake.close()
    assert caught.value is original
    closed_fds(fds)
    assert not hub.on_tick and not hub.on_close and not hub.readers
    wake.close()
    hub.close()


def test_repeated_lifecycle_has_no_descriptor_leak() -> None:
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(20):
        hub = Hub()
        wake = ReadyCallbackWake.install(hub)
        wake.before_poll()
        hub.close()
        wake.close()
        hub.close()
    assert len(os.listdir("/proc/self/fd")) == before


def test_stop_preserves_original_pending_callbacks_for_normal_hub_close() -> None:
    hub = Hub()
    consumer = SimpleNamespace(hub=hub)
    step = FixtureCallbackWake(consumer)
    step.start(consumer)
    calls: list[str] = []
    promise = hub.call_soon(calls.append, "original")
    assert step.wake is not None
    step.wake.before_poll()
    step.shutdown(consumer)
    assert calls == [] and hub._ready == {promise}
    hub.close()
    assert calls == ["original"] and not hub._ready


def test_first_fd_close_failure_still_closes_second_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = Hub()
    wake = ReadyCallbackWake.install(hub)
    fds = (wake.read_fd, wake.write_fd)
    closed: list[int] = []
    close = os.close
    original = OSError(errno.EIO, "synthetic close failure")

    def close_failed(fd: int) -> None:
        closed.append(fd)
        close(fd)
        if fd == fds[0]:
            raise original

    monkeypatch.setattr(os, "close", close_failed)
    with pytest.raises(OSError) as caught:
        wake.close()
    assert caught.value is original and closed == list(fds)
    wake.close()
    assert closed == list(fds)  # Never retry an uncertain descriptor close.
    closed_fds(fds)
    monkeypatch.undo()
    hub.close()


def _real_solo_delivery(
    with_wake: bool, diagnostics: bool, outcome: str, *, mark: Mark = quiet_mark
) -> None:
    """Only persistence and incoming broker bytes are synthetic, not ACK code."""
    from emailmonitor.jobs import broker

    asynchronous = import_module("kombu.asynchronous")
    serialization = import_module("kombu.serialization")
    message_module = import_module("kombu.message")
    transport = import_module("kombu.transport.base").Transport
    assert import_module("celery").__version__ == "5.6.3"
    assert import_module("kombu").__version__ == "5.6.2"
    assert import_module("amqp").__version__ == "5.4.1"
    mark("dependencies_ready")
    monkeypatch = pytest.MonkeyPatch()
    counts = {"claim": 0, "process": 0, "postrun": 0, "failure": 0, "ack": 0}
    requests: list[Any] = []

    def no_network(*_: Any, **__: Any) -> None:
        raise AssertionError("No network in real worker regression")

    def claim(*_: Any) -> Any:
        counts["claim"] += 1
        if outcome == "claim_error":
            raise RuntimeError("synthetic claim failure")
        return None if outcome == "empty" else SimpleNamespace(lease=SimpleNamespace(generation=1))

    def process(*_: Any) -> None:
        counts["process"] += 1
        if outcome == "process_error":
            raise RuntimeError("synthetic processing failure")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setattr(socket, "socket", no_network)
    for name in (
        "create_connection",
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname_ex",
        "gethostbyaddr",
    ):
        monkeypatch.setattr(socket, name, no_network)
    monkeypatch.setattr(broker, "Database", lambda _: SimpleNamespace())
    monkeypatch.setattr(
        broker, "Progress", lambda *_: SimpleNamespace(claim=claim, process_fixture=process)
    )
    asynchronous.set_event_loop(None)
    mark("patches_ready")
    org = uuid4()
    app, _ = create_worker(
        FixtureWorkerConfig(
            environment="test",
            database_url="postgresql+pg8000://fixture@127.0.0.1/test",
            broker_url="pyamqp://fixture@127.0.0.1/",
            organization=str(org),
            session_token="synthetic-session-only",
            queue=NAMESPACE,
            ui_diagnostics=diagnostics,
        )
    )
    mark("app_ready")
    assert FixtureCallbackWake in app.steps["consumer"]
    if not with_wake:
        app.steps["consumer"].discard(FixtureCallbackWake)
    mark("worker_construct_started")
    worker = app.Worker(
        pool="solo",
        concurrency=1,
        hostname="fixture@localhost",
        loglevel="WARNING",
        without_gossip=True,
        without_mingle=True,
        without_heartbeat=True,
    )
    mark("worker_ready")
    consumer = worker.consumer
    hub = consumer.hub
    assert hub is not None
    step = next((step for step in consumer.steps if isinstance(step, FixtureCallbackWake)), None)
    if with_wake:
        assert step is not None
        names = [type(step).__name__ for step in consumer.steps]
        assert names.index("Tasks") < names.index("FixtureCallbackWake") < names.index("Evloop")
        step.start(consumer)
    else:
        assert step is None
    assert consumer.amqheartbeat == 120 and consumer.amqheartbeat_rate == 3
    assert hub.timer.max_interval == 10
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_acks_late and app.conf.task_reject_on_worker_lost
    assert consumer.initial_prefetch_count == 1
    consumer.update_strategies()
    handler = consumer.create_task_handler()
    mark("handshake_ready")

    def received(sender: Any = None, request: Any = None, **_: Any) -> None:
        if sender is consumer:
            requests.append(request)

    def postrun(sender: Any = None, **_: Any) -> None:
        if sender is app.tasks[TASK]:
            counts["postrun"] += 1

    def failed(sender: Any = None, **_: Any) -> None:
        if sender is app.tasks[TASK]:
            counts["failure"] += 1

    signals.task_received.connect(received, weak=False)
    signals.task_postrun.connect(postrun, weak=False)
    signals.task_failure.connect(failed, weak=False)
    body = {
        "organization_id": str(org),
        "job_id": str(uuid4()),
        "item_id": str(uuid4()),
        "event_id": str(uuid4()),
        "generation": 1,
    }
    envelope = app.amqp.create_task_message(str(uuid4()), TASK, args=[body])
    content_type, encoding, serialized = serialization.dumps(envelope.body, serializer="json")

    class Channel:
        no_ack_consumers: set[str] = set()

        def basic_ack(self, delivery_tag: int, multiple: bool = False) -> None:
            assert delivery_tag == 1 and multiple is False
            counts["ack"] += 1

    message = message_module.Message(
        body=serialized,
        content_type=content_type,
        content_encoding=encoding,
        headers=envelope.headers,
        properties=envelope.properties,
        delivery_info={"exchange": "", "routing_key": NAMESPACE + "-parse"},
        delivery_tag=1,
        channel=Channel(),
    )

    class BufferedConnection:
        connected = True
        calls = 0

        def drain_events(self, timeout: int) -> None:
            self.calls += 1
            if self.calls > 1:
                raise TimeoutError()
            handler(message)

    # The real transport schedules this reader after draining one available
    # frame, exactly the callback-inside-ready-snapshot branch under test.
    hub.call_soon(transport._make_reader(None, BufferedConnection()), hub)
    hub.timer.call_repeatedly(consumer.amqheartbeat / consumer.amqheartbeat_rate, lambda: None)
    idle_read, idle_write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    hub.add_reader(idle_read, lambda: None)
    polls: list[tuple[float, int, int]] = []
    original_poll = hub.poller.poll

    def observed_poll(timeout: float) -> Any:
        polls.append((timeout, len(hub._ready), counts["ack"]))
        # First poll uses the real OS selector and unchanged timeout. Once the
        # ACK has occurred, skip only the irrelevant subsequent idle wait.
        return [] if counts["ack"] else original_poll(timeout)

    hub.poller.poll = observed_poll
    loop = hub.create_loop()
    try:
        mark("work_started")
        started = time.monotonic()
        next(loop)
        elapsed = time.monotonic() - started
        mark("first_poll_done")
        assert polls[0] == (10.0, 2, 0)
        assert counts["claim"] == 1 and counts["postrun"] == 1 and counts["ack"] == 0
        assert counts["process"] == (0 if outcome in {"empty", "claim_error"} else 1)
        assert counts["failure"] == int(outcome.endswith("error"))
        assert len(requests) == 1 and requests[0].acknowledged
        assert not message.acknowledged
        # A passing postrun or Request.acknowledged is not broker ACK evidence.
        assert (elapsed < 2) if with_wake else (elapsed >= 8)
        next(loop)
        assert message.acknowledged and counts["ack"] == 1
        assert counts["postrun"] == 1
        mark("ack_seen")
    finally:
        mark("cleanup_started")
        loop.close()
        if step is not None:
            step.shutdown(consumer)
        hub.remove_reader(idle_read)
        os.close(idle_read)
        os.close(idle_write)
        hub.close()
        asynchronous.set_event_loop(None)
        signals.task_received.disconnect(received)
        signals.task_postrun.disconnect(postrun)
        signals.task_failure.disconnect(failed)
        app.close()
        monkeypatch.undo()
        mark("cleanup_complete")


@pytest.mark.parametrize(
    ("with_wake", "diagnostics", "outcome"),
    [(False, False, "success")]
    + [
        (True, diagnostics, outcome)
        for diagnostics in (False, True)
        for outcome in ("success", "empty", "claim_error", "process_error")
    ],
)
def test_actual_worker_solo_task_ack_waits_for_next_ready_iteration(
    with_wake: bool, diagnostics: bool, outcome: str, tmp_path: Path
) -> None:
    trace = PhaseTrace(tmp_path / "callback-parent.jsonl")
    before = resources()
    child = multiprocessing.get_context("spawn").Process(
        target=callback_entry,
        args=(str(tmp_path / "callback-child.jsonl"), with_wake, diagnostics, outcome),
    )
    trace.mark("launch")
    child.start()
    owned_pid = child.pid
    timed_out = False
    try:
        child.join(timeout=20)
        trace.mark("join_returned")
        timed_out = child.exitcode is None
        if timed_out:
            trace.mark("timeout")
        assert child.exitcode == 0
    finally:
        trace.mark("cleanup_started")
        if child.is_alive():
            child.kill()
            child.join(timeout=5)
        code = child.exitcode
        child.close()
        trace.mark("cleanup_complete")
        receipt(
            tmp_path / "callback-receipt.json",
            {
                "kind": "callback",
                "owned_pid": owned_pid,
                "exit_code": code,
                "timed_out": timed_out,
                "before": before,
                "after": resources(),
            },
        )


def test_bootstep_refuses_non_solo_or_missing_hub_and_controls_remain_unchanged() -> None:
    solo = import_module("celery.concurrency.solo").TaskPool
    step = FixtureCallbackWake(SimpleNamespace())
    assert not step.include_if(SimpleNamespace(hub=None, pool=object.__new__(solo)))
    assert not step.include_if(SimpleNamespace(hub=object(), pool=object()))

    class OtherPool(solo):  # type: ignore[misc, valid-type]
        pass

    assert not step.include_if(SimpleNamespace(hub=object(), pool=object.__new__(OtherPool)))
    assert step.include_if(SimpleNamespace(hub=object(), pool=object.__new__(solo)))
    root = Path(__file__).resolve().parents[3]
    source = (root / "scripts/isolation/test_operator_ui_acceptance.py").read_text()
    assert "wait_for(complete, seconds=8)" in source
    assert "wait_for(consumer_ready)" in source

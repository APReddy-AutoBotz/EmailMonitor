"""Owned signal lifecycle and pinned-controller probes; no SQL or external broker."""

import os
import selectors
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from celery.concurrency.solo import TaskPool  # type: ignore[import-untyped]
from emailmonitor.runtime import entrypoint
from emailmonitor.runtime import worker as worker_module
from emailmonitor.runtime.signal_wake import SignalWakeState
from emailmonitor.runtime.worker import ServiceWorker
from kombu.asynchronous import Hub  # type: ignore[import-untyped]


@dataclass
class WakeFD:
    current: int = -1
    calls: list[int] = field(default_factory=list)
    fail: set[int] = field(default_factory=set)
    fail_after: set[int] = field(default_factory=set)

    def set(self, descriptor: int, *, warn_on_full_buffer: bool) -> int:
        assert warn_on_full_buffer is False
        self.calls.append(descriptor)
        ordinal = len(self.calls)
        if ordinal in self.fail:
            raise RuntimeError("private-setter-failure")
        previous, self.current = self.current, descriptor
        if ordinal in self.fail_after:
            raise RuntimeError("private-setter-failure")
        return previous


@dataclass
class Harness:
    hub: Any
    state: SignalWakeState
    setter: WakeFD
    consumer: Any

    def start(self) -> tuple[int, int]:
        self.state.start(self.consumer)
        owned = self.state.owned
        assert owned is not None and owned.read_fd is not None and owned.write_fd is not None
        return owned.read_fd, owned.write_fd


@pytest.fixture
def owned(monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    hub = Hub()
    _ = hub.poller
    setter = WakeFD()
    monkeypatch.setattr("emailmonitor.runtime.signal_wake.signal.set_wakeup_fd", setter.set)
    state = SignalWakeState()
    consumer = SimpleNamespace(hub=hub, pool=object.__new__(TaskPool))
    try:
        yield Harness(hub, state, setter, consumer)
    finally:
        # Only the fake process-wide setter is used by these unit cases. Resolve
        # its injected ambiguity explicitly before releasing retained test FDs.
        setter.current = -1
        if state.owned is not None:
            state.owned.installed = state.owned.uncertain = False
            try:
                state.owned.close()
            except RuntimeError:
                pass
        hub.close()


def closed(*descriptors: int) -> None:
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_repeated_signal_wake_lifecycle_and_handlers_are_unchanged(owned: Harness) -> None:
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    for _ in range(3):
        read_fd, write_fd = owned.start()
        assert not os.get_blocking(read_fd) and not os.get_blocking(write_fd)
        assert not os.get_inheritable(read_fd) and not os.get_inheritable(write_fd)
        assert owned.hub.readers[read_fd][0] == owned.state.owned.drain  # type: ignore[union-attr]
        assert owned.setter.current == write_fd
        owned.state.close()
        owned.state.close()
        assert owned.setter.current == -1
        assert read_fd not in owned.hub.readers
        assert not owned.hub.on_close
        closed(read_fd, write_fd)
    assert {sig: signal.getsignal(sig) for sig in handlers} == handlers
    assert not owned.state.failed


@pytest.mark.parametrize("mode", ["pool", "hub", "closed-hub", "thread"])
def test_unsupported_signal_wake_shape_fails_before_allocating(
    owned: Harness, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    allocate = MagicMock(side_effect=AssertionError("must not allocate"))
    monkeypatch.setattr("emailmonitor.runtime.signal_wake.os.pipe2", allocate)
    if mode == "pool":
        owned.consumer.pool = object()
    elif mode == "hub":
        owned.consumer.hub = SimpleNamespace()
    elif mode == "closed-hub":
        owned.hub.close()
    if mode == "thread":
        errors: list[BaseException] = []

        def start() -> None:
            try:
                owned.state.start(owned.consumer)
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=start)
        thread.start()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], RuntimeError)
    else:
        with pytest.raises(RuntimeError, match="Main-thread solo"):
            owned.state.start(owned.consumer)
    assert owned.state.failed and owned.state.owned is None
    allocate.assert_not_called()


@pytest.mark.parametrize("partial", [False, True])
def test_reader_is_registered_before_install_and_partial_registration_rolls_back(
    owned: Harness, monkeypatch: pytest.MonkeyPatch, partial: bool
) -> None:
    original = owned.hub.add_reader
    descriptors: list[int] = []

    def fail(descriptor: int, callback: object) -> None:
        descriptors.append(descriptor)
        if partial:
            original(descriptor, callback)
        raise ValueError("primary-reader-registration")

    monkeypatch.setattr(owned.hub, "add_reader", fail)
    with pytest.raises(ValueError, match="primary-reader-registration"):
        owned.state.start(owned.consumer)
    assert owned.state.failed and owned.setter.calls == []
    assert not owned.hub.readers and not owned.hub.on_close
    closed(*descriptors)
    assert owned.state.owned is not None and owned.state.owned.write_fd is None


def test_pipe_allocation_failure_has_no_registration_or_setter_side_effect(
    owned: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = OSError("private-allocation-failure")
    monkeypatch.setattr("emailmonitor.runtime.signal_wake.os.pipe2", MagicMock(side_effect=primary))
    with pytest.raises(OSError) as caught:
        owned.state.start(owned.consumer)
    assert caught.value is primary
    assert owned.state.failed and owned.setter.calls == []
    assert not owned.hub.readers and not owned.hub.on_close


def test_foreign_wake_owner_is_restored_and_refused(owned: Harness) -> None:
    foreign_read, foreign_write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        owned.setter.current = foreign_write
        with pytest.raises(RuntimeError, match="Foreign signal wake"):
            owned.state.start(owned.consumer)
        assert owned.state.failed and owned.setter.current == foreign_write
        assert owned.setter.calls[-1] == foreign_write
        assert owned.state.owned is not None and owned.state.owned.closed
        os.fstat(foreign_read)
        os.fstat(foreign_write)
        assert not owned.hub.readers and not owned.hub.on_close
    finally:
        os.close(foreign_read)
        os.close(foreign_write)


def test_replaced_wake_owner_is_preserved_and_failure_latched(owned: Harness) -> None:
    read_fd, write_fd = owned.start()
    foreign_read, foreign_write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        owned.setter.current = foreign_write
        with pytest.raises(RuntimeError, match="cleanup failed"):
            owned.state.close()
        assert owned.state.failed and owned.setter.current == foreign_write
        assert owned.setter.calls[-2:] == [-1, foreign_write]
        closed(read_fd, write_fd)
        os.fstat(foreign_read)
        os.fstat(foreign_write)
        with pytest.raises(RuntimeError, match="lifecycle failed"):
            owned.state.start(owned.consumer)
    finally:
        os.close(foreign_read)
        os.close(foreign_write)


@pytest.mark.parametrize("after", [False, True])
def test_install_failure_retains_owned_descriptors_when_outcome_is_uncertain(
    owned: Harness, after: bool
) -> None:
    (owned.setter.fail_after if after else owned.setter.fail).add(1)
    with pytest.raises(RuntimeError, match="private-setter-failure") as caught:
        owned.state.start(owned.consumer)
    assert "startup cleanup failed" in caught.value.__notes__[0]
    wake = owned.state.owned
    assert wake is not None and wake.uncertain and owned.state.failed
    assert wake.read_fd is not None and wake.write_fd is not None
    os.fstat(wake.read_fd)
    os.fstat(wake.write_fd)
    with pytest.raises(RuntimeError, match="ownership remains uncertain"):
        owned.state.close()
    assert len(owned.setter.calls) == 1


@pytest.mark.parametrize("mode", ["restore", "foreign-start", "replacement-restore"])
def test_failed_restoration_never_closes_potentially_installed_descriptors(
    owned: Harness, mode: str
) -> None:
    foreign_read, foreign_write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if mode == "foreign-start":
            owned.setter.current = foreign_write
            owned.setter.fail.add(2)
            with pytest.raises(RuntimeError, match="Foreign signal wake"):
                owned.state.start(owned.consumer)
        else:
            owned.start()
            if mode == "replacement-restore":
                owned.setter.current = foreign_write
                owned.setter.fail.add(3)
            else:
                owned.setter.fail.add(2)
            with pytest.raises(RuntimeError, match="restoration failed"):
                owned.state.close()
        wake = owned.state.owned
        assert wake is not None and wake.uncertain and not wake.closed and owned.state.failed
        assert wake.read_fd is not None and wake.write_fd is not None
        os.fstat(wake.read_fd)
        os.fstat(wake.write_fd)
        os.fstat(foreign_read)
        os.fstat(foreign_write)
    finally:
        os.close(foreign_read)
        os.close(foreign_write)


@pytest.mark.parametrize("action", ["close", "reset"])
def test_hub_close_and_reset_restore_before_close_without_mutating_hooks(
    owned: Harness, action: str
) -> None:
    read_fd, write_fd = owned.start()
    getattr(owned.hub, action)()
    assert owned.setter.current == -1 and not owned.state.failed
    assert owned.state.owned is not None and owned.state.owned.closed
    closed(read_fd, write_fd)
    owned.state.close()
    assert not owned.hub.on_close
    if action == "reset":
        owned.start()
        owned.state.close()


def test_hub_close_failure_latches_and_still_runs_other_owners(owned: Harness) -> None:
    read_fd, write_fd = owned.start()
    owned.setter.fail.add(2)
    calls: list[str] = []
    owned.hub.on_close.add(lambda _: calls.append("other-owner-closed"))
    owned.hub.close()
    assert calls == ["other-owner-closed"]
    assert owned.state.failed and owned.state.owned is not None
    assert owned.state.owned.uncertain
    os.fstat(read_fd)
    os.fstat(write_fd)


@pytest.mark.parametrize("mode", ["error", "eof"])
def test_reader_failure_detaches_then_closes_and_preserves_primary(
    owned: Harness, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    read_fd, write_fd = owned.start()
    primary = OSError("private-read-failure")

    def read(descriptor: int, size: int) -> bytes:
        assert descriptor == read_fd and size == 4096
        if mode == "error":
            raise primary
        return b""

    monkeypatch.setattr("emailmonitor.runtime.signal_wake.os.read", read)
    assert owned.state.owned is not None
    with pytest.raises((OSError, RuntimeError)) as caught:
        owned.state.owned.drain()
    if mode == "error":
        assert caught.value is primary
    assert owned.state.failed and owned.setter.current == -1
    closed(read_fd, write_fd)


def test_empty_and_full_pipe_are_bounded_wake_only_operations(owned: Harness) -> None:
    read_fd, write_fd = owned.start()
    assert owned.state.owned is not None
    owned.state.owned.drain()
    total = 0
    while True:
        try:
            total += os.write(write_fd, b"x" * 4096)
            assert total <= 1_048_576
        except BlockingIOError:
            break
    assert total > 0
    owned.state.owned.drain()
    assert os.write(write_fd, b"x") == 1
    assert not owned.state.failed
    owned.state.close()
    closed(read_fd, write_fd)


def test_unregister_failure_still_attempts_both_owned_closes(
    owned: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    read_fd, write_fd = owned.start()
    monkeypatch.setattr(
        owned.hub, "remove_reader", MagicMock(side_effect=RuntimeError("private-remove-failure"))
    )
    with pytest.raises(RuntimeError, match="cleanup failed"):
        owned.state.close()
    assert owned.setter.current == -1 and owned.state.failed
    closed(read_fd, write_fd)


def test_hook_removal_failure_does_not_skip_reader_or_descriptor_cleanup(
    owned: Harness,
) -> None:
    class FailingHooks(set[Any]):
        def discard(self, element: Any) -> None:
            raise RuntimeError("private-hook-removal-failure")

    read_fd, write_fd = owned.start()
    original = owned.hub.on_close
    owned.hub.on_close = FailingHooks(original)
    try:
        with pytest.raises(RuntimeError, match="cleanup failed"):
            owned.state.close()
        assert owned.state.failed and owned.setter.current == -1
        assert read_fd not in owned.hub.readers
        closed(read_fd, write_fd)
    finally:
        owned.hub.on_close = original


def test_first_descriptor_close_failure_still_attempts_second_once(
    owned: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    read_fd, write_fd = owned.start()
    original = os.close
    calls: list[int] = []

    def close(descriptor: int) -> None:
        calls.append(descriptor)
        original(descriptor)
        if descriptor == read_fd:
            raise OSError("private-close-failure")

    monkeypatch.setattr("emailmonitor.runtime.signal_wake.os.close", close)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        owned.state.close()
    assert calls == [read_fd, write_fd]
    assert owned.state.failed and owned.setter.current == -1
    assert owned.state.owned is not None
    owned.state.owned.close()
    assert calls == [read_fd, write_fd]
    closed(read_fd, write_fd)


@pytest.mark.parametrize("late", [False, True])
def test_entrypoint_rejects_latched_signal_cleanup_failure_and_closes_pools(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], late: bool
) -> None:
    worker = object.__new__(ServiceWorker)
    worker.closed = False
    worker.signal_wake = SignalWakeState()
    worker.signal_wake.failed = not late
    worker.application = MagicMock()
    worker.database = MagicMock()
    controller = worker.application.Worker.return_value
    controller.exitcode = 0
    if late:
        controller.stop.side_effect = lambda: setattr(worker.signal_wake, "failed", True)
    monkeypatch.setattr(worker_module, "ServiceWorker", lambda _: worker)
    monkeypatch.setattr(entrypoint, "load_config", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["service", "worker", "--config", "unused.json"])
    assert entrypoint.main() == 1
    assert capsys.readouterr().err == (
        ("" if late else "service_runtime_failed\n") + "service_runtime_cleanup_failed\n"
    )
    controller.stop.assert_called_once()
    worker.application.close.assert_called_once()
    worker.database.engine.dispose.assert_called_once()


CONTROLLER_PROBE = """
import os, signal, sys, time
from celery import Celery, bootsteps, signals
sys.path.insert(0, sys.argv[1])
from emailmonitor.jobs.callback_wake import FixtureCallbackWake
from emailmonitor.runtime.signal_wake import SignalWakeState, register_signal_wake
app = Celery("synthetic-signal-probe", broker="memory://", backend=None)
app.conf.update(worker_enable_remote_control=False, worker_send_task_events=False,
                worker_hijack_root_logger=False)
app.steps["consumer"].add(FixtureCallbackWake)
state = SignalWakeState()
register_signal_wake(app, state)
class Reconcile(bootsteps.StartStopStep):
    requires = ("celery.worker.consumer.tasks:Tasks",)
    def start(self, consumer):
        self.timer = consumer.timer.call_repeatedly(5.0, lambda: None)
    def stop(self, consumer):
        self.timer.cancel()
    shutdown = terminate = stop
app.steps["consumer"].add(Reconcile)
def ready(sender, **kwargs):
    original = signal.getsignal(signal.SIGTERM)
    assert original.__name__ == "worker_Warm"
    def before_poll():
        sender.hub.on_tick.discard(before_poll)
        print("POLL_READY", flush=True)
        if sys.argv[2] == "full":
            while True:
                try:
                    os.write(state.owned.write_fd, b"x" * 4096)
                except BlockingIOError:
                    break
            os.kill(os.getpid(), signal.SIGTERM)
        assert signal.getsignal(signal.SIGTERM) is original
    sender.hub.on_tick.add(before_poll)
signals.worker_ready.connect(ready, weak=False)
controller = app.Worker(pool="solo", concurrency=1, use_eventloop=True,
    loglevel="CRITICAL", without_gossip=True, without_mingle=True,
    without_heartbeat=True, redirect_stdouts=False, quiet=True)
controller.start()
assert controller.exitcode == 0
state.require_clean()
controller.stop()
state.close()
app.close()
assert signal.set_wakeup_fd(-1, warn_on_full_buffer=False) == -1
print("CLEAN_EXIT", flush=True)
"""


@pytest.mark.parametrize("mode", ["normal", "full"])
def test_real_pinned_solo_controller_observes_sigterm_with_original_five_second_bound(
    mode: str,
) -> None:
    """Synthetic memory transport selects the real async hub; no RabbitMQ claim."""
    source = Path(__file__).resolve().parents[1] / "src"
    running = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", CONTROLLER_PROBE, str(source), mode],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    try:
        assert running.stdout is not None
        with selectors.DefaultSelector() as reader:
            reader.register(running.stdout, selectors.EVENT_READ)
            assert reader.select(timeout=5), "Pinned synthetic controller did not become ready"
            assert running.stdout.readline() == b"POLL_READY\n"
        if mode == "normal":
            # Ensure the signal arrives in the idle poll rather than before it.
            time.sleep(0.01)
            running.terminate()
        assert running.wait(timeout=5) == 0
        output, error = running.communicate(timeout=1)
        assert output.endswith(b"CLEAN_EXIT\n")
        assert output.count(b"Warm shutdown") == 1
        assert b"Exception ignored" not in error
    finally:
        if running.poll() is None:
            running.kill()
            running.wait(timeout=5)

"""Owned signal wake for the pinned main-thread solo worker's asynchronous hub.

Celery's handlers retain all shutdown semantics. CPython writes a wake byte so
its warm-shutdown flag is observed without waiting for the reconciliation timer.
The pipe is independent of the fixture callback adapter and owns no broker I/O.
The process-wide API has no getter: ownership inspection uses a main-thread swap,
assuming the unchanged Celery handlers do not themselves replace the wake FD.
Foreign descriptor identity is restored on refusal; its prior warning flag is
not observable, so exact warning-flag restoration cannot be promised.
"""

import os
import signal
import threading
from typing import Any

from celery import bootsteps
from celery.concurrency.solo import TaskPool  # type: ignore[import-untyped]
from kombu.asynchronous import Hub  # type: ignore[import-untyped]


class SignalWakeState:
    """One live pipe at most; a lifecycle failure remains fatal after reconnect."""

    def __init__(self) -> None:
        self.failed = False
        self.owned: SignalWake | None = None

    def require_clean(self) -> None:
        if self.failed:
            raise RuntimeError("Worker signal wake lifecycle failed")

    def start(self, consumer: Any) -> None:
        self.require_clean()
        if self.owned is not None:
            self.owned.close()
        hub = getattr(consumer, "hub", None)
        if (
            threading.current_thread() is not threading.main_thread()
            or type(getattr(consumer, "pool", None)) is not TaskPool
            or type(hub) is not Hub
            or getattr(hub, "_poller", None) is None
            or not callable(getattr(hub, "_register_fd", None))
            or not callable(getattr(hub, "_unregister_fd", None))
            or not isinstance(getattr(hub, "readers", None), dict)
            or not isinstance(getattr(hub, "on_close", None), set)
        ):
            self.failed = True
            raise RuntimeError("Main-thread solo worker with live pinned hub required")
        # Keep the owner reachable even when partial startup must retain its FDs.
        self.owned = SignalWake(hub, self)
        self.owned.start()

    def close(self) -> None:
        if self.owned is not None:
            self.owned.close()
        self.require_clean()


class SignalWake:
    """Restore process-wide wake ownership before closing either owned FD."""

    def __init__(self, hub: Any, state: SignalWakeState) -> None:
        self.hub = hub
        self.state = state
        self.read_fd: int | None = None
        self.write_fd: int | None = None
        self.previous = -1
        self.installed = False
        self.uncertain = False
        self.closed = False

    def start(self) -> None:
        try:
            self.read_fd, self.write_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
            # The reader and close hook must exist before signals can write.
            self.hub.add_reader(self.read_fd, self.drain)
            self.hub.on_close.add(self.on_hub_close)
            try:
                self.previous = signal.set_wakeup_fd(self.write_fd, warn_on_full_buffer=False)
            except BaseException:
                # Conservatively retain descriptors if an installation failure
                # leaves the process-wide ownership outcome unconfirmed.
                self.uncertain = True
                raise
            self.installed = True
            if self.previous != -1:
                raise RuntimeError("Foreign signal wake owner refused")
        except BaseException as primary:
            self.state.failed = True
            try:
                self.close()
            except BaseException:
                BaseException.add_note(primary, "Worker signal wake startup cleanup failed")
            raise

    def drain(self) -> None:
        if self.closed:
            return
        assert self.read_fd is not None
        try:
            # One bounded read. A full pipe is already a sufficient wake; bytes
            # carry no application meaning and further bytes remain readable.
            if not os.read(self.read_fd, 4096):
                raise RuntimeError("Worker signal wake pipe closed")
        except BlockingIOError:
            pass
        except BaseException as primary:
            self.state.failed = True
            try:
                self.close()
            except BaseException:
                BaseException.add_note(primary, "Worker signal wake reader cleanup failed")
            raise

    def on_hub_close(self, hub: Any) -> None:
        # Kombu closes its poller before iterating this set. Do not mutate the
        # set or reopen the poller here; later stop removes the inert close hook.
        try:
            self.close(from_hub=True)
        except BaseException:
            # Hub.close must still run the other owners' close hooks. The
            # independently retained latch makes the CLI reject a clean exit.
            self.state.failed = True

    def _restore(self) -> bool:
        """Return whether the expected ownership was intact; never keep a foreign FD."""
        if not self.installed:
            return True
        assert self.write_fd is not None
        try:
            observed = signal.set_wakeup_fd(self.previous, warn_on_full_buffer=False)
            if observed != self.write_fd:
                # Python has no getter. Undo our inspection swap immediately
                # instead of leaving another owner's wake descriptor replaced.
                displaced = signal.set_wakeup_fd(observed, warn_on_full_buffer=False)
                if displaced != self.previous:
                    raise RuntimeError("Signal wake ownership changed during restoration")
                self.installed = False
                self.state.failed = True
                return False
            self.installed = False
            return True
        except BaseException:
            # A failed/ambiguous restore must never close a descriptor which
            # might still receive interpreter writes after its number is reused.
            self.uncertain = True
            self.state.failed = True
            raise RuntimeError("Worker signal wake restoration failed") from None

    def close(self, *, from_hub: bool = False) -> None:
        if self.closed:
            if not from_hub:
                try:
                    self.hub.on_close.discard(self.on_hub_close)
                except BaseException:
                    self.state.failed = True
                    raise RuntimeError("Worker signal wake hook cleanup failed") from None
            return
        if self.uncertain:
            self.state.failed = True
            raise RuntimeError("Worker signal wake ownership remains uncertain")
        intact = self._restore()
        self.closed = True
        errors = not intact
        if not from_hub:
            try:
                self.hub.on_close.discard(self.on_hub_close)
            except BaseException:
                errors = True
            try:
                if self.read_fd is not None:
                    self.hub.remove_reader(self.read_fd)
            except BaseException:
                errors = True
        read_fd, write_fd = self.read_fd, self.write_fd
        # Never retry close on a descriptor number which could have been reused.
        self.read_fd = self.write_fd = None
        for descriptor in (read_fd, write_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except BaseException:
                    errors = True
        if errors:
            self.state.failed = True
            raise RuntimeError("Worker signal wake cleanup failed")


def register_signal_wake(application: Any, state: SignalWakeState) -> None:
    """Register only on the separately owned service worker, never publisher/API."""

    class SignalWakeStep(bootsteps.StartStopStep):  # type: ignore[misc]
        requires = ("celery.worker.consumer.tasks:Tasks",)

        def start(self, consumer: Any) -> None:
            state.start(consumer)

        def stop(self, consumer: Any) -> None:
            state.close()

        shutdown = stop
        terminate = stop

    application.steps["consumer"].add(SignalWakeStep)

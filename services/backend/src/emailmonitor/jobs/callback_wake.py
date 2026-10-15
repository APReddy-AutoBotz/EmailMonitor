"""Wake the pinned synthetic solo worker when a ready callback queues another.

Kombu 5.6.2 drains one ready snapshot before polling. A synchronous solo task
can enqueue its original late-ACK promise during that drain. The next poll must
be readable without changing its timeout or running any callback out of order.
This is a same-event-loop-thread adapter, not a cross-thread call_soon API.
"""

import os
from contextlib import suppress
from typing import Any

from celery import bootsteps
from celery.concurrency.solo import TaskPool  # type: ignore[import-untyped]

_ATTRIBUTE = "_emailmonitor_callback_wake"


class ReadyCallbackWake:
    """Own exactly two nonblocking, close-on-exec FDs and at most one wake byte."""

    def __init__(self, hub: Any) -> None:
        # These two private fields are deliberately pinned integration points.
        # Refuse an incompatible hub before allocating or changing callbacks.
        if not isinstance(getattr(hub, "_ready", None), set) or not all(
            callable(getattr(getattr(hub, "_ready_lock", None), name, None))
            for name in ("__enter__", "__exit__")
        ):
            raise RuntimeError("Unsupported fixture worker ready queue")
        self.hub = hub
        self.closed = False
        self.signaled = False
        self.read_fd: int | None = None
        self.write_fd: int | None = None
        self.read_fd, self.write_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            hub.add_reader(self.read_fd, self.drain)
            hub.on_tick.add(self.before_poll)
            hub.on_close.add(self.on_hub_close)
        except BaseException:
            # Preserve the original installation failure; always attempt both
            # owned closes even when registration only partially succeeded.
            with suppress(Exception):
                self.close()
            raise

    @classmethod
    def install(cls, hub: Any) -> "ReadyCallbackWake":
        existing = getattr(hub, _ATTRIBUTE, None)
        if existing is not None:
            if not isinstance(existing, cls):
                raise RuntimeError("Unexpected fixture worker wake owner")
            if not existing.closed:
                return existing
            existing.close()
        wake = cls(hub)
        setattr(hub, _ATTRIBUTE, wake)
        return wake

    def before_poll(self) -> None:
        if self.closed or self.signaled:
            return
        with self.hub._ready_lock:
            pending = bool(self.hub._ready)
        if pending:
            assert self.write_fd is not None
            try:
                if os.write(self.write_fd, b"\0") != 1:
                    raise RuntimeError("Incomplete fixture worker wake")
            except BlockingIOError:
                # An already readable pipe needs no second wake byte.
                pass
            except BaseException:
                with suppress(Exception):
                    self.close()
                raise
            self.signaled = True

    def drain(self) -> None:
        if self.closed:
            return
        assert self.read_fd is not None
        try:
            if os.read(self.read_fd, 1) == b"":
                raise RuntimeError("Closed fixture worker wake pipe")
        except BlockingIOError:
            pass
        except BaseException:
            with suppress(Exception):
                self.close()
            raise
        self.signaled = False

    def on_hub_close(self, hub: Any) -> None:
        # Hub.close iterates on_close directly AFTER clearing readers and
        # closing the poller. Do not mutate that set or recreate its poller.
        # One inert hook remains until stop/shutdown or reconnect installation.
        self._close(from_hub=True)

    def close(self) -> None:
        self._close(from_hub=False)

    def _close(self, *, from_hub: bool) -> None:
        self.hub.on_tick.discard(self.before_poll)
        if not from_hub:
            self.hub.on_close.discard(self.on_hub_close)
            if getattr(self.hub, _ATTRIBUTE, None) is self:
                delattr(self.hub, _ATTRIBUTE)
        if self.closed:
            return
        self.closed = True
        self.signaled = False
        read_fd, write_fd = self.read_fd, self.write_fd
        self.read_fd = self.write_fd = None
        try:
            if not from_hub and read_fd is not None:
                self.hub.remove_reader(read_fd)
        finally:
            try:
                if read_fd is not None:
                    os.close(read_fd)
            finally:
                if write_fd is not None:
                    os.close(write_fd)


class FixtureCallbackWake(bootsteps.StartStopStep):  # type: ignore[misc]
    """Consumer lifecycle hook registered only by the explicit fixture factory."""

    requires = ("celery.worker.consumer.tasks:Tasks",)

    def __init__(self, consumer: Any, **kwargs: Any) -> None:
        super().__init__(consumer, **kwargs)
        self.wake: ReadyCallbackWake | None = None

    def include_if(self, consumer: Any) -> bool:
        return consumer.hub is not None and type(consumer.pool) is TaskPool

    def start(self, consumer: Any) -> None:
        if self.wake is not None and self.wake.hub is not consumer.hub:
            self.wake.close()
        self.wake = ReadyCallbackWake.install(consumer.hub)

    def stop(self, consumer: Any) -> None:
        if self.wake is not None:
            self.wake.close()
            self.wake = None

    shutdown = stop
    terminate = stop

"""One bounded real solo worker, owning the controlled gateway pipe until joined."""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from importlib import import_module
from typing import Any, cast

from emailmonitor.fetching.resources import HopResources
from emailmonitor.fetching.sciencedirect import AcquiredResponse, ProviderBoundary
from emailmonitor.jobs.broker import FixtureWorkerConfig, create_worker
from emailmonitor.jobs.queues import owned_queues
from emailmonitor.progress.execution import ExecutionDispatcher, Executor
from emailmonitor.progress.service import Progress
from transport_provider import ProviderProxy
from transport_rpc import OwnedProcess


class PipeOwner:
    """Revocable per-I/O gate; SQL callbacks never hold its cleanup lock."""

    def __init__(self, process: OwnedProcess) -> None:
        self.process = process
        self.owner: int | None = None
        self.closed = threading.Event()
        self.io = threading.Lock()
        self.active = False

    @property
    def poisoned(self) -> bool:
        return self.process.poisoned

    @poisoned.setter
    def poisoned(self, value: bool) -> None:
        self.process.poisoned = value

    def check(self) -> None:
        if self.closed.is_set() or self.owner != threading.get_ident():
            raise RuntimeError("Controlled gateway pipe ownership refused")

    def send(self, value: dict[str, object], deadline: float) -> None:
        with self.io:
            self.check()
            self.process.send(value, min(deadline, time.monotonic() + 20))

    def receive(self, deadline: float) -> dict[str, Any]:
        with self.io:
            self.check()
            return self.process.receive(min(deadline, time.monotonic() + 20))

    def revoke(self) -> None:
        self.closed.set()
        # Each admitted pipe call has the existing at-most20s deadline. Never
        # hold this lock across SQL callbacks or the isolated parser.
        if not self.io.acquire(timeout=25):
            raise RuntimeError("Controlled gateway pipe did not relinquish I/O")
        try:
            if self.active:
                self.process.poisoned = True
        finally:
            self.io.release()

    def acquire(self, boundary: ProviderBoundary, *, resources: HopResources) -> AcquiredResponse:
        self.check()
        self.active = True
        try:
            # The proxy uses only poisoned/send/receive on this owned capability.
            return ProviderProxy(cast(OwnedProcess, self)).acquire(boundary, resources=resources)
        finally:
            self.active = False


@contextmanager
def controlled_worker(
    config: FixtureWorkerConfig,
    gateway: OwnedProcess,
    compose: Callable[[Progress, PipeOwner], Executor],
) -> Iterator[Any]:
    ready = threading.Event()
    failures: list[BaseException] = []
    pipe = PipeOwner(gateway)

    def executor(progress: Progress) -> Executor:
        if pipe.owner != threading.get_ident():
            raise RuntimeError("Controlled gateway belongs exclusively to the solo worker")
        return compose(progress, pipe)

    app, ledger = create_worker(config, executor_factory=executor)
    controller: Any = None

    def work() -> None:
        pipe.owner = threading.get_ident()
        app.set_current()
        try:
            controller.start()
        except BaseException as error:
            failures.append(error)
        finally:
            ready.set()

    state: Any = import_module("celery.worker.state")
    thread = threading.Thread(target=work, name="controlled-provider-solo", daemon=True)
    previous_termination = state.should_terminate
    try:
        # Standard registered tasks and genuine broker delivery, never eager/manual execution.
        app.finalize()
        controller = app.WorkController(
            pool="solo",
            concurrency=1,
            queues=owned_queues(config.queue),
            hostname=config.queue + "@controlled",
            without_heartbeat=True,
            without_mingle=True,
            without_gossip=True,
            ready_callback=lambda _: ready.set(),
        )
        thread.start()
        # Unlike celery.contrib.testing.worker.ensure_started, startup is bounded,
        # and the finally block also runs when readiness fails.
        if not ready.wait(20) or not thread.is_alive() or failures:
            raise RuntimeError("Controlled solo worker failed bounded readiness")
        yield app
        if failures or not thread.is_alive():
            raise RuntimeError("Controlled solo worker stopped unexpectedly")
    finally:
        state.should_terminate = 0
        try:
            pipe.revoke()
        finally:
            # Revocation failure must not skip the bounded join. Never dispose
            # resources while their worker is still alive or undo its stop flag.
            if thread.ident is not None:
                thread.join(timeout=150)
            if thread.is_alive():
                raise RuntimeError("Controlled solo worker did not release gateway ownership")
            state.should_terminate = previous_termination
            try:
                with app.connection_for_write() as connection:
                    channel = connection.channel()
                    try:
                        for queue in owned_queues(config.queue):
                            channel.queue_delete(queue=queue)
                            channel.exchange_delete(exchange=queue)
                    finally:
                        channel.close()
            finally:
                try:
                    app.close()
                finally:
                    ledger.database.engine.dispose()


@contextmanager
def provider_worker(config: FixtureWorkerConfig, gateway: OwnedProcess) -> Iterator[Any]:
    with controlled_worker(
        config, gateway, lambda progress, pipe: ExecutionDispatcher(progress, pipe)
    ) as app:
        yield app

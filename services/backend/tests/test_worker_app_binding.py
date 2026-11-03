"""Worker-specific task closures cannot inherit another Celery app's authority."""

import inspect
import multiprocessing
import socket
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from emailmonitor.jobs import broker
from emailmonitor.jobs.broker import FixtureWorkerConfig
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.progress.execution import Executor, ExecutorFactory
from emailmonitor.progress.service import Progress

TASKS = ("retention", "export", "execute", "discover", "persist")
Binding = tuple[Any, FixtureWorkerConfig, Ledger, ExecutorFactory]


def assert_owned_closures(binding: Binding) -> None:
    app, config, ledger, factory = binding
    app.finalize()
    for name in TASKS:
        task = app.tasks["emailmonitor.fixture." + name]
        closure = inspect.getclosurevars(task.run).nonlocals
        assert closure["config"] is config, name
        assert closure["ledger"] is ledger, name
        if name == "execute":
            assert closure["executor_factory"] is factory


def isolated_bindings(simultaneous: bool) -> None:
    # No SQL service or broker is needed: inspect real finalized task registrations,
    # without invoking tasks or replacing Celery's global finalizer machinery.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(broker, "Database", lambda _: SimpleNamespace())

    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("Task registration must not connect to a service")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    bindings: list[Binding] = []

    def create(number: int) -> Binding:
        config = FixtureWorkerConfig(
            environment="test",
            database_url="postgresql+pg8000://fixture@127.0.0.1/test",
            broker_url="pyamqp://fixture@127.0.0.1/",
            organization=str(UUID(int=number)),
            session_token=f"synthetic-session-{number}",
            queue=f"em-fixture-binding-{number}",
        )

        def factory(progress: Progress) -> Executor:
            raise AssertionError("Registration must not invoke the execution factory")

        app, ledger = broker.create_worker(config, executor_factory=factory)
        binding = (app, config, ledger, factory)
        bindings.append(binding)
        return binding

    try:
        if simultaneous:
            # Both apps see the same global callbacks. With shared=True at least
            # one app necessarily inherits the wrong closure for every task name.
            create(1)
            create(2)
            for binding in bindings:
                assert_owned_closures(binding)
        else:
            # Match sequential controlled UI workers, including closing the first.
            for number in (1, 2):
                binding = create(number)
                assert_owned_closures(binding)
                binding[0].close()
    finally:
        for binding in bindings:
            binding[0].close()
        monkeypatch.undo()


@pytest.mark.parametrize("simultaneous", [True, False], ids=["simultaneous", "sequential"])
def test_registered_tasks_keep_worker_identity(simultaneous: bool) -> None:
    # Keep global Celery callbacks from other tests out of this regression.
    child = multiprocessing.get_context("spawn").Process(
        target=isolated_bindings, args=(simultaneous,)
    )
    child.start()
    try:
        child.join(timeout=20)
        assert child.exitcode == 0
    finally:
        if child.is_alive():
            child.kill()
            child.join(timeout=5)
        child.close()

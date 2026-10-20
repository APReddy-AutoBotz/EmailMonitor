"""Python-only execution composition preserves durable claim and default refusals."""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from emailmonitor.jobs.broker import FixtureWorkerConfig
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.progress.broker import ExecutionEvent, process
from emailmonitor.progress.execution import ExecutionDispatcher
from emailmonitor.progress.service import Progress, Work
from emailmonitor.sources import provider_documents as catalog
from pydantic import ValidationError
from spawn_probe import run_spawn_probe

ORG = UUID(int=1)


def event() -> dict[str, object]:
    return ExecutionEvent(
        organization_id=str(ORG),
        job_id=str(UUID(int=2)),
        item_id=str(UUID(int=3)),
        event_id=str(UUID(int=4)),
        generation=1,
    ).model_dump()


def worker_config(**changes: object) -> FixtureWorkerConfig:
    return FixtureWorkerConfig.model_validate(
        {
            "environment": "test",
            "database_url": "postgresql+pg8000://fixture@127.0.0.1/test",
            "broker_url": "pyamqp://fixture@127.0.0.1/",
            "organization": str(ORG),
            "session_token": "synthetic-session-only",
            "queue": "em-fixture-executor",
            **changes,
        }
    )


@pytest.mark.parametrize(
    "field", ["executor_factory", "provider", "transport", "import_path", "credentials"]
)
def test_configuration_and_queue_cannot_select_execution(field: str) -> None:
    with pytest.raises(ValidationError):
        worker_config(**{field: "untrusted.module:run"})
    with pytest.raises(ValidationError):
        ExecutionEvent.model_validate({**event(), field: "untrusted.module:run"})


@pytest.mark.parametrize(
    "route", sorted(catalog.URLS) + ["https://synthetic.publisher.example/article-1.html"]
)
def test_default_never_constructs_or_invokes_provider(
    route: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from emailmonitor.progress import execution

    calls: list[object] = []
    failure = RuntimeError("original default refusal")

    def fixture(work: Work, callback: object) -> str:
        calls.extend((work, callback))
        raise failure

    def unexpected(*args: object) -> None:
        pytest.fail("Default execution constructed provider journey")

    monkeypatch.setattr(execution, "ProviderJourney", unexpected)
    progress = cast(Progress, SimpleNamespace(process_fixture=fixture))
    work = cast(Work, SimpleNamespace(url=route))

    def callback() -> None:
        pass

    with pytest.raises(RuntimeError) as caught:
        ExecutionDispatcher(progress).process(work, after_observation=callback)
    assert caught.value is failure and calls == [work, callback]


@pytest.mark.parametrize("route", sorted(catalog.URLS))
@pytest.mark.parametrize("fails", [False, True])
def test_composed_provider_routes_exact_work_and_never_falls_back(
    route: str, fails: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from emailmonitor.progress import execution

    calls: list[object] = []
    failure = RuntimeError("controlled dispatch failed")
    work = cast(Work, SimpleNamespace(url=route))

    def callback() -> None:
        pass

    dispatch = object()
    progress = cast(Progress, object())

    class Journey:
        def __init__(self, actual_progress: object, actual_dispatch: object):
            assert actual_progress is progress and actual_dispatch is dispatch

        def process(
            self, actual: Work, *, after_observation: Callable[[], None] | None = None
        ) -> str:
            calls.extend((actual, after_observation))
            if fails:
                raise failure
            return "needs_review"

    monkeypatch.setattr(execution, "ProviderJourney", Journey)
    executor = ExecutionDispatcher(progress, cast(Any, dispatch))
    if fails:
        with pytest.raises(RuntimeError) as caught:
            executor.process(work, after_observation=callback)
        assert caught.value is failure
    else:
        assert executor.process(work, after_observation=callback) == "needs_review"
    assert calls == [work, callback]


@pytest.mark.parametrize(
    "condition", ["empty", "wrong_org", "generation", "malformed", "claim_error"]
)
def test_factory_is_never_called_before_successful_current_claim(condition: str) -> None:
    body = event()
    work = SimpleNamespace(lease=SimpleNamespace(generation=2 if condition == "generation" else 1))
    claims: list[object] = []
    failure = RuntimeError("claim denied")

    def claim(*args: object) -> object:
        claims.extend(args)
        if condition == "claim_error":
            raise failure
        return None if condition == "empty" else work

    def factory(progress: Progress) -> Any:
        pytest.fail("Factory ran without a valid claim")

    progress = cast(Progress, SimpleNamespace(claim=claim))
    if condition == "wrong_org":
        body["organization_id"] = str(UUID(int=99))
    if condition == "malformed":
        body["url"] = catalog.SEARCH_URL
    if condition == "empty":
        assert process(progress, ORG, body, executor_factory=factory) is False
    else:
        expected = (
            RuntimeError
            if condition == "claim_error"
            else ValidationError
            if condition == "malformed"
            else AuthorizationDenied
        )
        with pytest.raises(expected):
            process(progress, ORG, body, executor_factory=factory)
    assert bool(claims) is (condition not in {"wrong_org", "malformed"})


def test_factory_receives_current_progress_claim_and_callback_once() -> None:
    work = SimpleNamespace(lease=SimpleNamespace(generation=1))
    calls: list[object] = []

    def callback() -> None:
        pass

    progress = cast(Progress, SimpleNamespace(claim=lambda *args: work))

    class Executor:
        def process(
            self, claimed: Work, *, after_observation: Callable[[], None] | None = None
        ) -> str:
            calls.extend((claimed, after_observation))
            return "succeeded"

    def factory(actual: Progress) -> Executor:
        calls.append(actual)
        return Executor()

    assert process(progress, ORG, event(), executor_factory=factory, after_observation=callback)
    assert calls == [progress, work, callback]


def registered_composition() -> None:
    # Isolate Celery's process-global shared-task registry, like existing worker tests.
    from emailmonitor.jobs import broker

    monkeypatch = pytest.MonkeyPatch()
    calls: list[object] = []
    monkeypatch.setattr(broker, "Database", lambda _: SimpleNamespace())

    def factory(progress: Progress) -> object:
        return object()

    def execute(*args: object, **kwargs: object) -> bool:
        calls.append(kwargs["executor_factory"])
        return False

    monkeypatch.setattr(broker, "execute_process", execute)
    app, _ = broker.create_worker(worker_config(), executor_factory=cast(Any, factory))
    try:
        app.tasks["emailmonitor.fixture.execute"].run(event())
        assert calls == [factory]
    finally:
        app.close()
        monkeypatch.undo()


def test_normal_registered_task_retains_python_factory() -> None:
    run_spawn_probe(registered_composition)

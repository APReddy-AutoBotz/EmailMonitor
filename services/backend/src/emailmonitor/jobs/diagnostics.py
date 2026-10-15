"""Opt-in, fixed-category observations for the disposable solo UI worker only."""

import json
import sys
from collections.abc import Callable
from typing import Any, Literal

from celery import signals

from emailmonitor.jobs.queues import owned_queues

Stage = Literal[
    "worker_ready",
    "task_received",
    "execute_enter",
    "validated",
    "claim_enter",
    "claim_empty",
    "claim_acquired",
    "claim_error",
    "process_enter",
    "process_return",
    "process_error",
    "task_postrun",
    "task_failure",
]
STAGES: tuple[Stage, ...] = (
    "worker_ready",
    "task_received",
    "execute_enter",
    "validated",
    "claim_enter",
    "claim_empty",
    "claim_acquired",
    "claim_error",
    "process_enter",
    "process_return",
    "process_error",
    "task_postrun",
    "task_failure",
)
PREFIX = "EM_UI_WORKER_V1 "
MAX_SNAPSHOTS = 512
TASK = "emailmonitor.fixture.execute"


def emit(stage: Stage, callback: Callable[[Stage], None] | None) -> None:
    """Diagnostic failure must never change a task's return or original exception."""
    if callback is not None:
        try:
            callback(stage)
        except Exception:
            pass


def _write(value: str) -> None:
    # Bypass Celery's log redirection: one fixed-prefix line, no logger metadata.
    if sys.__stderr__ is not None:
        sys.__stderr__.write(value)
        sys.__stderr__.flush()


class WorkerDiagnostics:
    """Cumulative bounded snapshots; no identifiers, message data or exception text."""

    def __init__(
        self, application: Any, namespace: str, writer: Callable[[str], None] = _write
    ) -> None:
        self.application = application
        self.queues = owned_queues(namespace)
        self.writer = writer
        self.counts = dict.fromkeys(STAGES, 0)
        self.snapshots = 0

    def record(self, stage: Stage) -> None:
        if stage not in STAGES or self.snapshots >= MAX_SNAPSHOTS:
            return
        self.counts[stage] += 1
        self.snapshots += 1
        self.writer(
            PREFIX
            + json.dumps(
                {
                    "counts": self.counts,
                    "last_stage": stage,
                    "saturated": self.snapshots == MAX_SNAPSHOTS,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )

    def matches(self, task: Any, request: Any) -> bool:
        info = getattr(request, "delivery_info", None)
        expected = self.application.tasks.get(TASK)
        return (
            getattr(task, "app", None) is self.application
            and getattr(task, "name", None) == TASK
            and task is expected
            and type(info) is dict
            and info.get("routing_key") in self.queues
            # Pinned Celery publishes direct named queues through AMQP's
            # empty default exchange. Do not infer exchange from queue name.
            and info.get("exchange") == ""
        )

    def ready(self, sender: Any = None, **_: Any) -> None:
        consumer = getattr(sender, "task_consumer", None)
        queues = getattr(consumer, "queues", ())
        if getattr(sender, "app", None) is self.application and {
            getattr(queue, "name", None) for queue in queues
        } == set(self.queues):
            emit("worker_ready", self.record)

    def received(self, sender: Any = None, request: Any = None, **_: Any) -> None:
        if (
            getattr(sender, "app", None) is self.application
            and getattr(request, "app", None) is self.application
            and self.matches(getattr(request, "task", None), request)
        ):
            emit("task_received", self.record)

    def postrun(self, sender: Any = None, **_: Any) -> None:
        if self.matches(sender, getattr(sender, "request", None)):
            # Celery's pool callback/late broker acknowledgement occurs later.
            emit("task_postrun", self.record)

    def failure(self, sender: Any = None, **_: Any) -> None:
        if self.matches(sender, getattr(sender, "request", None)):
            emit("task_failure", self.record)

    def connect(self) -> None:
        # Weak bound-method receivers remain owned by this application's execute
        # closure, without retaining every created synthetic app globally.
        signals.worker_ready.connect(self.ready)
        signals.task_received.connect(self.received)
        signals.task_postrun.connect(self.postrun)
        signals.task_failure.connect(self.failure)

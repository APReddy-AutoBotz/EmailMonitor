"""Closed host stages for future installed acceptance metadata; no payload capture."""

from pathlib import Path
from typing import Literal, get_args

Stage = Literal[
    "package",
    "identity_and_roles",
    "configuration",
    "service_identity",
    "broker_setup",
    "api_startup",
    "api_readiness",
    "profile_and_session",
    "first_worker_readiness_and_stop",
    "restarted_worker_readiness",
    "browser_execution_and_owned_cleanup",
    "postconditions",
    "publisher_stop",
    "service_process_cleanup",
    "resource_cleanup",
    "complete",
]


class InstalledStage:
    def __init__(self) -> None:
        self.current: Stage = "package"
        self.failure: Stage | None = None

    def enter(self, stage: Stage) -> None:
        if type(stage) is not str or stage not in get_args(Stage):
            raise ValueError("Closed installed stage required")
        self.current = stage

    def fail(self) -> None:
        if self.failure is None:
            self.failure = self.current


def report_stage(stage: InstalledStage, destination: Path) -> None:
    value = stage.failure if stage.failure is not None else stage.current
    if type(value) is not str or value not in get_args(Stage):
        raise ValueError("Closed installed stage required")
    with destination.open("a", encoding="utf-8") as output:
        output.write("stage=" + value + "\n")

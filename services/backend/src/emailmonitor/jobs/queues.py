"""Closed synthetic phase routing. Queue names never supply tenant authority."""

import re
from typing import Literal

Phase = Literal["fixture_io", "parse", "export"]
PHASES: tuple[Phase, ...] = ("fixture_io", "parse", "export")


def phase_queue(namespace: str, phase: Phase) -> str:
    if not re.fullmatch(r"em-fixture-[a-z0-9-]{1,60}", namespace):
        raise ValueError("Owned synthetic queue namespace required")
    if phase not in ("fixture_io", "parse", "export"):
        raise ValueError("Unsupported synthetic worker phase")
    return namespace + "-" + phase.replace("_", "-")


def owned_queues(namespace: str) -> tuple[str, ...]:
    return (
        namespace,
        *(phase_queue(namespace, phase) for phase in PHASES),
    )

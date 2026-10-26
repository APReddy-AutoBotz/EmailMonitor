"""Elapsed event intervals never stand in for processing, effort or billing."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from emailmonitor.progress.timing import JobTiming, project_timing

STAMP = datetime(2026, 1, 1, tzinfo=UTC)


def timing(**changes: Any) -> JobTiming:
    args: dict[str, Any] = dict(
        organization=UUID(int=1),
        job=UUID(int=2),
        state="completed",
        revision=5,
        generation=2,
        queued_at=STAMP,
        terminal_at=STAMP + timedelta(seconds=12.5),
        queued_sequence=1,
        terminal_sequence=4,
        terminal_revision=5,
    )
    args.update(changes)
    return project_timing(**args)


def test_exact_retained_interval_includes_waiting_and_does_not_claim_cpu() -> None:
    value = timing()
    assert value.availability == "recorded" and value.elapsed_seconds == 12.5
    assert value.includes_waiting_and_pauses and value.queued_at == STAMP


@pytest.mark.parametrize("state", ["queued", "running", "paused", "pausing", "cancelling"])
def test_active_state_never_uses_an_old_terminal_event(state: str) -> None:
    value = timing(state=state)
    assert value.availability == "not_terminal" and value.elapsed_seconds is None
    assert value.queued_at is None and value.terminal_at is None


@pytest.mark.parametrize(
    "changes",
    [
        {"terminal_at": None},
        {"queued_at": None},
        {"terminal_revision": 4},
        {"terminal_at": STAMP - timedelta(seconds=1)},
        {"queued_sequence": 4},
        {"terminal_sequence": None},
        {"queued_at": STAMP.replace(tzinfo=None)},
    ],
)
def test_missing_conflicting_or_naive_observations_remain_unknown(changes: dict[str, Any]) -> None:
    value = timing(**changes)
    assert value.availability in {"not_recorded", "inconsistent"}
    assert value.elapsed_seconds is None and value.queued_at is None and value.terminal_at is None


def test_resume_and_new_generation_do_not_reset_the_observed_start() -> None:
    assert timing(generation=9).elapsed_seconds == 12.5
    assert timing(state="cancelled").availability == "recorded"
    assert timing(state="draft").availability == "not_started"


def test_committed_timing_schema_and_example_match_runtime() -> None:
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator, FormatChecker

    root = Path(__file__).resolve().parents[3]
    schema = json.loads((root / "contracts/job-timing.schema.json").read_text())
    raw = (root / "contracts/examples/job-timing.json").read_text()
    assert schema == JobTiming.model_json_schema()
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(json.loads(raw))
    assert JobTiming.model_validate_json(raw) == timing()

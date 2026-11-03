"""Pure progress truthfulness and job-scoped replay cursor regressions."""

from uuid import uuid4

import pytest
from emailmonitor.progress.state import (
    Outcome,
    completion,
    counts,
    cursor,
    parse_cursor,
    percentage,
)
from pydantic import ValidationError


@pytest.mark.parametrize("outcome", ["succeeded", "no_contact", "needs_review"])
def test_quality_outcomes_can_complete(outcome: Outcome) -> None:
    state = counts([outcome])
    assert completion(state, enumeration_stopped=True, discovery_complete=True) == "completed"
    assert percentage(state, True) == 100


@pytest.mark.parametrize(
    "outcome", ["policy_blocked", "access_blocked", "unsupported", "skipped", "failed", "cancelled"]
)
def test_execution_gaps_are_partial(outcome: Outcome) -> None:
    state = counts([outcome])
    assert (
        completion(state, enumeration_stopped=True, discovery_complete=True) == "completed_partial"
    )


@pytest.mark.parametrize("outcome", ["pending", "running", "retry_wait"])
def test_active_work_is_never_terminalized(outcome: Outcome) -> None:
    state = counts(["failed", outcome])
    assert completion(state, enumeration_stopped=True, discovery_complete=True) is None


def test_source_cap_and_unknown_total_never_claim_complete_percentage() -> None:
    state = counts(["no_contact", "succeeded"])
    assert percentage(state, False) is None
    assert (
        completion(state, enumeration_stopped=True, discovery_complete=False) == "completed_partial"
    )
    assert completion(state, enumeration_stopped=False, discovery_complete=False) is None


def test_positive_empty_exhaustion_can_complete_without_contact_claim() -> None:
    assert completion(counts([]), enumeration_stopped=True, discovery_complete=True) == "completed"


def test_invalid_durable_counts_refuse() -> None:
    with pytest.raises(ValidationError):
        counts(["invented"])  # type: ignore[list-item]
    with pytest.raises(ValidationError):
        counts(["pending"] * 501)
    original = counts(["no_contact"])
    with pytest.raises(ValidationError):
        type(original).model_validate({**original.model_dump(), "terminal": 0})


@pytest.mark.parametrize("sequence", [0, 1, 100, 9223372036854775807])
def test_cursor_round_trip(sequence: int) -> None:
    org, job = uuid4(), uuid4()
    assert parse_cursor(org, job, cursor(org, job, sequence)) == sequence
    assert parse_cursor(org, job, None) == 0


@pytest.mark.parametrize(
    "suffix", ["-1", "+1", "01", "1.0", "١", "1\n", "9223372036854775808", "0:1"]
)
def test_cursor_noncanonical_or_unbounded_refuses(suffix: str) -> None:
    org, job = uuid4(), uuid4()
    with pytest.raises(ValueError):
        parse_cursor(org, job, f"{org}/{job}:{suffix}")


def test_cross_job_cursor_refuses() -> None:
    with pytest.raises(ValueError):
        parse_cursor(uuid4(), uuid4(), cursor(uuid4(), uuid4(), 1))


def test_cross_tenant_same_job_cursor_refuses() -> None:
    job = uuid4()
    with pytest.raises(ValueError):
        parse_cursor(uuid4(), job, cursor(uuid4(), job, 1))

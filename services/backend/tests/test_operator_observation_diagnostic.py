"""Passive observation diagnostics preserve failures and emit only closed states."""

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from operator_ui_acceptance import finish_observation_trace, start_observation_trace
from operator_ui_protocol import DiagnosticFrame, ObservationTrace
from playwright.async_api import JSHandle, Locator
from pydantic import ValidationError

STATE = {
    "opener_connected": True,
    "region_connected": True,
    "dialog_present": False,
    "dialog_open": False,
    "quality": "missing",
}


@pytest.mark.parametrize(
    "payload",
    [
        {"states": [STATE], "truncated": False},
        {"states": [STATE, {**STATE, "opener_connected": False}], "truncated": True},
        {"states": [{**STATE, "quality": "private article text"}], "truncated": False},
        {"states": [STATE], "truncated": False, "url": "private"},
        RuntimeError("private exception details"),
    ],
)
def test_snapshot_cannot_replace_original_assertion(payload: object) -> None:
    trace = SimpleNamespace(evaluate=AsyncMock(side_effect=[payload]), dispose=AsyncMock())
    captured: object = None

    async def scenario() -> None:
        nonlocal captured
        try:
            raise AssertionError("original content assertion")
        finally:
            captured = await finish_observation_trace(cast(JSHandle, trace))

    with pytest.raises(AssertionError, match="^original content assertion$"):
        asyncio.run(scenario())
    trace.dispose.assert_awaited_once()
    if (
        isinstance(payload, dict)
        and payload.get("states") in ([STATE], [STATE, {**STATE, "opener_connected": False}])
        and "url" not in payload
    ):
        assert isinstance(captured, ObservationTrace)
        assert captured.model_dump() == payload
    else:
        assert captured == "unavailable"


def test_pending_setup_and_snapshot_do_not_change_failure() -> None:
    async def pending(_: str) -> object:
        await asyncio.Event().wait()
        return None

    opener = SimpleNamespace(evaluate_handle=pending)
    assert asyncio.run(start_observation_trace(cast(Locator, opener))) is None
    trace = SimpleNamespace(evaluate=pending, dispose=AsyncMock())
    assert asyncio.run(finish_observation_trace(cast(JSHandle, trace))) == "unavailable"
    trace.dispose.assert_awaited_once()


@pytest.mark.parametrize(
    "patch",
    [
        {"states": []},
        {"states": [STATE] * 9},
        {"truncated": "false"},
        {"states": [{**STATE, "opener_connected": 1}]},
        {"states": [{**STATE, "quality": "secret"}]},
    ],
)
def test_trace_grammar_rejects_unbounded_or_non_fixed_values(patch: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ObservationTrace.model_validate({"states": [STATE], "truncated": False, **patch})


@pytest.mark.parametrize(
    "patch",
    [
        {"stage": "evidence_review"},
        {"outcome_phase": "outcomes_actual_initial_focus"},
        {"error": "RuntimeError"},
        {"kind": "stage", "error": None},
    ],
)
def test_trace_only_attaches_to_original_content_failure(patch: dict[str, object]) -> None:
    frame = {
        "kind": "failure",
        "stage": "url_worker",
        "error": "AssertionError",
        "outcome_phase": "outcomes_actual_quality",
        "observation_trace": "unavailable",
    }
    assert DiagnosticFrame.model_validate(frame).observation_trace == "unavailable"
    with pytest.raises(ValidationError):
        DiagnosticFrame.model_validate({**frame, **patch})

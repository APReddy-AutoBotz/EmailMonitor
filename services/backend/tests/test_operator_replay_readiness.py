"""Deterministic replay/response ordering; actual DOM acceptance remains hosted."""

import asyncio
import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from operator_ui_acceptance import require_outcome_render, wait_outcome_replay
from operator_ui_protocol import ORIGIN, OutcomeReplayReadiness, ReplayRequest
from playwright.async_api import JSHandle, Page

ORG = "00000000-0000-4000-8000-000000000001"
JOB = "00000000-0000-4000-8000-000000000002"
ITEM = "00000000-0000-4000-8000-000000000003"
OTHER = "00000000-0000-4000-8000-000000000004"
CURSOR = f"{ORG}/{JOB}:7"


def request(state: OutcomeReplayReadiness, suffix: str, method: str = "GET") -> ReplayRequest:
    result = state.begin(ORIGIN + state.root + suffix, method)
    assert result is not None
    return result


def offer(state: OutcomeReplayReadiness, token: ReplayRequest, data: object) -> None:
    state.offer(token, 201 if token.kind == "create" else 200, json.dumps(data).encode())


def armed() -> OutcomeReplayReadiness:
    state = OutcomeReplayReadiness(ORG)
    creation = request(state, "/jobs", "POST")
    offer(state, creation, {"id": JOB})
    state.finish(creation, True)
    job = request(state, f"/jobs/{JOB}")
    offer(state, job, {"id": JOB, "generation": 1, "state": "completed"})
    state.finish(job, True)
    return state


def terminal(state: OutcomeReplayReadiness) -> ReplayRequest:
    stream = request(state, f"/jobs/{JOB}/events")
    state.headers(stream, {})
    event = {"organization_id": ORG, "job_id": JOB, "sequence": 7, "event_type": "job.finished"}
    state.offer(stream, 200, f"id: {CURSOR}\ndata: {json.dumps(event)}\n\n".encode())
    stream.render_before = SimpleNamespace(evaluate=AsyncMock(return_value=True))
    return stream


def progress_payload(**changes: object) -> dict[str, object]:
    return {
        "organization_id": ORG,
        "job_id": JOB,
        "generation": 1,
        "state": "completed",
        "last_sequence": 7,
        **changes,
    }


def outcomes_payload(**changes: object) -> dict[str, object]:
    return {
        "items": [
            {
                "organization_id": ORG,
                "job_id": JOB,
                "item_id": ITEM,
                "state": "no_contact",
                "batch_id": OTHER,
                **changes,
            }
        ],
        "next_cursor": None,
    }


def replies(state: OutcomeReplayReadiness) -> tuple[ReplayRequest, ReplayRequest, ReplayRequest]:
    progress = request(state, f"/jobs/{JOB}/progress")
    offer(state, progress, progress_payload())
    state.finish(progress, True)
    outcomes = request(state, f"/article-outcomes?job_id={JOB}&limit=25")
    outcomes.loading = True
    offer(state, outcomes, outcomes_payload())
    state.finish(outcomes, True)
    ack = request(state, f"/jobs/{JOB}/events")
    state.headers(ack, {"last-event-id": CURSOR})
    state.offer(ack, 200, b"")
    state.finish(ack, True)
    return progress, outcomes, ack


def ready() -> tuple[OutcomeReplayReadiness, ReplayRequest]:
    state = armed()
    stream = terminal(state)
    state.finish(stream, True)
    _, outcomes, _ = replies(state)
    assert state.ready() is outcomes
    return state, outcomes


def test_consumption_before_fulfill_returns_needs_every_successful_delivery() -> None:
    state = armed()
    stream = terminal(state)
    _, outcomes, _ = replies(state)
    assert state.ready() is None
    state.finish(stream, True)
    assert state.ready() is outcomes


def test_terminal_already_observed_before_wait_is_retained_without_reconnect() -> None:
    state, outcomes = ready()
    # Starting the wait does not reset already-current replay or create another request.
    assert state.ready() is outcomes
    assert state.cursor == CURSOR and state.generation == 1


@pytest.mark.parametrize("part", ["replay", "ack", "progress", "outcomes", "job_request"])
def test_incomplete_correlations_never_become_ready(part: str) -> None:
    state, _ = ready()
    token = getattr(state, part)
    token.delivered = False
    assert state.ready() is None


@pytest.mark.parametrize(
    "changes",
    [
        {"organization_id": OTHER},
        {"job_id": OTHER},
        {"generation": 2},
        {"generation": True},
        {"last_sequence": 6},
        {"last_sequence": True},
        {"state": "running"},
    ],
)
def test_progress_must_match_current_terminal_job_generation(changes: dict[str, object]) -> None:
    state, _ = ready()
    token = request(state, f"/jobs/{JOB}/progress")
    offer(state, token, progress_payload(**changes))
    state.finish(token, True)
    assert state.failed and state.ready() is None


@pytest.mark.parametrize(
    "changes",
    [
        {"organization_id": OTHER},
        {"job_id": OTHER},
        {"item_id": "arbitrary"},
        {"state": "running"},
        {"batch_id": None},
    ],
)
def test_outcome_identity_and_terminal_content_are_correlated(changes: dict[str, object]) -> None:
    state, _ = ready()
    token = request(state, f"/article-outcomes?job_id={JOB}&limit=25")
    token.loading = True
    offer(state, token, outcomes_payload(**changes))
    state.finish(token, True)
    assert state.failed and state.ready() is None


def test_old_epoch_cannot_satisfy_replaced_stream_even_with_same_cursor() -> None:
    state, old = ready()
    old_progress = state.progress
    stream = terminal(state)
    state.finish(stream, True)
    state.finish(old, True)
    state.finish(old_progress, True)
    assert state.ready() is None
    _, current, _ = replies(state)
    assert current is not old and state.ready() is current


def test_newer_request_retires_old_outcome_reply_and_loading_proof() -> None:
    state, old = ready()
    current = request(state, f"/article-outcomes?job_id={JOB}&limit=25")
    state.finish(old, True)
    assert state.ready() is None
    offer(state, current, outcomes_payload())
    state.finish(current, True)
    assert state.failed and state.ready() is None


def test_old_stream_headers_cannot_replace_newer_stream_epoch() -> None:
    state = armed()
    old = request(state, f"/jobs/{JOB}/events")
    current = request(state, f"/jobs/{JOB}/events")
    state.headers(current, {})
    epoch = state.epoch
    state.headers(old, {})
    assert state.epoch == epoch


def test_mismatched_ack_and_delivery_refusal_cannot_be_ready() -> None:
    state, _ = ready()
    ack = request(state, f"/jobs/{JOB}/events")
    state.headers(ack, {"last-event-id": f"{ORG}/{OTHER}:7"})
    assert state.failed and state.ready() is None
    state, _ = ready()
    state.finish(state.outcomes, False)
    assert state.ready() is None


@pytest.mark.parametrize("connected", [False, True])
def test_render_must_be_connected_and_still_owned_after_dom_read(connected: bool) -> None:
    state, proof = ready()

    async def evaluate(*args: object) -> bool:
        if connected:
            # Replacement during the DOM await must not reuse the old proof.
            request(state, f"/article-outcomes?job_id={JOB}&limit=25")
        return connected

    handle = SimpleNamespace(evaluate=evaluate)
    with pytest.raises(RuntimeError, match="correlation missing"):
        asyncio.run(require_outcome_render(cast(Page, None), state, proof, cast(JSHandle, handle)))


def test_wait_requires_actual_render_even_after_complete_network_receipts() -> None:
    state, _ = ready()
    handle = SimpleNamespace(evaluate=AsyncMock(return_value=False), dispose=AsyncMock())
    locator = SimpleNamespace(wait_for=AsyncMock(), element_handle=AsyncMock(return_value=handle))
    locator.first = locator
    locator.filter = lambda **kwargs: locator
    locator.get_by_role = lambda *args, **kwargs: locator
    page = SimpleNamespace(
        get_by_role=lambda *args, **kwargs: locator, get_by_text=lambda *args, **kwargs: locator
    )
    with pytest.raises(RuntimeError, match="correlation missing"):
        asyncio.run(wait_outcome_replay(cast(Page, page), state, asyncio.Event()))
    handle.dispose.assert_awaited_once()


def test_reply_before_terminal_offer_cannot_prove_post_replay_render() -> None:
    state = armed()
    premature = request(state, f"/article-outcomes?job_id={JOB}&limit=25")
    premature.loading = True
    stream = terminal(state)
    state.finish(stream, True)
    offer(state, premature, outcomes_payload())
    state.finish(premature, True)
    assert state.ready() is None
    _, current, _ = replies(state)
    assert current is not premature and state.ready() is current


def test_successful_dom_read_does_not_accept_wrong_network_generation() -> None:
    state, proof = ready()
    replacement = request(state, f"/jobs/{JOB}")
    offer(state, replacement, {"id": JOB, "generation": 2, "state": "completed"})
    state.finish(replacement, True)
    handle = SimpleNamespace(evaluate=AsyncMock(return_value=True))
    with pytest.raises(RuntimeError, match="correlation missing"):
        asyncio.run(require_outcome_render(cast(Page, None), state, proof, cast(JSHandle, handle)))
    handle.evaluate.assert_not_awaited()


def test_complete_network_and_current_render_prove_readiness() -> None:
    state, proof = ready()
    handle = SimpleNamespace(evaluate=AsyncMock(return_value=True), dispose=AsyncMock())
    locator = SimpleNamespace(wait_for=AsyncMock(), element_handle=AsyncMock(return_value=handle))
    locator.first = locator
    locator.filter = lambda **kwargs: locator
    locator.get_by_role = lambda *args, **kwargs: locator
    page = SimpleNamespace(
        get_by_role=lambda *args, **kwargs: locator, get_by_text=lambda *args, **kwargs: locator
    )
    result = asyncio.run(wait_outcome_replay(cast(Page, page), state, asyncio.Event()))
    assert result == (proof, cast(JSHandle, handle))
    handle.dispose.assert_not_awaited()


def test_incomplete_readiness_wait_cannot_return_a_visible_stale_row() -> None:
    state = armed()
    page = SimpleNamespace(get_by_text=AsyncMock())

    async def exercise() -> None:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(
                wait_outcome_replay(cast(Page, page), state, asyncio.Event()), timeout=0.01
            )

    asyncio.run(exercise())
    page.get_by_text.assert_not_called()


@pytest.mark.parametrize("continuation", [False, True])
def test_pending_stream_headers_immediately_retire_old_readiness(continuation: bool) -> None:
    state, proof = ready()
    stream = request(state, f"/jobs/{JOB}/events")
    assert state.ready() is None
    state.headers(stream, {"last-event-id": CURSOR} if continuation else {})
    assert (state.ready() is proof) == continuation


@pytest.mark.parametrize("kind", ["progress", "outcomes"])
def test_cancelled_render_request_can_be_replaced_without_hiding_refusals(kind: str) -> None:
    state, _ = ready()
    original = state.progress if kind == "progress" else state.outcomes
    state.finish(original, False)
    assert state.ready() is None
    _, replacement, _ = replies(state)
    assert state.ready() is replacement
    assert original is not state.progress and original is not state.outcomes
    state.offer(state.outcomes, 403, b"{}")
    replies(state)
    assert state.failed and state.ready() is None


def test_initial_loading_and_matching_response_do_not_prove_replay_remount() -> None:
    state, proof = ready()
    assert state.replay is not None
    state.replay.render_before = SimpleNamespace(evaluate=AsyncMock(return_value=False))
    current = SimpleNamespace(evaluate=AsyncMock(return_value=True))
    with pytest.raises(RuntimeError, match="has not replaced"):
        asyncio.run(require_outcome_render(cast(Page, None), state, proof, cast(JSHandle, current)))
    current.evaluate.assert_not_awaited()

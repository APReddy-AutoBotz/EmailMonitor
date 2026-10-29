"""Authored pagination must not begin on the pre-replay visible table."""

import ast
import asyncio
import inspect
import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from operator_ui_acceptance import (
    authored_outcome_paging,
    require_outcome_render,
    wait_outcome_replay,
)
from operator_ui_protocol import ORIGIN, AuthoredOutcomeReplayReadiness, ReplayRequest
from playwright.async_api import JSHandle, Page


def test_presence_activation_requires_replay_render_not_just_visible_table() -> None:
    function = ast.parse(inspect.getsource(authored_outcome_paging)).body[0]
    assert isinstance(function, ast.AsyncFunctionDef)
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    marker = next(
        node for node in calls if ast.unparse(node) == "checkpoint('outcomes_presence_keyboard')"
    )
    denied = next(
        node for node in calls if ast.unparse(node) == "checkpoint('outcomes_page_denied')"
    )
    readiness = [
        node
        for node in calls
        if isinstance(node.func, ast.Name)
        and node.func.id == "wait_outcome_replay"
        and denied.lineno < node.lineno < marker.lineno
    ]
    assert len(readiness) == 1, "the initial visible table can precede terminal replay"
    call = readiness[0]
    assert any(
        keyword.arg == "timeout" and ast.literal_eval(keyword.value) == 5
        for keyword in call.keywords
    )
    marker = next(
        node for node in calls if ast.unparse(node) == "checkpoint('outcomes_presence_keyboard')"
    )
    assert call.lineno < marker.lineno


def test_initial_pagination_waits_for_its_own_replay_render() -> None:
    function = ast.parse(inspect.getsource(authored_outcome_paging)).body[0]
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    start = next(
        node for node in calls if ast.unparse(node) == "checkpoint('outcomes_authored_load')"
    )
    first = next(node for node in calls if ast.unparse(node) == "checkpoint('outcomes_next_rows')")
    readiness = [
        node
        for node in calls
        if start.lineno < node.lineno < first.lineno
        and isinstance(node.func, ast.Name)
        and node.func.id == "wait_outcome_replay"
    ]
    assert len(readiness) == 1, "the initial table may precede its terminal replay"
    assert any(
        keyword.arg == "timeout" and ast.literal_eval(keyword.value) == 5
        for keyword in readiness[0].keywords
    )
    observes = [
        node
        for node in calls
        if start.lineno < node.lineno < first.lineno
        and ast.unparse(node) == "observe(readiness, None, None)"
    ]
    refresh = next(
        node
        for node in calls
        if start.lineno < node.lineno < first.lineno
        and isinstance(node.func, ast.Name)
        and node.func.id == "activate"
        and "Refresh current view" in ast.unparse(node)
    )
    assert len(observes) == 1 and observes[0].lineno < refresh.lineno < readiness[0].lineno


ORG = "00000000-0000-4000-8000-000000000011"
JOB = "00000000-0000-4000-8000-000000000012"
OTHER = "00000000-0000-4000-8000-000000000013"
CURSOR = f"{ORG}/{JOB}:7"


def request(state: AuthoredOutcomeReplayReadiness, suffix: str) -> ReplayRequest:
    token = state.begin(ORIGIN + state.root + suffix, "GET")
    assert token is not None
    return token


def offer(state: AuthoredOutcomeReplayReadiness, token: ReplayRequest, payload: object) -> None:
    state.offer(token, 200, json.dumps(payload).encode())
    state.finish(token, True)


def armed() -> AuthoredOutcomeReplayReadiness:
    state = AuthoredOutcomeReplayReadiness(ORG, JOB)
    offer(state, request(state, f"/jobs/{JOB}"), {"id": JOB, "generation": 1, "state": "completed"})
    return state


def payload() -> dict[str, Any]:
    states = [
        "no_contact",
        "policy_blocked",
        "access_blocked",
        "unsupported",
        "failed",
        "succeeded",
    ]
    return {
        "items": [
            dict(
                organization_id=ORG,
                job_id=JOB,
                item_id=f"00000000-0000-4000-8000-{index + 1:012d}",
                source_url=f"https://synthetic.publisher.example/authored-outcome-{index:03d}.html",
                state=states[index % 6],
                batch_id="00000000-0000-4000-8000-000000000127" if index == 0 else None,
            )
            for index in range(25)
        ],
        "next_cursor": "25",
    }


def replay(state: AuthoredOutcomeReplayReadiness) -> ReplayRequest:
    token = request(state, f"/jobs/{JOB}/events")
    state.headers(token, {})
    event = dict(organization_id=ORG, job_id=JOB, sequence=7, event_type="job.finished")
    state.offer(token, 200, f"id: {CURSOR}\ndata: {json.dumps(event)}\n\n".encode())
    token.render_before = SimpleNamespace(evaluate=AsyncMock(return_value=True))
    return token


def following(state: AuthoredOutcomeReplayReadiness) -> ReplayRequest:
    offer(
        state,
        request(state, f"/jobs/{JOB}/progress"),
        dict(organization_id=ORG, job_id=JOB, generation=1, state="completed", last_sequence=7),
    )
    outcomes = request(state, f"/article-outcomes?job_id={JOB}&limit=25")
    outcomes.loading = True
    offer(state, outcomes, payload())
    ack = request(state, f"/jobs/{JOB}/events")
    state.headers(ack, {"last-event-id": CURSOR})
    state.offer(ack, 200, b"")
    state.finish(ack, True)
    return outcomes


def ready() -> tuple[AuthoredOutcomeReplayReadiness, ReplayRequest]:
    state = armed()
    state.finish(replay(state), True)
    proof = following(state)
    assert state.ready() is proof
    return state, proof


def test_visible_first_table_and_held_replay_do_not_authorize_keyboard_start() -> None:
    state = armed()
    initial = request(state, f"/article-outcomes?job_id={JOB}&limit=25")
    initial.loading = True
    offer(state, initial, payload())
    assert state.ready() is None
    terminal = replay(state)
    current = following(state)
    assert state.ready() is None  # Even all following replies cannot replace replay delivery.
    state.finish(terminal, True)
    assert state.ready() is current and current is not initial


@pytest.mark.parametrize("part", ["job_request", "replay", "ack", "progress", "outcomes"])
def test_every_delivery_is_required(part: str) -> None:
    state, _ = ready()
    state.finish(getattr(state, part), False)
    assert state.ready() is None


@pytest.mark.parametrize(
    "mutation",
    [
        "tenant",
        "job",
        "item",
        "order",
        "count",
        "cursor",
        "source",
        "state",
        "batch",
        "loading",
        "denied",
    ],
)
def test_authored_membership_and_reply_refusals(mutation: str) -> None:
    state, _ = ready()
    data = payload()
    token = request(state, f"/article-outcomes?job_id={JOB}&limit=25")
    token.loading = mutation != "loading"
    if mutation in {"tenant", "job", "item", "source", "state", "batch"}:
        key = {
            "tenant": "organization_id",
            "job": "job_id",
            "item": "item_id",
            "source": "source_url",
            "state": "state",
            "batch": "batch_id",
        }[mutation]
        data["items"][0][key] = OTHER
    elif mutation == "order":
        data["items"].reverse()
    elif mutation == "count":
        data["items"].pop()
    elif mutation == "cursor":
        data["next_cursor"] = None
    state.offer(token, 404 if mutation == "denied" else 200, json.dumps(data).encode())
    state.finish(token, True)
    assert state.failed and state.ready() is None


def test_restarted_stream_retires_previous_render_and_ack() -> None:
    state, old = ready()
    state.finish(replay(state), True)
    state.finish(old, True)
    assert state.ready() is None
    current = following(state)
    assert state.ready() is current and current is not old


def test_wrong_generation_refuses_even_with_current_authored_rows() -> None:
    state, _ = ready()
    offer(
        state,
        request(state, f"/jobs/{JOB}/progress"),
        dict(organization_id=ORG, job_id=JOB, generation=2, state="completed", last_sequence=7),
    )
    assert state.failed and state.ready() is None


@pytest.mark.parametrize("retained_old_dom", [False, True])
def test_network_proof_requires_current_render_and_detached_prior_page(
    retained_old_dom: bool,
) -> None:
    state, proof = ready()
    assert state.replay is not None
    state.replay.render_before = SimpleNamespace(
        evaluate=AsyncMock(return_value=not retained_old_dom)
    )
    current = SimpleNamespace(evaluate=AsyncMock(return_value=retained_old_dom))
    with pytest.raises(RuntimeError, match="correlation|replaced"):
        asyncio.run(require_outcome_render(cast(Page, None), state, proof, cast(JSHandle, current)))


def test_current_network_and_render_proof_pass_and_keep_five_second_budget() -> None:
    state, proof = ready()
    current = SimpleNamespace(evaluate=AsyncMock(return_value=True), dispose=AsyncMock())
    locator = SimpleNamespace(wait_for=AsyncMock(), element_handle=AsyncMock(return_value=current))
    locator.first = locator
    locator.get_by_role = lambda *args, **kwargs: locator
    locator.filter = lambda **kwargs: locator
    page = SimpleNamespace(
        get_by_role=lambda *args, **kwargs: locator, get_by_text=lambda *args, **kwargs: locator
    )
    result = asyncio.run(wait_outcome_replay(cast(Page, page), state, asyncio.Event(), timeout=5))
    assert result == (proof, cast(JSHandle, current))


def test_waiter_does_not_inspect_visible_initial_page_until_exact_replay_delivery() -> None:
    async def scenario() -> None:
        state = armed()
        stream = replay(state)
        proof = following(state)
        current = SimpleNamespace(evaluate=AsyncMock(return_value=True), dispose=AsyncMock())
        locator = SimpleNamespace(
            wait_for=AsyncMock(), element_handle=AsyncMock(return_value=current)
        )
        locator.first = locator
        locator.get_by_role = lambda *args, **kwargs: locator
        locator.filter = lambda **kwargs: locator
        page = SimpleNamespace(
            get_by_role=lambda *args, **kwargs: locator, get_by_text=lambda *args, **kwargs: locator
        )
        changed = asyncio.Event()
        task = asyncio.create_task(wait_outcome_replay(cast(Page, page), state, changed, timeout=5))
        try:
            await asyncio.sleep(0)  # Yield once to the owned waiter, not a readiness delay.
            assert not task.done()
            locator.wait_for.assert_not_awaited()
            state.finish(stream, True)
            changed.set()
            assert await task == (proof, cast(JSHandle, current))
            locator.wait_for.assert_awaited_once()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "suffix", ["&cursor=25", "&article_outcome_presence=unresolved", "&item_id=" + OTHER]
)
def test_readiness_never_accepts_another_selection(suffix: str) -> None:
    state, _ = ready()
    request(state, f"/article-outcomes?job_id={JOB}&limit=25" + suffix)
    assert state.failed and state.ready() is None


def test_late_organization_requires_new_mount_readiness() -> None:
    function = ast.parse(inspect.getsource(authored_outcome_paging)).body[0]
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    marker = next(
        node for node in calls if ast.unparse(node) == "checkpoint('outcomes_late_organization')"
    )
    returns = [
        node
        for node in calls
        if node.lineno < marker.lineno
        and isinstance(node.func, ast.Name)
        and node.func.id == "activate"
        and "name='Jobs'" in ast.unparse(node)
    ]
    last_return = max(returns, key=lambda node: node.lineno)
    waits = [
        node
        for node in calls
        if last_return.lineno < node.lineno < marker.lineno
        and isinstance(node.func, ast.Name)
        and node.func.id == "wait_outcome_replay"
    ]
    assert len(waits) == 1, "earlier presence readiness cannot cover a new Jobs mount"
    assert any(
        keyword.arg == "timeout" and ast.literal_eval(keyword.value) == 5
        for keyword in waits[0].keywords
    )


def test_new_mount_requires_its_own_replay_and_deliveries() -> None:
    previous, old_proof = ready()
    current = armed()
    current.finish(old_proof, True)
    current.finish(previous.replay, True)
    assert current.ready() is None
    current.finish(replay(current), True)
    fresh_proof = following(current)
    assert current.ready() is fresh_proof and fresh_proof is not old_proof

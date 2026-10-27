"""Passive same-attempt diagnostics preserve the real keyboard failure."""

import ast
import asyncio
import inspect
import json
import subprocess
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from operator_ui_protocol import FocusExhaustion, KeyboardAttemptTrace
from playwright.async_api import Locator, Page
from pydantic import ValidationError


def test_presence_next_page_uses_same_target_with_passive_attempt_trace() -> None:
    import operator_ui_acceptance as guest

    module = ast.parse(inspect.getsource(guest))
    for node in ast.walk(module):
        if not isinstance(node, ast.Try):
            continue
        for index, statement in enumerate(node.body):
            if ast.unparse(statement) == "checkpoint('outcomes_presence_keyboard')":
                call = node.body[index + 2]
                assert ast.unparse(call) == (
                    "await traced_activate(page, region.get_by_role('button', "
                    "name='Next article outcome page', exact=True))"
                )
                return
    raise AssertionError("Existing presence keyboard checkpoint must remain covered")


@pytest.mark.parametrize("overflow", [False, True])
def test_passive_observer_records_order_and_cleans_up(overflow: bool) -> None:
    import operator_ui_acceptance as guest

    script = r"""
const listeners = new Map();
let observer;
let disconnected = false;
let replacement;
const heading = {};
const region = {querySelector: selector => selector === 'h4' ? heading : replacement};
const target = {isConnected: true, closest: () => region};
replacement = target;
global.document = {
 addEventListener: (kind, fn) => listeners.set(kind, fn),
 removeEventListener: (kind, fn) => {
  if(listeners.get(kind) !== fn) throw Error(); listeners.delete(kind);
 }
};
global.MutationObserver = class {
 constructor(fn) {observer = fn;} observe() {} disconnect() {disconnected = true;}
};
const state = OBSERVER(target);
for(let i=0;i<47;i++) listeners.get('keydown')({key:'Tab'});
listeners.get('focusin')({target: heading});
target.isConnected = false;
replacement = {isConnected: true};
observer();
for(let i=47;i<100;i++) listeners.get('keydown')({key:'Tab'});
OVERFLOW
const result = state.finish();
if(!disconnected || listeners.size !== 0) throw Error('cleanup');
console.log(JSON.stringify(result));
""".replace("OBSERVER", "(" + guest.KEYBOARD_ATTEMPT_OBSERVER + ")").replace(
        "OVERFLOW",
        "for(let i=0;i<100;i++) listeners.get('focusin')({target:heading});" if overflow else "",
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    trace = KeyboardAttemptTrace.model_validate(json.loads(result.stdout))
    assert trace.tabs == 100
    if overflow:
        assert trace.truncated and len(trace.events) == 32
        return
    assert not trace.truncated
    assert [(e.kind, e.tab, e.target_connected) for e in trace.events] == [
        ("start", 0, True),
        ("heading_focus", 47, True),
        ("target_detached", 47, False),
        ("target_replaced", 47, True),
        ("finish", 100, True),
    ]


@pytest.mark.parametrize("broken", [False, True])
def test_trace_never_replaces_original_failure(
    monkeypatch: pytest.MonkeyPatch, broken: bool
) -> None:
    import operator_ui_acceptance as guest

    original = RuntimeError("Control not reachable by keyboard")
    guest.focus_exhaustion = FocusExhaustion(
        target_focused=False, document_focused=True, modal_open=False, active_kind="other"
    )
    handle = SimpleNamespace(
        evaluate=AsyncMock(
            side_effect=RuntimeError("private") if broken else None,
            return_value={"tabs": 100, "truncated": False, "events": []},
        ),
        dispose=AsyncMock(),
    )
    target = SimpleNamespace(evaluate_handle=AsyncMock(return_value=handle))
    activate = AsyncMock(side_effect=original)
    monkeypatch.setattr(guest, "activate", activate)
    page = cast(Page, object())
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(guest.traced_activate(page, cast(Locator, target)))
    assert caught.value is original
    activate.assert_awaited_once_with(page, target)
    handle.dispose.assert_awaited_once()
    assert (
        guest.focus_exhaustion.attempt_trace == "unavailable"
        if broken
        else isinstance(guest.focus_exhaustion.attempt_trace, KeyboardAttemptTrace)
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"tabs": 101},
        {"tabs": True},
        {"private": "value"},
        {"events": [{"kind": "arbitrary", "tab": 0, "target_connected": True}]},
        {"events": [{"kind": "start", "tab": 0, "target_connected": True}] * 33},
    ],
)
def test_trace_rejects_unbounded_or_sensitive_fields(patch: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        KeyboardAttemptTrace.model_validate({"tabs": 0, "truncated": False, "events": [], **patch})


@pytest.mark.parametrize("attachment_failure", [False, True])
def test_success_and_attachment_failure_keep_single_activation(
    monkeypatch: pytest.MonkeyPatch, attachment_failure: bool
) -> None:
    import operator_ui_acceptance as guest

    handle = SimpleNamespace(
        evaluate=AsyncMock(return_value={"tabs": 3, "truncated": False, "events": []}),
        dispose=AsyncMock(),
    )
    target = SimpleNamespace(
        evaluate_handle=AsyncMock(
            return_value=handle, side_effect=RuntimeError("private") if attachment_failure else None
        )
    )
    activate = AsyncMock()
    monkeypatch.setattr(guest, "activate", activate)
    guest.focus_exhaustion = None
    asyncio.run(guest.traced_activate(cast(Page, object()), cast(Locator, target)))
    activate.assert_awaited_once()
    assert guest.focus_exhaustion is None
    if not attachment_failure:
        handle.dispose.assert_awaited_once()

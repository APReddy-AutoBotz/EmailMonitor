"""Keyboard-only actual built UI, same approved isolated browser, owned ASGI RPC."""

import asyncio
import base64
import errno
import hashlib
import json
import os
import re
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlsplit

from browser_acceptance import sandbox_status
from operator_ui_protocol import (
    ERRORS,
    EVIDENCE_PHASES,
    OUTCOME_PHASES,
    STAGES,
    EvidenceFocusTrace,
    FocusExhaustion,
    HandoffTrace,
    KeyboardAttemptTrace,
    ObservationTrace,
    OutcomeReplayReadiness,
    ReplayRequest,
    asset_manifest,
    export_assertion_line,
    failure_reason,
    route_failure_reason,
    route_headers_reason,
    validate_journey,
)
from playwright.async_api import (
    Error,
    JSHandle,
    Locator,
    Page,
    Request,
    Route,
    async_playwright,
    expect,
)

ORIGIN = "https://app.example.test"

# Passive, value-free observations of one owned keyboard attempt. No focus calls,
# event cancellation, DOM writes, retries, timer changes or payload collection.
KEYBOARD_ATTEMPT_OBSERVER = """node => {
    let target = node;
    const region = node.closest('section[aria-label="Article outcomes"]');
    const heading = region?.querySelector('h4');
    const trace = {tabs: 0, truncated: false, events: []};
    const record = kind => {
        if (trace.events.length === 32) { trace.truncated = true; return; }
        trace.events.push({kind, tab: trace.tabs, target_connected: target.isConnected});
    };
    const key = event => {
        if (event.key === 'Tab') trace.tabs = Math.min(100, trace.tabs + 1);
    };
    const focus = event => { if (event.target === heading) record('heading_focus'); };
    let detached = false;
    const changed = () => {
        if (!target.isConnected && !detached) { record('target_detached'); detached = true; }
        const replacement = region?.querySelector(
            ':scope > div:last-child > .actions > button:last-child');
        if (replacement && replacement !== target) {
            target = replacement; detached = false; record('target_replaced');
        }
    };
    const observer = new MutationObserver(changed);
    observer.observe(region, {childList: true, subtree: true});
    document.addEventListener('keydown', key, true);
    document.addEventListener('focusin', focus, true);
    record('start');
    return {finish: () => {
        changed(); record('finish'); observer.disconnect();
        document.removeEventListener('keydown', key, true);
        document.removeEventListener('focusin', focus, true);
        return trace;
    }};
}"""


HANDOFF_OBSERVER = """(() => {
    const trace = {key_events: 0, click_events: 0, trusted_click: false,
        disabled_on_enter: null, focused_on_enter: null, last_enter_target: 'none',
        error_count: 0, error_kind: 'none'};
    window.__emHandoffTrace = trace;
    const target = node => node?.tagName === 'BUTTON'
        && node.textContent === 'View accepted results for this selection';
    document.addEventListener('keydown', event => {
        if (event.key !== 'Enter') return;
        trace.last_enter_target = target(event.target) ? 'handoff' : 'other';
        if (target(event.target)) {
            trace.key_events = Math.min(2, trace.key_events + 1);
            trace.disabled_on_enter = event.target.disabled;
            trace.focused_on_enter = event.target === document.activeElement;
        }
    }, true);
    document.addEventListener('click', event => {
        if (target(event.target)) {
            trace.click_events = Math.min(2, trace.click_events + 1);
            trace.trusted_click = event.isTrusted;
        }
    }, true);
    const error = value => {
        trace.error_count = Math.min(2, trace.error_count + 1);
        trace.error_kind = value?.name === 'TypeError' ? 'type'
            : value?.name === 'ReferenceError' ? 'reference' : 'other';
    };
    window.addEventListener('error', event => error(event.error));
    window.addEventListener('unhandledrejection', event => error(event.reason));
})()"""


async def handoff_snapshot(page: Page) -> HandoffTrace | Literal["unavailable"]:
    try:
        value = await asyncio.wait_for(
            page.evaluate("""() => {
            const trace = window.__emHandoffTrace;
            const screen = document.querySelector('h3')?.textContent;
            const label = Array.from(document.querySelectorAll('label')).find(
                node => node.firstChild?.textContent === 'Association state');
            const value = label?.querySelector('select')?.value;
            return {...trace, screen: screen === 'Contacts' ? 'contacts'
                : screen === 'Review queue' ? 'review' : 'other',
                association: value === undefined ? 'missing'
                : ['accepted','needs_review','unmatched','rejected'].includes(value)
                    ? value : 'other'};
        }"""),
            timeout=0.1,
        )
        return HandoffTrace.model_validate(value)
    except Exception:
        return "unavailable"


handoff_trace: HandoffTrace | Literal["unavailable"] | None = None


async def assert_accepted_handoff(page: Page) -> None:
    global handoff_trace
    handoff_trace = None
    try:
        # The wrapping label also contains the select's option text.
        await expect(page.get_by_label(re.compile(r"^Association state"))).to_have_value("accepted")
    except AssertionError:
        # Capture while Playwright is still live; never replace the original failure.
        handoff_trace = await handoff_snapshot(page)
        raise


focus_exhaustion: FocusExhaustion | Literal["unavailable"] | None = None
HEADERS = {
    "content-type",
    "cookie",
    "origin",
    "x-csrf-token",
    "x-emailmonitor-ui",
    "idempotency-key",
    "last-event-id",
    "accept",
}


RPC_DEADLINE = 10.0


class Channel:
    def __init__(self) -> None:
        self.identifier = 0
        self.pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.retired: set[int] = set()
        self.writer = asyncio.Lock()
        self.capacity = asyncio.Semaphore(8)
        self.waiting = 0
        self.admitted = 0

    async def read(self) -> None:
        while True:
            raw = await asyncio.to_thread(sys.stdin.buffer.readline, 65537)
            if not raw.endswith(b"\n") or len(raw) > 65536:
                raise RuntimeError("Bounded UI reply missing")
            message = json.loads(raw)
            identifier = message.get("identifier")
            if type(identifier) is not int or message.get("kind") != "reply":
                raise RuntimeError("Unexpected UI reply grammar")
            future = self.pending.pop(identifier, None)
            if future is None:
                if identifier in self.retired:
                    continue
                raise RuntimeError("Unknown UI reply identifier")
            if not future.done():
                future.set_result(message)

    async def request(self, message: dict[str, object]) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + RPC_DEADLINE
        queued = self.admitted >= 8
        if self.identifier >= 512:
            raise RuntimeError("UI diagnostic request cap exceeded")
        if self.admitted >= 16:
            raise RuntimeError("UI diagnostic admission cap exceeded")
        self.admitted += 1
        if queued:
            self.waiting += 1
        acquired = False
        identifier = None
        try:
            await asyncio.wait_for(self.capacity.acquire(), timeout=RPC_DEADLINE)
            acquired = True
            if queued:
                self.waiting -= 1
                queued = False
            if self.identifier >= 512:
                raise RuntimeError("UI diagnostic request cap exceeded")
            self.identifier += 1
            identifier = self.identifier
            future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
            message["identifier"] = identifier
            raw = json.dumps(message)
            if len(raw.encode()) > 32768:
                raise RuntimeError("UI diagnostic request too large")
            self.pending[identifier] = future
            async with self.writer:
                print(raw, flush=True)
            return await asyncio.wait_for(
                future, timeout=max(0, deadline - asyncio.get_running_loop().time())
            )
        finally:
            if identifier is not None:
                self.pending.pop(identifier, None)
                self.retired.add(identifier)
            if queued:
                self.waiting -= 1
            self.admitted -= 1
            if acquired:
                self.capacity.release()


async def api_headers(incoming: Request, failure: Callable[[str, str], None]) -> dict[str, str]:
    """Keep actual sensitive-header retrieval; report only fixed failure metadata."""
    try:
        return {
            key: value for key, value in (await incoming.all_headers()).items() if key in HEADERS
        }
    except (Error, RuntimeError) as error:
        failure(
            "Error" if isinstance(error, Error) else "RuntimeError",
            route_headers_reason(incoming.failure, error),
        )
        raise


async def focus(page: Page, target: Locator) -> None:
    """Find controls using real Tab navigation; never mutate DOM form values."""
    global focus_exhaustion
    focus_exhaustion = None
    await target.wait_for(state="visible", timeout=10000)
    await expect(target).to_be_enabled(timeout=10000)
    for _ in range(100):
        if await target.evaluate("node => node === document.activeElement"):
            return
        await page.keyboard.press("Tab")
    # Observe only after failure; even a target reached on Tab 100 still fails.
    # Never emit DOM text, values, identifiers, URLs or arbitrary error messages.
    try:
        focus_exhaustion = FocusExhaustion.model_validate(
            await asyncio.wait_for(
                target.evaluate("""node => {
                const active = document.activeElement;
                const heading = document.querySelector('section[aria-label="Article outcomes"] h4');
                const controls = ['BUTTON', 'TEXTAREA', 'SELECT', 'INPUT'];
                const kind = element => controls.includes(element?.tagName)
                    ? element.tagName.toLowerCase() : 'other';
                const targetDialog = node.closest('dialog[open]');
                return {
                    target_focused: node === active,
                    document_focused: document.hasFocus(),
                    modal_open: document.querySelector('dialog[open]') !== null,
                    active_kind: active === null ? 'none' : active === node ? 'target'
                        : active === document.body ? 'body'
                        : active === heading ? 'outcomes_heading' : 'other',
                    target_kind: kind(node), active_control: kind(active),
                    target_disabled: node.matches(':disabled'),
                    target_in_dialog: targetDialog !== null,
                    active_in_target_dialog: targetDialog !== null && targetDialog.contains(active),
                    target_inert: node.closest('[inert]') !== null,
                    target_tab_stop: node.tabIndex >= 0
                };
            }"""),
                timeout=0.1,
            )
        )
    except Exception:
        focus_exhaustion = "unavailable"
    raise RuntimeError("Control not reachable by keyboard")


async def activate(page: Page, target: Locator) -> None:
    await focus(page, target)
    await page.keyboard.press("Enter")


async def traced_activate(page: Page, target: Locator) -> None:
    """Observe the same activate call; diagnostics cannot change its outcome."""
    global focus_exhaustion
    handle: JSHandle | None = None
    try:
        handle = await asyncio.wait_for(target.evaluate_handle(KEYBOARD_ATTEMPT_OBSERVER), 0.1)
    except Exception:
        pass
    try:
        await activate(page, target)
    finally:
        trace: KeyboardAttemptTrace | Literal["unavailable"] = "unavailable"
        if handle is not None:
            try:
                trace = KeyboardAttemptTrace.model_validate(
                    await asyncio.wait_for(handle.evaluate("state => state.finish()"), 0.1)
                )
            except Exception:
                pass
            finally:
                try:
                    await asyncio.wait_for(handle.dispose(), 0.1)
                except Exception:
                    pass
        if isinstance(focus_exhaustion, FocusExhaustion):
            focus_exhaustion = focus_exhaustion.model_copy(update={"attempt_trace": trace})


async def outcome_loading(page: Page, state: OutcomeReplayReadiness) -> bool:
    """Read only the exact request-owned loading render, before its reply is offered."""
    return bool(
        await page.evaluate(
            """scope => {
        const region = document.querySelector('section[aria-label="Article outcomes"]');
        const organization = document.querySelector('select[aria-label="Active organization"]');
        const job = [...document.querySelectorAll('h4')].some(
            node => node.textContent === 'Job ' + scope.job);
        return organization?.value === scope.organization && job && !!region &&
            !region.querySelector('table') &&
            [...region.querySelectorAll('[role="status"]')].some(node =>
                node.textContent === 'Loading current article outcomes…');
    }""",
            {"organization": state.organization, "job": state.job},
        )
    )


async def require_outcome_render(
    page: Page, state: OutcomeReplayReadiness, proof: ReplayRequest, opener: JSHandle
) -> None:
    if state.ready() is not proof or state.replay is None or state.replay.render_before is None:
        raise RuntimeError("Current terminal replay/render correlation missing")
    previous = cast(JSHandle, state.replay.render_before)
    if not await previous.evaluate("node => !!node && !node.isConnected"):
        raise RuntimeError("Terminal replay has not replaced its preceding outcome render")
    valid = await opener.evaluate(
        """(node, scope) => {
        const region = node.closest('section[aria-label="Article outcomes"]');
        const row = node.closest('tr');
        const organization = document.querySelector('select[aria-label="Active organization"]');
        const job = [...document.querySelectorAll('h4')].some(
            value => value.textContent === 'Job ' + scope.job);
        return node.isConnected && !!region && organization?.value === scope.organization && job &&
            row?.querySelector('td')?.textContent.includes('Item: ' + scope.item) &&
            node.textContent === 'Inspect article observation';
    }""",
        {"organization": state.organization, "job": state.job, "item": proof.item},
    )
    if not valid or state.ready() is not proof:
        raise RuntimeError("Current terminal replay/render correlation missing")


async def wait_outcome_replay(
    page: Page, state: OutcomeReplayReadiness, changed: asyncio.Event
) -> tuple[ReplayRequest, JSHandle]:
    async with asyncio.timeout(10):
        while True:
            changed.clear()
            if state.failed:
                raise RuntimeError("Current terminal replay/render correlation refused")
            proof = state.ready()
            if proof is not None:
                break
            await changed.wait()
        # These remain actual DOM checks; a cursor or HTTP reply alone cannot pass.
        await page.get_by_text("no contact", exact=True).first.wait_for()
        region = page.get_by_role("region", name="Article outcomes", exact=True)
        opener = (
            region.get_by_role("row")
            .filter(has_text="Item: " + str(proof.item))
            .get_by_role("button", name="Inspect article observation", exact=True)
        )
        handle = await opener.element_handle()
        if handle is None:
            raise RuntimeError("Current terminal replay/render correlation missing")
        try:
            await require_outcome_render(page, state, proof, handle)
        except BaseException:
            await handle.dispose()
            raise
        return proof, handle


async def prove_delayed_outcome_replay(
    page: Page,
    organization: str,
    job: str,
    observe: Callable[
        [OutcomeReplayReadiness | None, asyncio.Event | None, asyncio.Event | None], None
    ],
    changed: asyncio.Event,
    checkpoint: Callable[[str], None],
) -> None:
    """Separate deterministic proof; forward the exact held terminal replay unchanged."""
    await activate(page, page.get_by_role("button", name="Back to recent jobs", exact=True))
    state = OutcomeReplayReadiness(organization, job)
    release, offered = asyncio.Event(), asyncio.Event()
    observe(state, release, offered)
    old: JSHandle | None = None
    current: JSHandle | None = None
    try:
        checkpoint("outcomes_replay_delayed")
        await activate(page, page.get_by_role("button", name="Open job " + job, exact=True))
        await asyncio.wait_for(offered.wait(), timeout=5)
        region = page.get_by_role("region", name="Article outcomes", exact=True)
        opener = region.get_by_role("button", name="Inspect article observation", exact=True)
        await opener.wait_for()
        old = await opener.element_handle()
        assert old is not None and state.ready() is None
        dialog = page.get_by_role("dialog", name="Article observation details", exact=True)
        await activate(page, opener)
        await expect(dialog).to_be_visible()
        assert state.ready() is None
        release.set()
        checkpoint("outcomes_replay_invalidated")
        await expect(dialog).not_to_be_visible()
        assert await old.evaluate("node => !node.isConnected")
        checkpoint("outcomes_replay_rendered")
        proof, current = await wait_outcome_replay(page, state, changed)
        await focus(page, opener)
        await require_outcome_render(page, state, proof, current)
        await page.keyboard.press("Enter")
        await expect(dialog).to_contain_text("Retained parser outcome: no contact")
        await require_outcome_render(page, state, proof, current)
        await expect(
            dialog.get_by_role("button", name="Close article observation", exact=True)
        ).to_be_focused()
        await page.keyboard.press("Escape")
        await expect(dialog).not_to_be_visible()
        await expect(opener).to_be_focused()
    finally:
        release.set()
        observe(None, None, None)
        for handle in (old, current):
            if handle is not None:
                await handle.dispose()


async def start_evidence_focus_trace(page: Page) -> JSHandle | None:
    """Passive fixed-category observation; never changes focus or captures content."""
    try:
        return await asyncio.wait_for(
            page.evaluate_handle("""() => {
            const dialog = document.querySelector('dialog[aria-labelledby="evidence-title"]');
            const trace = {states: [], truncated: false, close_seen: false};
            const current = () => document.querySelector(
                '[aria-label="Scrollable contact results"] tbody button');
            const sample = event => {
                const active = document.activeElement, opener = current();
                const state = {event, dialog_connected: dialog?.isConnected === true,
                    dialog_open: dialog?.open === true, close_seen: trace.close_seen,
                    opener_connected: opener?.isConnected === true,
                    contacts_present: document.querySelector(
                        '[aria-label="Scrollable contact results"]') !== null,
                    active_kind: active === opener && opener ? 'opener'
                        : dialog?.contains(active) ? 'dialog'
                        : active?.matches('p[tabindex="-1"]') ? 'fallback'
                        : active === document.body ? 'body' : 'other'};
                if (trace.states.length < 8) trace.states.push(state);
                else { trace.truncated = true; trace.states[7] = state; }
            };
            const close = () => { trace.close_seen = true; sample('close'); };
            const focus = () => sample('focus');
            const observer = new MutationObserver(() => sample('mutation'));
            dialog?.addEventListener('close', close);
            document.addEventListener('focusin', focus);
            observer.observe(document.body, {childList: true, subtree: true,
                attributes: true, attributeFilter: ['open']});
            let timer;
            trace.stop = () => { clearTimeout(timer); observer.disconnect();
                dialog?.removeEventListener('close', close);
                document.removeEventListener('focusin', focus); };
            trace.finish = () => { sample('assertion'); trace.stop();
                return {states: trace.states, truncated: trace.truncated}; };
            timer = setTimeout(trace.stop, 10000);
            sample('start'); return trace;
        }"""),
            timeout=0.1,
        )
    except Exception:
        return None


async def wait_evidence_closed(page: Page) -> None:
    """Native hidden precedes React close handling; require the exact dialog's removal."""
    # CSS deliberately includes the hidden element. A default role locator excludes it.
    # Inherit the unchanged page timeout; do not add a retry or move focus here.
    await page.locator('dialog[aria-labelledby="evidence-title"]').wait_for(state="detached")


async def check_evidence_focus(
    page: Page,
    trace: JSHandle | None,
) -> tuple[bool, EvidenceFocusTrace | Literal["unavailable"]]:
    """Preserve the original immediate current-opener assertion, with passive evidence."""
    try:
        value = await page.get_by_role(
            "button", name="Evidence and review", exact=True
        ).first.evaluate(
            """(node, trace) => ({
            restored: node === document.activeElement,
            trace: trace ? trace.finish() : null
        })""",
            trace,
        )
        restored = value["restored"]
        if type(restored) is not bool:
            raise RuntimeError("Invalid focus assertion result")
        try:
            snapshot: EvidenceFocusTrace | Literal["unavailable"] = (
                EvidenceFocusTrace.model_validate(value["trace"])
            )
        except Exception:
            snapshot = "unavailable"
        return restored, snapshot
    finally:
        if trace is not None:
            try:
                await asyncio.wait_for(trace.dispose(), timeout=0.1)
            except Exception:
                pass


async def start_observation_trace(opener: Locator) -> JSHandle | None:
    """Bounded passive DOM observation; never retain or emit article text/identifiers."""
    try:
        return await asyncio.wait_for(
            opener.evaluate_handle("""node => {
            const region = node.closest('section');
            const trace = {states: [], truncated: false};
            const sample = () => {
                const dialog = document.querySelector(
                    'dialog[aria-labelledby="article-observation-title"]');
                const panel = dialog?.querySelector(
                    'section[aria-label="Article observation quality"]');
                const text = panel?.textContent ?? '';
                const state = {
                    opener_connected: node.isConnected,
                    region_connected: region?.isConnected === true,
                    dialog_present: dialog !== null, dialog_open: dialog?.open === true,
                    quality: !panel ? 'missing'
                        : text.includes('Retained parser outcome: no contact') ? 'expected'
                        : text.includes('Loading current article quality') ? 'loading'
                        : text.includes('Current article quality is unavailable')
                            ? 'unavailable' : 'other'
                };
                if (JSON.stringify(trace.states.at(-1)) !== JSON.stringify(state)) {
                    if (trace.states.length < 8) trace.states.push(state);
                    else { trace.truncated = true; trace.observer.disconnect(); }
                }
            };
            trace.sample = sample;
            trace.observer = new MutationObserver(sample);
            trace.observer.observe(document.body, {
                subtree: true, childList: true, characterData: true,
                attributes: true, attributeFilter: ['open']});
            trace.timer = setTimeout(() => {
                trace.truncated = true; trace.observer.disconnect();
            }, 10000);
            sample();
            return trace;
        }"""),
            timeout=0.1,
        )
    except Exception:
        return None


async def finish_observation_trace(
    trace: JSHandle | None,
) -> ObservationTrace | Literal["unavailable"]:
    if trace is None:
        return "unavailable"
    try:
        value = await asyncio.wait_for(
            trace.evaluate("""trace => {
            clearTimeout(trace.timer); trace.observer.disconnect(); trace.sample();
            return {states: trace.states, truncated: trace.truncated};
        }"""),
            timeout=0.1,
        )
        return ObservationTrace.model_validate(value)
    except Exception:
        return "unavailable"
    finally:
        try:
            await asyncio.wait_for(trace.dispose(), timeout=0.1)
        except Exception:
            pass


async def type_text(page: Page, target: Locator, text: str) -> None:
    await focus(page, target)
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await page.keyboard.type(text)


async def select_index(page: Page, target: Locator, index: int) -> None:
    await focus(page, target)
    await page.keyboard.press("Home")
    for _ in range(index):
        await page.keyboard.press("ArrowDown")
    await page.keyboard.press("Enter")


async def authored_outcome_paging(
    page: Page, organization: str, checkpoint: Callable[[str], None]
) -> None:
    """Separate authored browser contract; these 127 rows are not SQL/worker evidence."""
    job_heading = page.get_by_role("heading", name=re.compile(r"^Job [0-9a-f-]{36}$"))
    job = (await job_heading.inner_text()).removeprefix("Job ")
    batch = "00000000-0000-4000-8000-000000000127"
    pattern = "**/article-outcomes?*"
    quality_pattern = f"**/association-batches/{batch}/observation-quality"
    methods: list[str] = []
    api_methods: list[str] = []

    def observe_request(request: Request) -> None:
        if urlsplit(request.url).path.startswith("/api/v1/"):
            api_methods.append(request.method)

    requested_pages: list[int] = []
    denied = False
    hold = False
    held_offset: int | None = None
    requested = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    quality_denied = False
    quality_hold = False
    quality_requested = asyncio.Event()
    quality_release = asyncio.Event()
    quality_finished = asyncio.Event()
    states = [
        "no_contact",
        "policy_blocked",
        "access_blocked",
        "unsupported",
        "failed",
        "succeeded",
    ]

    async def fulfill(route: Route, payload: object, status: int = 200) -> None:
        try:
            await route.fulfill(
                status=status, content_type="application/json", body=json.dumps(payload)
            )
        except Error:
            if route.request.failure != "net::ERR_ABORTED":
                raise

    async def outcomes(route: Route) -> None:
        nonlocal held_offset
        methods.append(route.request.method)
        assert route.request.method == "GET"
        query = parse_qs(urlsplit(route.request.url).query)
        if query.get("job_id") != [job]:
            await route.fallback()
            return
        assert query.get("limit") == ["25"]
        offset = int(query.get("cursor", ["0"])[0])
        assert offset in {0, 25, 50, 75, 100, 125}
        requested_pages.append(offset)
        presence = query.get("article_outcome_presence", ["all"])[0]
        assert presence in {
            "all",
            "observed_candidate",
            "completed_without_candidate",
            "unresolved",
        }
        indices = (
            list(range(127))
            if presence == "all"
            else (
                [0]
                if presence == "completed_without_candidate"
                else (
                    list(range(5, 127, 6))
                    if presence == "observed_candidate"
                    else [index for index in range(1, 127) if index % 6 != 5]
                )
            )
        )
        if query.get("item_id"):
            indices = [
                index
                for index in indices
                if query["item_id"] == [f"00000000-0000-4000-8000-{index + 1:012d}"]
            ]
        items = [
            {
                "organization_id": organization,
                "job_id": job,
                "item_id": f"00000000-0000-4000-8000-{index + 1:012d}",
                "source_url": f"https://synthetic.publisher.example/authored-outcome-{index:03d}.html",
                "state": states[index % len(states)],
                "reason": [
                    "no_contact",
                    "source_policy_changed",
                    "source_policy_changed",
                    "browser_not_completed",
                    "worker_failure",
                    "observed",
                ][index % len(states)],
                "batch_id": batch if index == 0 else None,
                "completed_at": "2026-10-22T00:00:00Z",
                "inherited_job_id": "00000000-0000-4000-8000-000000000099" if index == 5 else None,
                "observation_status": "no_contact" if index == 0 else None,
                "technical_status": "not_checked",
                "outreach_eligibility": "not_assessed",
            }
            for index in indices[offset : offset + 25]
        ]
        payload = {
            "items": items,
            "next_cursor": str(offset + 25) if offset + 25 < len(indices) else None,
        }
        if hold and offset == 25:
            held_offset = offset
            requested.set()
            await asyncio.wait_for(release.wait(), timeout=8)
            await fulfill(route, payload)
            finished.set()
        elif denied:
            await fulfill(route, {"detail": "Current scope unavailable"}, 404)
        else:
            await fulfill(route, payload)

    async def quality(route: Route) -> None:
        methods.append(route.request.method)
        assert route.request.method == "GET"
        payload = {
            "view_version": "observation-quality-v1",
            "organization_id": organization,
            "batch_id": batch,
            "scope": "article",
            "parser_version": "synthetic-html-v1",
            "observation_route": "html",
            "observation_status": "no_contact",
            "reason_availability": "not_recorded",
            "reasons": [],
            "review_scope": "author_email_association",
        }
        if quality_hold:
            quality_requested.set()
            await asyncio.wait_for(quality_release.wait(), timeout=8)
            await fulfill(route, payload)
            quality_finished.set()
        elif quality_denied:
            await fulfill(route, {"detail": "Current scope unavailable"}, 404)
        else:
            await fulfill(route, payload)

    page.on("request", observe_request)
    await page.route(pattern, outcomes)
    await page.route(quality_pattern, quality)
    try:
        checkpoint("outcomes_authored_load")
        await activate(page, page.get_by_role("button", name="Refresh current view", exact=True))
        region = page.get_by_role("region", name="Article outcomes", exact=True)
        table = region.get_by_role("table", name="Current-authorized article outcomes", exact=True)
        seen = []
        heading = region.get_by_role("heading", name="Article outcomes", exact=True)
        for number in range(6):
            checkpoint("outcomes_next_rows")
            count = 25 if number < 5 else 2
            await expect(region).to_contain_text(f"Page {number + 1}: {count} article outcomes")
            rows = table.locator("tbody tr")
            await expect(rows).to_have_count(count)
            seen.extend(
                await rows.locator("td:first-child").evaluate_all(
                    "nodes => nodes.map(node => node.firstChild.textContent)"
                )
            )
            if number < 5:
                await activate(
                    page,
                    region.get_by_role("button", name="Next article outcome page", exact=True),
                )
                checkpoint("outcomes_next_focus")
                await expect(heading).to_be_focused()
                await expect(table).to_be_visible()
                checkpoint("outcomes_next_tab")
                await page.keyboard.press("Tab")
                assert await region.evaluate("node => node.contains(document.activeElement)")
        checkpoint("outcomes_complete_page_set")
        assert len(seen) == len(set(seen)) == 127
        assert seen == [
            f"https://synthetic.publisher.example/authored-outcome-{index:03d}.html"
            for index in range(127)
        ]
        await expect(
            region.get_by_role("button", name="Next article outcome page", exact=True)
        ).to_be_disabled()
        for number in range(5, 0, -1):
            checkpoint("outcomes_previous_rows")
            await activate(
                page,
                region.get_by_role("button", name="Previous article outcome page", exact=True),
            )
            await expect(region).to_contain_text(f"Page {number}: 25 article outcomes")
            checkpoint("outcomes_previous_focus")
            await expect(heading).to_be_focused()
            checkpoint("outcomes_previous_tab")
            await page.keyboard.press("Tab")
            assert await region.evaluate("node => node.contains(document.activeElement)")
        checkpoint("outcomes_counts_and_states")
        await expect(
            page.get_by_text("1 of 1 discovered article units terminal", exact=True)
        ).to_be_visible()
        for state in states:
            await expect(table).to_contain_text(state.replace("_", " "))
        await expect(region).to_contain_text("Inherited from job")
        await expect(region).to_contain_text("No retained observation batch")
        await expect(
            region.get_by_role("button", name="Previous article outcome page", exact=True)
        ).to_be_disabled()
        checkpoint("outcomes_authored_modal")
        opener = region.get_by_role("button", name="Inspect article observation", exact=True)
        await activate(page, opener)
        dialog = page.get_by_role("dialog", name="Article observation details", exact=True)
        close = dialog.get_by_role("button", name="Close article observation", exact=True)
        await expect(close).to_be_focused()
        await expect(dialog).to_contain_text("Retained parser outcome: no contact")
        checkpoint("outcomes_modal_tab")
        # Check document controls without requiring focus to wrap inside the DOM:
        # native sequential navigation may move focus to browser chrome at an edge.
        assert await dialog.evaluate("node => node.matches(':modal')")
        await expect(close).to_be_focused()
        await page.keyboard.press("Tab")
        await expect(
            dialog.get_by_role("button", name="Refresh article observation", exact=True)
        ).to_be_focused()
        await page.keyboard.press("Shift+Tab")
        await expect(close).to_be_focused()
        assert await dialog.evaluate("node => node.matches(':modal')")
        checkpoint("outcomes_quality_pending")
        quality_hold = True
        await activate(
            page,
            dialog.get_by_role("button", name="Refresh article observation", exact=True),
        )
        await asyncio.wait_for(quality_requested.wait(), timeout=5)
        await expect(dialog).to_contain_text("Loading current article quality")
        await expect(dialog).not_to_contain_text("Retained parser outcome:")
        checkpoint("outcomes_quality_escape")
        await page.keyboard.press("Escape")
        await expect(dialog).not_to_be_visible()
        await expect(opener).to_be_focused()
        quality_hold = False
        quality_release.set()
        await asyncio.wait_for(quality_finished.wait(), timeout=5)
        await expect(dialog).not_to_be_visible()
        await activate(page, opener)
        await expect(dialog).to_contain_text("Retained parser outcome: no contact")
        checkpoint("outcomes_quality_denied")
        quality_denied = True
        await activate(
            page,
            dialog.get_by_role("button", name="Refresh article observation", exact=True),
        )
        await expect(dialog).to_contain_text("Current article quality is unavailable")
        await expect(dialog).not_to_contain_text("Retained parser outcome:")
        await activate(page, close)
        await expect(opener).to_be_focused()
        quality_denied = False
        await activate(page, opener)
        await expect(dialog).to_contain_text("Retained parser outcome: no contact")
        checkpoint("outcomes_stream_invalidation")
        # The native modal makes outside controls inert. A one-shot authored
        # stream failure exercises the real SSE invalidation path while it is open.
        stream_failed = asyncio.Event()
        events_pattern = f"**/jobs/{job}/events"

        async def fail_next_stream(route: Route) -> None:
            assert route.request.method == "GET"
            await route.abort("failed")
            stream_failed.set()

        await page.route(events_pattern, fail_next_stream, times=1)
        try:
            await asyncio.wait_for(stream_failed.wait(), timeout=5)
            await expect(dialog).not_to_be_visible()
            await expect(heading).to_be_focused()
            await expect(page.locator("dialog[open]")).to_have_count(0)
        finally:
            await page.unroute(events_pattern, fail_next_stream)
        checkpoint("outcomes_page_denied")
        denied = True
        await activate(page, page.get_by_role("button", name="Refresh current view", exact=True))
        await expect(region).to_contain_text("Current article outcomes are unavailable")
        await expect(table).not_to_be_visible()
        denied = False
        await activate(page, page.get_by_role("button", name="Refresh current view", exact=True))
        await expect(table).to_be_visible()
        checkpoint("outcomes_presence_keyboard")
        presence_select = region.get_by_role(
            "combobox", name="Article-outcome candidate presence", exact=True
        )
        await activate(
            page,
            region.get_by_role("button", name="Next article outcome page", exact=True),
        )
        await expect(region).to_contain_text("Page 2: 25 article outcomes")
        await select_index(page, presence_select, 2)
        await expect(region).to_contain_text("Page 1: 1 article outcomes")
        await expect(region).to_contain_text("authored-outcome-000.html")
        await expect(
            region.get_by_role("button", name="Previous article outcome page", exact=True)
        ).to_be_disabled()
        await expect(
            region.get_by_role("button", name="Next article outcome page", exact=True)
        ).to_be_disabled()
        await select_index(page, presence_select, 1)
        await expect(region).to_contain_text("Page 1: 21 article outcomes")
        await expect(region).not_to_contain_text("authored-outcome-000.html")
        await select_index(page, presence_select, 3)
        await expect(region).to_contain_text("Page 1: 25 article outcomes")
        await expect(region).not_to_contain_text("authored-outcome-005.html")
        await select_index(page, presence_select, 0)
        await expect(region).to_contain_text("Page 1: 25 article outcomes")
        checkpoint("outcomes_late_filter")
        hold = True
        requested.clear()
        release.clear()
        finished.clear()
        await activate(
            page,
            region.get_by_role("button", name="Next article outcome page", exact=True),
        )
        await asyncio.wait_for(requested.wait(), timeout=5)
        await select_index(page, presence_select, 2)
        await expect(region).to_contain_text("Page 1: 1 article outcomes")
        hold = False
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=5)
        await expect(region).not_to_contain_text("authored-outcome-025.html")
        await expect(page.locator("dialog[open]")).to_have_count(0)
        await select_index(page, presence_select, 0)
        await expect(region).to_contain_text("Page 1: 25 article outcomes")
        requested.clear()
        release.clear()
        finished.clear()
        checkpoint("outcomes_late_job")
        # Abandon a held second page, change jobs, then release it. Old rows must not
        # overwrite the newly selected job or its page cursor.
        hold = True
        await activate(
            page,
            region.get_by_role("button", name="Next article outcome page", exact=True),
        )
        await asyncio.wait_for(requested.wait(), timeout=5)
        assert held_offset == 25
        await activate(page, page.get_by_role("button", name="Back to recent jobs", exact=True))
        other_job = (
            page.get_by_role("button", name=re.compile(r"^Open job "))
            .filter(has_not_text=job[:8])
            .first
        )
        await activate(page, other_job)
        hold = False
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=5)
        await expect(region).not_to_contain_text("authored-outcome-")
        await activate(page, page.get_by_role("button", name="Back to recent jobs", exact=True))
        await activate(page, page.get_by_role("button", name="Open job " + job, exact=True))
        await expect(region).to_contain_text("Page 1: 25 article outcomes")
        checkpoint("outcomes_exact_article_navigation")
        await activate(
            page,
            region.get_by_role("button", name="Contacts for this article", exact=True).first,
        )
        await expect(page.get_by_label("Job UUID (optional)", exact=True)).to_have_value(job)
        await expect(
            page.get_by_label("Article item UUID (optional; requires job)", exact=True)
        ).to_have_value("00000000-0000-4000-8000-000000000001")
        await expect(page.get_by_label(re.compile(r"^Association state"))).to_have_value("accepted")
        await activate(page, page.get_by_role("button", name="Jobs", exact=True))
        await activate(
            page,
            region.get_by_role("button", name="Review queue for this article", exact=True).first,
        )
        await expect(
            page.get_by_label("Article item UUID (optional; requires job)", exact=True)
        ).to_have_value("00000000-0000-4000-8000-000000000001")
        await expect(page.get_by_label(re.compile(r"^Association state"))).to_have_value(
            "needs_review"
        )
        await type_text(page, page.get_by_label("Job UUID (optional)", exact=True), "")
        await expect(
            page.get_by_label("Article item UUID (optional; requires job)", exact=True)
        ).to_have_value("")
        await expect(
            page.get_by_label("Article item UUID (optional; requires job)", exact=True)
        ).to_be_disabled()
        await activate(page, page.get_by_role("button", name="Jobs", exact=True))
        checkpoint("outcomes_scoped_contacts")
        await activate(page, page.get_by_role("button", name="Contacts for this job", exact=True))
        await expect(page.get_by_label("Job UUID (optional)", exact=True)).to_have_value(job)
        await expect(page.get_by_label(re.compile(r"^Association state"))).to_have_value("accepted")
        await expect(page.get_by_label("Search loaded scope", exact=True)).to_have_value("")
        # Return filters to the existing actual contact journey's all-job scope.
        await type_text(page, page.get_by_label("Job UUID (optional)", exact=True), "")
        await activate(page, page.get_by_role("button", name="Jobs", exact=True))
        checkpoint("outcomes_scoped_review")
        await activate(
            page,
            page.get_by_role("button", name="Review queue for this job", exact=True),
        )
        await expect(page.get_by_label("Job UUID (optional)", exact=True)).to_have_value(job)
        await expect(page.get_by_label(re.compile(r"^Association state"))).to_have_value(
            "needs_review"
        )
        await activate(page, page.get_by_role("button", name="Jobs", exact=True))
        await expect(region).to_contain_text("Page 1: 25 article outcomes")
        await expect(
            region.get_by_role("button", name="Next article outcome page", exact=True)
        ).to_be_enabled()
        checkpoint("outcomes_late_organization")
        held_offset = None
        requested.clear()
        release.clear()
        finished.clear()
        hold = True
        await traced_activate(
            page,
            region.get_by_role("button", name="Next article outcome page", exact=True),
        )
        await asyncio.wait_for(requested.wait(), timeout=5)
        assert held_offset == 25
        organization_select = page.get_by_role("combobox", name="Active organization", exact=True)
        values = await organization_select.locator("option").evaluate_all(
            "nodes => nodes.map(node => node.value)"
        )
        checkpoint("outcomes_organization_switch_away")
        await select_index(page, organization_select, 1 - values.index(organization))
        hold = False
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=5)
        await expect(page.locator("body")).not_to_contain_text("authored-outcome-")
        await expect(page.locator("dialog[open]")).to_have_count(0)
        checkpoint("outcomes_organization_switch_back")
        await select_index(page, organization_select, values.index(organization))
        checkpoint("outcomes_organization_reopen_job")
        await activate(page, page.get_by_role("button", name="Open job " + job, exact=True))
        await expect(region).to_contain_text("Page 1: 25 article outcomes")
        checkpoint("outcomes_read_only")
        assert api_methods and set(api_methods) == {"GET"}
        assert methods and set(methods) == {"GET"}
        assert set(requested_pages) == {0, 25, 50, 75, 100, 125}
    finally:
        release.set()
        quality_release.set()
        page.remove_listener("request", observe_request)
        await page.unroute(pattern, outcomes)
        await page.unroute(quality_pattern, quality)
    await activate(page, page.get_by_role("button", name="Refresh current view", exact=True))


async def authored_contact_request_ownership(page: Page, checkpoint: Callable[[str], None]) -> None:
    """Actual Contacts hook with authored replies; hosted execution remains required."""
    checkpoint("outcomes_request_generation")
    pattern = "**/contacts?*"
    empty = page.get_by_text("No contacts match these server filters.", exact=True)
    error = page.get_by_text(
        "Resource unavailable. Permissions or retention may have changed.", exact=False
    )
    loading = page.locator("#main > p").filter(
        has_text=re.compile("^Loading current organization data…$")
    )
    search = page.get_by_label("Search loaded scope", exact=True)
    target = page.get_by_role("combobox", name="Author role", exact=True)
    await expect(search).to_have_value("")
    await expect(target).to_have_value("all")

    async def run_case(seed_error: bool, disabled_interval: bool) -> None:
        phase = "seed"
        seeded = asyncio.Event()
        returned = asyncio.Event()
        changed = asyncio.Event()
        release_returned = asyncio.Event()
        release_changed = asyncio.Event()
        finished_returned = asyncio.Event()
        finished_changed = asyncio.Event()
        changed_requests = 0

        async def fulfill(route: Route, failure: bool) -> None:
            try:
                await route.fulfill(
                    status=404 if failure else 200,
                    content_type="application/json",
                    body=json.dumps(
                        {"detail": "Unavailable"} if failure else {"items": [], "next_cursor": None}
                    ),
                )
            except Error:
                if route.request.failure != "net::ERR_ABORTED":
                    raise

        async def contacts(route: Route) -> None:
            nonlocal changed_requests
            assert route.request.method == "GET"
            query = parse_qs(urlsplit(route.request.url).query, keep_blank_values=True)
            is_original = query.get("author_target") == ["all"] and query.get("query") == [""]
            if phase == "seed":
                assert is_original
                await fulfill(route, seed_error)
                seeded.set()
            elif is_original:
                returned.set()
                await asyncio.wait_for(release_returned.wait(), timeout=8)
                await fulfill(route, not seed_error)
                finished_returned.set()
            else:
                changed_requests += 1
                changed.set()
                await asyncio.wait_for(release_changed.wait(), timeout=8)
                await fulfill(route, seed_error)
                finished_changed.set()

        await page.route(pattern, contacts)
        try:
            await activate(
                page, page.get_by_role("button", name="Refresh current view", exact=True)
            )
            await asyncio.wait_for(seeded.wait(), timeout=5)
            await expect(error if seed_error else empty).to_be_visible()
            phase = "held"
            if disabled_interval:
                # Search temporarily disables this same hook with path=null.
                # Return before debounce settles B, so reopening is null -> A.
                await focus(page, search)
                await page.keyboard.type("x")
                await expect(
                    page.get_by_text("Applying server search…", exact=True)
                ).to_be_visible()
                await page.keyboard.press("Backspace")
            else:
                await select_index(page, target, 1)
                await asyncio.wait_for(changed.wait(), timeout=5)
                await select_index(page, target, 0)
            await asyncio.wait_for(returned.wait(), timeout=5)
            if disabled_interval:
                assert changed_requests == 0
            else:
                assert changed_requests == 1
            # Request identity, not equality with the old path, owns display.
            await expect(loading).to_be_visible()
            await expect(empty).not_to_be_visible()
            await expect(error).not_to_be_visible()
            await expect(page.locator("dialog[open]")).to_have_count(0)
            release_returned.set()
            await asyncio.wait_for(finished_returned.wait(), timeout=5)
            await expect(empty if seed_error else error).to_be_visible()
            if not disabled_interval:
                release_changed.set()
                await asyncio.wait_for(finished_changed.wait(), timeout=5)
                await expect(empty if seed_error else error).to_be_visible()
                await expect(error if seed_error else empty).not_to_be_visible()
        finally:
            release_returned.set()
            release_changed.set()
            await page.unroute(pattern, contacts)

    # Both settled success and settled error must lose ownership on either route.
    for seed_error in (False, True):
        for disabled_interval in (False, True):
            await run_case(seed_error, disabled_interval)
    await activate(page, page.get_by_role("button", name="Refresh current view", exact=True))


async def settle_lifecycle_requests(channel: Channel) -> None:
    """Await owned replies, including admitted requests waiting for capacity."""

    async def drained() -> None:
        while channel.pending or channel.admitted:
            await asyncio.sleep(0.05)

    await asyncio.wait_for(drained(), timeout=10)


async def lifecycle_journey(
    page: Page, channel: Channel, setup: dict[str, Any], checkpoint: Callable[[str], None]
) -> None:
    """Existing fixture controls only; every mutation goes through the real UI/API."""

    async def open_job(identifier: str) -> None:
        await activate(page, page.get_by_role("button", name="Jobs", exact=True))
        back = page.get_by_role("button", name="Back to recent jobs", exact=True)
        if await back.count():
            await activate(page, back)
        await activate(page, page.get_by_role("button", name="Open job " + identifier, exact=True))
        await expect(
            page.get_by_role("heading", name="Job " + identifier, exact=True)
        ).to_be_visible()

    cancel_job, retry_job = str(setup["cancel_job"]), str(setup["retry_job"])
    checkpoint("lifecycle_cancel")
    await open_job(cancel_job)
    checkpoint("lifecycle_pause")
    await activate(page, page.get_by_role("button", name="Pause", exact=True))
    checkpoint("lifecycle_resume")
    await activate(page, page.get_by_role("button", name="Resume", exact=True))
    # Cancel is also available while paused. Observe the resumed render first,
    # otherwise the dialog can retain the revision from before Resume commits.
    await expect(page.get_by_role("button", name="Pause", exact=True)).to_be_visible()
    checkpoint("lifecycle_confirm_cancel")
    await activate(page, page.get_by_role("button", name="Cancel job", exact=True))
    dialog = page.get_by_role("dialog", name="Cancel job", exact=True)
    await expect(dialog).to_contain_text("Retained partial results stay available")
    await activate(page, dialog.get_by_role("button", name="Confirm cancel job", exact=True))
    await expect(dialog).not_to_be_visible()
    await expect(page.get_by_text("cancelled", exact=True).first).to_be_visible()
    checkpoint("lifecycle_cancel_retry")
    await activate(
        page, page.get_by_role("button", name="Retry failed work as continuation", exact=True)
    )
    await expect(
        page.get_by_text(
            "Resource unavailable. Permissions or retention may have changed.", exact=True
        )
    ).to_be_visible()
    await expect(page.get_by_role("heading", name="Job " + cancel_job, exact=True)).to_be_visible()
    checkpoint("lifecycle_retained_review")
    await activate(page, page.get_by_role("button", name="Contacts for this job", exact=True))
    table = page.get_by_role("table", name="Current-authorized observed contacts", exact=True)
    await expect(table.locator("tbody tr")).to_have_count(1)
    await activate(page, page.get_by_role("button", name="Evidence and review", exact=True).first)
    await expect(
        page.get_by_role("heading", name="Actual retained citation", exact=True)
    ).to_be_visible()
    await type_text(
        page, page.get_by_label("Reason", exact=True), "Synthetic cancelled-job retained evidence"
    )
    await activate(page, page.get_by_role("button", name="Save review", exact=True))
    await expect(page.get_by_role("dialog")).not_to_be_visible()
    checkpoint("lifecycle_export")
    await activate(page, page.get_by_role("button", name="Export this selection", exact=True))
    await expect(
        page.get_by_label("Job UUID (blank selects authorized matching jobs)", exact=True)
    ).to_have_value(cancel_job)
    await activate(
        page, page.get_by_role("button", name="Preview eligible export counts", exact=True)
    )
    await expect(page.get_by_role("region", name="Current export preview")).to_contain_text(
        "1 contacts;"
    )
    await activate(page, page.get_by_role("button", name="Create asynchronous export", exact=True))
    await expect(
        page.get_by_text("Private export queued. Wait for actual worker completion.", exact=True)
    ).to_be_visible()
    await channel.request({"kind": "control", "action": "wait_exports"})
    await activate(page, page.get_by_role("button", name="Refresh current view", exact=True))
    await expect(page.get_by_role("button", name="Download", exact=True)).to_be_enabled()

    checkpoint("lifecycle_retry")
    await open_job(retry_job)
    await channel.request({"kind": "control", "action": "hold_lifecycle_reply"})
    await activate(
        page, page.get_by_role("button", name="Retry failed work as continuation", exact=True)
    )
    await channel.request({"kind": "control", "action": "wait_held"})
    checkpoint("lifecycle_switch")
    organization = page.get_by_role("combobox", name="Active organization", exact=True)
    values = await organization.locator("option").evaluate_all(
        "nodes => nodes.map(node => node.value)"
    )
    await select_index(page, organization, values.index(setup["other_organization"]))
    await channel.request({"kind": "control", "action": "release_lifecycle_reply"})
    await expect(page.get_by_role("heading", name="Synthetic tenant 1", exact=True)).to_be_visible()
    await expect(page.get_by_role("button", name="Pause", exact=True)).to_have_count(0)
    await expect(
        page.get_by_role("heading", name=re.compile(r"^Job [0-9a-f-]{36}$"))
    ).to_have_count(0)
    await select_index(page, organization, values.index(setup["initial_organization"]))
    await open_job(retry_job)
    await activate(
        page, page.get_by_role("button", name="Retry failed work as continuation", exact=True)
    )
    await expect(page.get_by_role("heading", name="Job " + retry_job, exact=True)).to_have_count(0)
    await expect(page.get_by_role("button", name="Pause", exact=True)).to_be_visible()
    await channel.request({"kind": "control", "action": "publish"})
    await channel.request({"kind": "control", "action": "wait_jobs"})
    await activate(page, page.get_by_role("button", name="Refresh current view", exact=True))
    await expect(page.get_by_text("completed", exact=True).first).to_be_visible()
    await open_job(retry_job)
    await expect(page.get_by_text("completed partial", exact=True).first).to_be_visible()


async def main() -> None:
    if os.environ.get("EM_ISOLATION_DIAGNOSTIC") != "synthetic-operator-ui" or os.geteuid() == 0:
        raise RuntimeError("Explicit nonroot UI diagnostic required")
    for name, value in {
        "HOME": "/tmp/browser-home",
        "XDG_CONFIG_HOME": "/tmp/browser-config",
        "CHROME_CONFIG_HOME": "/tmp/browser-config",
        "XDG_CACHE_HOME": "/tmp/browser-cache",
    }.items():
        if os.environ.get(name) != value:
            raise RuntimeError("Bounded browser paths required")
        Path(value).mkdir(mode=0o700, exist_ok=True)
    if any(os.environ.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")):
        raise RuntimeError("Proxy-free diagnostic required")
    interfaces = sorted(path.name for path in Path("/sys/class/net").iterdir())
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if (
        interfaces != ["lo"]
        or int(status["CapEff"].strip(), 16)
        or status["NoNewPrivs"].strip() != "1"
        or status["Seccomp"].strip() != "2"
    ):
        raise RuntimeError("Original OS isolation controls required")
    network = []
    for family, target in [
        (socket.AF_INET, ("192.0.2.1", 443)),
        (socket.AF_INET6, ("2001:db8::1", 443)),
    ]:
        with socket.socket(family, socket.SOCK_STREAM) as stream:
            stream.settimeout(0.2)
            code = stream.connect_ex(target)
            if code != errno.ENETUNREACH:
                raise RuntimeError("Actual OS network denial missing")
            network.append(code)
    raw = await asyncio.to_thread(sys.stdin.buffer.readline, 65537)
    if not raw.endswith(b"\n") or len(raw) > 65536:
        raise RuntimeError("Bounded synthetic bootstrap required")
    setup = json.loads(raw)
    if setup.get("kind") != "bootstrap" or setup.get("origin") != ORIGIN:
        raise RuntimeError("Fixed synthetic UI origin required")
    validate_journey(setup)
    root = Path("/app/operator-web")
    manifest = asset_manifest(root)
    if manifest != setup.get("assets") or "index.html" not in manifest:
        raise RuntimeError("Immutable built asset manifest mismatch")
    channel = Channel()
    receiver = asyncio.create_task(channel.read())
    accepted = 0
    api_statuses: list[int] = []
    download_seen = asyncio.Event()
    replay_readiness: OutcomeReplayReadiness | None = None
    replay_hold: asyncio.Event | None = None
    replay_offered: asyncio.Event | None = None
    replay_changed = asyncio.Event()

    def observe_replay(
        state: OutcomeReplayReadiness | None,
        hold: asyncio.Event | None = None,
        offered: asyncio.Event | None = None,
    ) -> None:
        nonlocal replay_readiness, replay_hold, replay_offered
        replay_readiness, replay_hold, replay_offered = state, hold, offered
        replay_changed.clear()

    stage = "browser_launch"
    outcome_phase: str | None = None
    evidence_phase: str | None = None
    observation_trace: ObservationTrace | Literal["unavailable"] | None = None
    evidence_focus_trace: EvidenceFocusTrace | Literal["unavailable"] | None = None
    evidence_focus_observations: dict[str, object] = {}

    def checkpoint(value: str) -> None:
        nonlocal stage, outcome_phase, evidence_phase
        if value not in STAGES:
            raise RuntimeError("Fixed UI stage required")
        stage = value
        outcome_phase = None
        evidence_phase = None
        print(json.dumps({"kind": "stage", "stage": value}), flush=True)

    def outcome_checkpoint(value: str) -> None:
        nonlocal outcome_phase
        if stage != "url_worker" or value not in OUTCOME_PHASES:
            raise RuntimeError("Fixed outcome diagnostic phase required")
        # Preserve emitted stage identity and its existing 32-frame cap.
        outcome_phase = value

    def evidence_checkpoint(value: str) -> None:
        nonlocal evidence_phase
        if stage != "evidence_review" or value not in EVIDENCE_PHASES:
            raise RuntimeError("Fixed evidence diagnostic phase required")
        evidence_phase = value

    try:
        checkpoint("browser_launch")
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                channel="chromium",
                headless=True,
                chromium_sandbox=True,
                args=["--enable-automation"],
            )
            if browser.version != "153.0.8010.12":
                raise RuntimeError("Pinned Chromium required")
            context = await browser.new_context(service_workers="block", accept_downloads=False)
            await context.add_cookies(setup["cookies"])
            page = await context.new_page()
            await page.add_init_script(HANDOFF_OBSERVER)
            page.set_default_timeout(10000)
            checkpoint("sandbox")
            await page.goto("chrome://sandbox", wait_until="domcontentloaded")
            sandbox = sandbox_status(
                await page.locator("#sandbox-status").inner_text(),
                await page.locator("#evaluation").inner_text(),
            )
            command = await (await context.new_cdp_session(page)).send(
                "Browser.getBrowserCommandLine"
            )
            if "--no-sandbox" in command["arguments"]:
                raise RuntimeError("Chromium sandbox must remain enabled")

            def header_failure(error: str, reason: str) -> None:
                print(
                    json.dumps(
                        {
                            "kind": "failure",
                            "stage": stage,
                            "error": error,
                            "reason": reason,
                            "api_statuses": api_statuses,
                        }
                    ),
                    flush=True,
                )

            async def route_request(route: Route) -> None:
                nonlocal accepted
                incoming = route.request
                parsed = urlsplit(incoming.url)
                if (
                    parsed.scheme != "https"
                    or parsed.netloc != "app.example.test"
                    or parsed.fragment
                    or incoming.resource_type == "websocket"
                ):
                    await route.abort("blockedbyclient")
                    return
                if parsed.path.startswith("/api/v1/"):
                    observed, hold, offered = replay_readiness, replay_hold, replay_offered
                    ticket = observed.begin(incoming.url, incoming.method) if observed else None
                    replay_changed.set()
                    headers = await api_headers(incoming, header_failure)
                    if observed is not None:
                        observed.headers(ticket, headers)
                    if (
                        observed is not None
                        and ticket is not None
                        and ticket.kind == "outcomes"
                        and ticket.eligible
                    ):
                        ticket.loading = await outcome_loading(page, observed)
                    reply = await channel.request(
                        {
                            "kind": "request",
                            "url": incoming.url,
                            "method": incoming.method,
                            "headers": headers,
                            "body": incoming.post_data or "",
                        }
                    )
                    if reply.get("transport_abort") is True:
                        if observed is not None:
                            observed.finish(ticket, False)
                            replay_changed.set()
                        await route.abort("failed")
                        return
                    body = base64.b64decode(reply["body"], validate=True)
                    if (
                        len(body) > 32768
                        or type(reply["status"]) is not int
                        or not 100 <= reply["status"] <= 599
                    ):
                        raise RuntimeError("Bounded actual API reply required")
                    api_statuses.append(reply["status"])
                    if observed is not None:
                        observed.offer(ticket, reply["status"], body)
                        if ticket is not None and ticket is observed.replay:
                            # Capture the request-owned page generation BEFORE this exact
                            # replay is delivered. Filling its initial response cannot
                            # satisfy the later remount proof.
                            ticket.render_before = await page.evaluate_handle(
                                """scope => {
                                const region = document.querySelector(
                                    'section[aria-label="Article outcomes"]');
                                const selected = document.querySelector(
                                    'select[aria-label="Active organization"]');
                                const job = [...document.querySelectorAll('h4')].some(
                                    node => node.textContent === 'Job ' + scope.job);
                                return selected?.value === scope.organization && job && region
                                    ? region.querySelector(':scope > div:last-child') : null;
                            }""",
                                {"organization": observed.organization, "job": observed.job},
                            )
                        replay_changed.set()
                        if ticket is observed.replay and hold is not None and offered is not None:
                            offered.set()
                            await asyncio.wait_for(hold.wait(), timeout=8)
                    try:
                        await route.fulfill(
                            status=reply["status"], headers=reply["headers"], body=body
                        )
                        if observed is not None:
                            observed.finish(ticket, True)
                            replay_changed.set()
                    except Error:
                        if observed is not None:
                            observed.finish(ticket, False)
                            replay_changed.set()
                        if incoming.failure != "net::ERR_ABORTED":
                            # Fail immediately with a fixed category rather than
                            # filling stderr with repeated async callback stacks.
                            print(
                                json.dumps(
                                    {
                                        "kind": "failure",
                                        "stage": stage,
                                        "error": "Error",
                                        "reason": route_failure_reason(incoming.failure),
                                        "api_statuses": api_statuses,
                                    }
                                ),
                                flush=True,
                            )
                            raise
                    return
                path = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
                if incoming.method != "GET" or path not in manifest or parsed.query:
                    await route.abort("blockedbyclient")
                    return
                body = (root / path).read_bytes()
                if len(body) > 1048576 or hashlib.sha256(body).hexdigest() != manifest[path]:
                    raise RuntimeError("Actual reviewed asset integrity required")
                mime = (
                    "text/html"
                    if path.endswith(".html")
                    else "text/javascript"
                    if path.endswith(".js")
                    else "text/css"
                    if path.endswith(".css")
                    else "image/svg+xml"
                )
                accepted += 1
                await route.fulfill(status=200, content_type=mime, body=body)

            await context.route("**/*", route_request)
            await context.route_web_socket(
                "**/*",
                lambda route: route.close(code=1008, reason="UI diagnostic excludes websockets"),
            )

            async def observe_download(download: Any) -> None:
                if not download.suggested_filename.startswith("emailmonitor-"):
                    raise RuntimeError("Bounded export filename required")
                await download.cancel()
                download_seen.set()

            page.on("download", observe_download)
            checkpoint("assets_session")
            await page.goto(ORIGIN, wait_until="domcontentloaded")
            await page.get_by_role("combobox", name="Active organization", exact=True).wait_for()
            await select_index(
                page,
                page.get_by_role("combobox", name="Active organization", exact=True),
                (
                    await page.get_by_role("combobox", name="Active organization", exact=True)
                    .locator("option")
                    .evaluate_all("nodes => nodes.map(node => node.value)")
                ).index(setup["initial_organization"]),
            )
            await page.get_by_role("heading", name="Synthetic tenant 0", exact=True).wait_for()
            if setup.get("journey") == "controlled_lifecycle":
                checkpoint("pause_resume")
                await lifecycle_journey(page, channel, setup, checkpoint)
                # Leave the live job subscription through the ordinary keyboard UI.
                await activate(
                    page, page.get_by_role("button", name="Back to recent jobs", exact=True)
                )
                await expect(
                    page.get_by_role("table", name="Recent authorized jobs", exact=True)
                ).to_be_visible()
                await settle_lifecycle_requests(channel)
                checkpoint("final_cleanup")
                print(
                    json.dumps(
                        {
                            "kind": "result",
                            "journey": "controlled_lifecycle",
                            "diagnostic": "synthetic-operator-ui",
                            "keyboard": True,
                            "confirmed_cancel": True,
                            "retained_review_export": True,
                            "continuation": True,
                            "late_mutation_scope": True,
                            "network_errno": network,
                            "interfaces": interfaces,
                        }
                    ),
                    flush=True,
                )
                return
            if setup.get("journey") in ("controlled_browser", "controlled_keyword_browser"):
                keyword_browser = setup["journey"] == "controlled_keyword_browser"
                browser_expected_addresses = (
                    (
                        "alex.chen@example.org",
                        "ravi.das@example.org",
                        "noor.ibrahim@example.org",
                        "elena.park@example.org",
                    )
                    if keyword_browser
                    else ("elena.park@example.org",)
                )
                checkpoint("source_review")
                await activate(page, page.get_by_role("button", name="Sources", exact=True))
                profile = page.get_by_role("combobox", name="Synthetic policy profile", exact=True)
                await expect(profile).to_have_value("html")
                await select_index(page, profile, 2)
                await expect(profile).to_have_value("html_browser")
                await activate(
                    page,
                    page.get_by_role("button", name="Request synthetic source review", exact=True),
                )
                await page.get_by_role(
                    "button", name="Approve synthetic policy", exact=True
                ).wait_for()
                # Changing an unsubmitted proposal must not alter the pending record
                # that the separate approval dialog actually authorizes.
                await select_index(page, profile, 0)
                await expect(profile).to_have_value("html")
                await activate(
                    page,
                    page.get_by_role("button", name="Approve synthetic policy", exact=True),
                )
                dialog = page.get_by_role("dialog")
                await expect(dialog).to_contain_text("version 1, revision 1")
                await expect(dialog).to_contain_text("browser")
                await expect(dialog).to_contain_text(
                    '"raw_hours":24,"excerpt_days":30,"contact_days":90'
                )
                await activate(
                    page,
                    page.get_by_role("button", name="Confirm approve synthetic policy", exact=True),
                )
                await dialog.wait_for(state="hidden")
                checkpoint("url_plan")
                await activate(
                    page,
                    page.get_by_role("navigation", name="Workspace", exact=True).get_by_role(
                        "button", name="New extraction", exact=True
                    ),
                )
                if keyword_browser:
                    await type_text(
                        page, page.get_by_label("Keyword", exact=True), "Myocardial Infarction"
                    )
                else:
                    await activate(page, page.get_by_role("button", name="URL", exact=True))
                    await type_text(
                        page,
                        page.get_by_label("Search-results or article URL", exact=True),
                        "https://synthetic.publisher.example/tooltip.html",
                    )
                browser_opt_in = page.get_by_role(
                    "checkbox",
                    name="Allow synthetic tooltip-only browser work",
                    exact=True,
                )
                await expect(browser_opt_in).not_to_be_checked()
                # Native checkboxes toggle with Space; Enter submits this form.
                await focus(page, browser_opt_in)
                await page.keyboard.press("Space")
                await expect(browser_opt_in).to_be_checked()
                await activate(
                    page,
                    page.get_by_role("button", name="Create and validate plan", exact=True),
                )
                await page.get_by_role("region", name="Server source plan").wait_for()
                await activate(
                    page,
                    page.get_by_role("button", name="Launch extraction", exact=True),
                )
                await page.get_by_role(
                    "heading", name=re.compile(r"^Job [0-9a-f-]{36}$")
                ).wait_for()
                checkpoint("url_worker")
                await channel.request({"kind": "control", "action": "publish"})
                # Separate controlled browser wait: HTTP plus isolated DOM acquisitions
                # retain source spacing. Existing static/provider waits are unchanged.
                await page.get_by_text("completed", exact=True).first.wait_for(timeout=75000)
                checkpoint("evidence_review")
                # Explicit tooltip correspondence is already accepted; still save a human review.
                evidence_checkpoint("contacts")
                await activate(page, page.get_by_role("button", name="Contacts", exact=True))
                for address in browser_expected_addresses:
                    row = page.get_by_role("row").filter(has_text=address)
                    await expect(row).to_have_count(1)
                    evidence_checkpoint("open")
                    await activate(
                        page,
                        row.get_by_role("button", name="Evidence and review", exact=True),
                    )
                    evidence_checkpoint("citation")
                    await page.get_by_role(
                        "heading", name="Actual retained citation", exact=True
                    ).wait_for()
                    evidence_checkpoint("reason")
                    await type_text(
                        page,
                        page.get_by_label("Reason", exact=True),
                        (
                            "Inspected combined keyword citation for " + address
                            if keyword_browser
                            else "Inspected controlled tooltip citation through keyboard UI"
                        ),
                    )
                    evidence_checkpoint("save")
                    await activate(page, page.get_by_role("button", name="Save review", exact=True))
                    evidence_checkpoint("closed")
                    await page.get_by_role("dialog").wait_for(state="hidden")
                evidence_checkpoint("returned")
                await activate(page, page.get_by_role("button", name="Contacts", exact=True))
                for address in browser_expected_addresses:
                    await expect(page.get_by_role("row").filter(has_text=address)).to_have_count(1)
                checkpoint("export_preview")
                await activate(page, page.get_by_role("button", name="Exports", exact=True))
                for index in (0, 1):
                    await select_index(page, page.get_by_label(re.compile(r"^Format")), index)
                    await activate(
                        page,
                        page.get_by_role(
                            "button", name="Preview eligible export counts", exact=True
                        ),
                    )
                    await page.get_by_role("region", name="Current export preview").wait_for()
                    await activate(
                        page,
                        page.get_by_role("button", name="Create asynchronous export", exact=True),
                    )
                    await (
                        page.get_by_role("row")
                        .filter(has_text=" · " + ("xlsx" if index == 0 else "csv"))
                        .wait_for()
                    )
                    await channel.request({"kind": "control", "action": "wait_exports"})
                    await activate(
                        page,
                        page.get_by_role("button", name="Refresh current view", exact=True),
                    )
                    download_seen.clear()
                    export_row = page.get_by_role("row").filter(
                        has_text=" · " + ("xlsx" if index == 0 else "csv")
                    )
                    await activate(
                        page,
                        export_row.get_by_role("button", name="Download", exact=True),
                    )
                    await asyncio.wait_for(download_seen.wait(), timeout=5)
                checkpoint("readonly_role")
                await select_index(
                    page,
                    page.get_by_role("combobox", name="Active organization", exact=True),
                    (
                        await page.get_by_role("combobox", name="Active organization", exact=True)
                        .locator("option")
                        .evaluate_all("nodes => nodes.map(node => node.value)")
                    ).index(setup["other_organization"]),
                )
                await page.get_by_role("heading", name="Synthetic tenant 1", exact=True).wait_for()
                await page.get_by_text(
                    "No jobs yet. Create a bounded extraction plan.", exact=True
                ).wait_for()
                body = await page.locator("body").inner_text()
                if any(address in body for address in browser_expected_addresses):
                    raise RuntimeError("Browser contacts survived tenant switch")
                await activate(page, page.get_by_role("button", name="Sources", exact=True))
                await page.get_by_text(
                    "Source management unavailable for this role.", exact=True
                ).wait_for()
                await page.get_by_text(
                    "Approval needed. No current source policy.", exact=True
                ).wait_for()
                await expect(
                    page.get_by_role("combobox", name="Synthetic policy profile", exact=True)
                ).to_have_count(0)
                await expect(
                    page.get_by_role("button", name="Request synthetic source review", exact=True)
                ).to_have_count(0)
                await expect(
                    page.get_by_role("button", name="Approve synthetic policy", exact=True)
                ).to_have_count(0)
                await activate(page, page.get_by_role("button", name="Exports", exact=True))
                await page.get_by_text(
                    "Export capability is not available for this role.", exact=False
                ).wait_for()

                if context.service_workers or await page.evaluate(
                    "navigator.serviceWorker.getRegistrations().then(rows=>rows.length)"
                ):
                    raise RuntimeError("UI service workers must remain absent")

                async def browser_settled() -> None:
                    while channel.pending:
                        await asyncio.sleep(0.05)

                await asyncio.wait_for(browser_settled(), timeout=10)
                checkpoint("final_cleanup")
                print(
                    json.dumps(
                        {
                            "kind": "result",
                            "diagnostic": "synthetic-operator-ui",
                            "journey": setup["journey"],
                            "allow_browser": True,
                            "source_policy_review": True,
                            "keyboard": True,
                            "built_assets": accepted,
                            "sandbox": sandbox,
                            "network_errno": network,
                            "interfaces": interfaces,
                            "review": True,
                            "formats": ["xlsx", "csv"],
                            "tenant_switch": True,
                            "download_cancelled": True,
                        }
                    ),
                    flush=True,
                )
                await context.close()
                await browser.close()
                return
            if setup.get("journey") == "controlled_provider":
                direct_url = setup.get("direct_article_url", False)
                if type(direct_url) is not bool:
                    raise ValueError("Fixed controlled operator input required")
                expected_addresses = (
                    ("Second@example.org",)
                    if direct_url
                    else ("Second@example.org", "beta@example.org")
                )
                checkpoint("source_review")
                await activate(page, page.get_by_role("button", name="Sources", exact=True))
                profile = page.get_by_role("combobox", name="Synthetic policy profile", exact=True)
                await expect(profile).to_have_value("html")
                await select_index(page, profile, 1)
                await expect(profile).to_have_value("xml")
                await activate(
                    page,
                    page.get_by_role("button", name="Request synthetic source review", exact=True),
                )
                await page.get_by_role(
                    "button", name="Approve synthetic policy", exact=True
                ).wait_for()
                # Changing an unsubmitted proposal must not alter the pending record
                # that the separate approval dialog actually authorizes.
                await select_index(page, profile, 0)
                await expect(profile).to_have_value("html")
                await activate(
                    page, page.get_by_role("button", name="Approve synthetic policy", exact=True)
                )
                dialog = page.get_by_role("dialog")
                await expect(dialog).to_contain_text("version 1, revision 1")
                await expect(dialog).to_contain_text("fetch_xml")
                await expect(dialog).to_contain_text(
                    '"raw_hours":0,"excerpt_days":30,"contact_days":90'
                )
                await activate(
                    page,
                    page.get_by_role("button", name="Confirm approve synthetic policy", exact=True),
                )
                await dialog.wait_for(state="hidden")
                checkpoint("url_plan" if direct_url else "keyword_plan")
                await activate(
                    page,
                    page.get_by_role("navigation", name="Workspace", exact=True).get_by_role(
                        "button", name="New extraction", exact=True
                    ),
                )
                if direct_url:
                    await activate(page, page.get_by_role("button", name="URL", exact=True))
                    await type_text(
                        page,
                        page.get_by_label("Search-results or article URL", exact=True),
                        "https://synthetic.publisher.example/provider-doi.xml",
                    )
                else:
                    await type_text(
                        page,
                        page.get_by_label("Keyword", exact=True),
                        "Controlled provider journey",
                    )
                await activate(
                    page, page.get_by_role("button", name="Create and validate plan", exact=True)
                )
                await page.get_by_role("region", name="Server source plan").wait_for()
                await activate(
                    page, page.get_by_role("button", name="Launch extraction", exact=True)
                )
                await page.get_by_role(
                    "heading", name=re.compile(r"^Job [0-9a-f-]{36}$")
                ).wait_for()
                checkpoint("url_worker" if direct_url else "keyword_worker")
                await channel.request({"kind": "control", "action": "publish"})
                # Separate provider acceptance: three real acquisitions retain enforced
                # source spacing plus HTTPS/parser work. The static wait remains 8s.
                await page.get_by_text("completed", exact=True).first.wait_for(timeout=75000)
                checkpoint("evidence_review")
                await activate(page, page.get_by_role("button", name="Review queue", exact=True))
                for address in expected_addresses:
                    row = page.get_by_role("row").filter(has_text=address)
                    await expect(row).to_have_count(1)
                    await activate(
                        page, row.get_by_role("button", name="Evidence and review", exact=True)
                    )
                    await page.get_by_role(
                        "heading", name="Actual retained citation", exact=True
                    ).wait_for()
                    quality = page.get_by_role(
                        "region", name="Article observation quality", exact=True
                    )
                    await expect(quality).to_contain_text("Retained parser outcome:")
                    await expect(quality).to_contain_text(
                        "does not resolve affiliation uncertainty"
                    )
                    await expect(quality).not_to_contain_text(
                        "reasons are not recorded for this route"
                    )
                    await type_text(
                        page,
                        page.get_by_label("Reason", exact=True),
                        "Inspected controlled XML citation through keyboard UI",
                    )
                    await activate(page, page.get_by_role("button", name="Save review", exact=True))
                    await page.get_by_role("dialog").wait_for(state="hidden")
                await activate(page, page.get_by_role("button", name="Contacts", exact=True))
                for address in expected_addresses:
                    await expect(page.get_by_role("row").filter(has_text=address)).to_have_count(1)
                if direct_url:
                    await expect(
                        page.get_by_role("row").filter(has_text="beta@example.org")
                    ).to_have_count(0)
                checkpoint("export_preview")
                await activate(page, page.get_by_role("button", name="Exports", exact=True))
                for index in (0, 1):
                    await select_index(page, page.get_by_label(re.compile(r"^Format")), index)
                    await activate(
                        page,
                        page.get_by_role(
                            "button", name="Preview eligible export counts", exact=True
                        ),
                    )
                    await page.get_by_role("region", name="Current export preview").wait_for()
                    await activate(
                        page,
                        page.get_by_role("button", name="Create asynchronous export", exact=True),
                    )
                    await (
                        page.get_by_role("row")
                        .filter(has_text=" · " + ("xlsx" if index == 0 else "csv"))
                        .wait_for()
                    )
                    await channel.request({"kind": "control", "action": "wait_exports"})
                    await activate(
                        page, page.get_by_role("button", name="Refresh current view", exact=True)
                    )
                    download_seen.clear()
                    export_row = page.get_by_role("row").filter(
                        has_text=" · " + ("xlsx" if index == 0 else "csv")
                    )
                    await activate(
                        page, export_row.get_by_role("button", name="Download", exact=True)
                    )
                    await asyncio.wait_for(download_seen.wait(), timeout=5)
                checkpoint("readonly_role")
                await select_index(
                    page,
                    page.get_by_role("combobox", name="Active organization", exact=True),
                    (
                        await page.get_by_role("combobox", name="Active organization", exact=True)
                        .locator("option")
                        .evaluate_all("nodes => nodes.map(node => node.value)")
                    ).index(setup["other_organization"]),
                )
                await page.get_by_role("heading", name="Synthetic tenant 1", exact=True).wait_for()
                await page.get_by_text(
                    "No jobs yet. Create a bounded extraction plan.", exact=True
                ).wait_for()
                body = await page.locator("body").inner_text()
                if any(address in body for address in ("Second@example.org", "beta@example.org")):
                    raise RuntimeError("Provider contacts survived tenant switch")
                await activate(page, page.get_by_role("button", name="Sources", exact=True))
                await page.get_by_text(
                    "Source management unavailable for this role.", exact=True
                ).wait_for()
                await page.get_by_text(
                    "Approval needed. No current source policy.", exact=True
                ).wait_for()
                await expect(
                    page.get_by_role("combobox", name="Synthetic policy profile", exact=True)
                ).to_have_count(0)
                await expect(
                    page.get_by_role("button", name="Request synthetic source review", exact=True)
                ).to_have_count(0)
                await expect(
                    page.get_by_role("button", name="Approve synthetic policy", exact=True)
                ).to_have_count(0)
                await activate(page, page.get_by_role("button", name="Exports", exact=True))
                await page.get_by_text(
                    "Export capability is not available for this role.", exact=False
                ).wait_for()

                if context.service_workers or await page.evaluate(
                    "navigator.serviceWorker.getRegistrations().then(rows=>rows.length)"
                ):
                    raise RuntimeError("UI service workers must remain absent")

                async def provider_settled() -> None:
                    while channel.pending:
                        await asyncio.sleep(0.05)

                await asyncio.wait_for(provider_settled(), timeout=10)
                checkpoint("final_cleanup")
                print(
                    json.dumps(
                        {
                            "kind": "result",
                            "diagnostic": "synthetic-operator-ui",
                            "journey": "controlled_provider",
                            "direct_article_url": direct_url,
                            "source_policy_review": True,
                            "keyboard": True,
                            "built_assets": accepted,
                            "sandbox": sandbox,
                            "network_errno": network,
                            "interfaces": interfaces,
                            "review": True,
                            "formats": ["xlsx", "csv"],
                            "tenant_switch": True,
                            "download_cancelled": True,
                        }
                    ),
                    flush=True,
                )
                await context.close()
                await browser.close()
                return
            checkpoint("source_review")
            # Every action below is activated or entered through keyboard events.
            await activate(page, page.get_by_role("button", name="Sources", exact=True))
            await expect(
                page.get_by_role("combobox", name="Synthetic policy profile", exact=True)
            ).to_have_value("html")
            await activate(
                page, page.get_by_role("button", name="Request synthetic source review", exact=True)
            )
            await page.get_by_role("button", name="Approve synthetic policy", exact=True).wait_for()
            await activate(
                page, page.get_by_role("button", name="Approve synthetic policy", exact=True)
            )
            await activate(
                page,
                page.get_by_role("button", name="Confirm approve synthetic policy", exact=True),
            )
            await page.get_by_text("Current synthetic policy", exact=True).wait_for()
            checkpoint("keyword_plan")
            await activate(page, page.get_by_role("button", name="New extraction", exact=True))
            source_select = page.get_by_label(re.compile(r"^SourceSelect an existing source"))
            await select_index(page, source_select, 0)
            await expect(
                page.get_by_role("button", name="Create and validate plan", exact=True)
            ).to_be_disabled()
            await select_index(page, source_select, 1)
            await expect(source_select).to_have_value("synthetic-publisher")
            await type_text(page, page.get_by_label("Keyword", exact=True), "Myocardial Infarction")
            await activate(
                page, page.get_by_role("button", name="Create and validate plan", exact=True)
            )
            await page.get_by_role("region", name="Server source plan").wait_for()
            await activate(page, page.get_by_role("button", name="Launch extraction", exact=True))
            await page.get_by_text("Enumeration unknown", exact=False).wait_for()
            keyword_job = (
                await page.get_by_role(
                    "heading", name=re.compile(r"^Job [0-9a-f-]{36}$")
                ).inner_text()
            ).removeprefix("Job ")
            checkpoint("pause_resume")
            await activate(page, page.get_by_role("button", name="Pause", exact=True))
            await page.get_by_role("button", name="Resume", exact=True).wait_for()
            await activate(page, page.get_by_role("button", name="Resume", exact=True))
            await page.get_by_role("button", name="Pause", exact=True).wait_for()
            await activate(page, page.get_by_role("button", name="Cancel job", exact=True))
            await page.get_by_role("dialog").wait_for()
            await page.keyboard.press("Escape")
            await page.get_by_role("dialog").wait_for(state="hidden")
            checkpoint("old_replay")
            await channel.request({"kind": "control", "action": "hold_events"})
            await channel.request({"kind": "control", "action": "wait_held"})
            await select_index(
                page,
                page.get_by_role("combobox", name="Active organization", exact=True),
                (
                    await page.get_by_role("combobox", name="Active organization", exact=True)
                    .locator("option")
                    .evaluate_all("nodes => nodes.map(node => node.value)")
                ).index(setup["other_organization"]),
            )
            await page.get_by_role("heading", name="Synthetic tenant 1", exact=True).wait_for()
            await page.get_by_text(
                "No jobs yet. Create a bounded extraction plan.", exact=True
            ).wait_for()
            await channel.request({"kind": "control", "action": "release_contacts"})
            await select_index(
                page,
                page.get_by_role("combobox", name="Active organization", exact=True),
                (
                    await page.get_by_role("combobox", name="Active organization", exact=True)
                    .locator("option")
                    .evaluate_all("nodes => nodes.map(node => node.value)")
                ).index(setup["initial_organization"]),
            )
            await page.get_by_role("heading", name="Synthetic tenant 0", exact=True).wait_for()
            await activate(page, page.get_by_role("button", name="Jobs", exact=True))
            await activate(
                page, page.get_by_role("button", name="Open job " + keyword_job, exact=True)
            )
            checkpoint("keyword_worker")
            await channel.request({"kind": "control", "action": "publish"})
            await channel.request({"kind": "control", "action": "wait_jobs"})
            await activate(
                page, page.get_by_role("button", name="Refresh current view", exact=True)
            )
            await page.get_by_text("completed partial", exact=True).first.wait_for()
            await activate(page, page.get_by_role("button", name="Contacts", exact=True))
            await page.get_by_role("table", name="Current-authorized observed contacts").wait_for()
            checkpoint("contacts_retry")
            await channel.request({"kind": "control", "action": "fault_contacts"})
            await activate(
                page, page.get_by_role("button", name="Refresh current view", exact=True)
            )
            await page.get_by_text("Stale view.", exact=False).wait_for()
            await activate(
                page, page.get_by_role("button", name="Refresh current view", exact=True)
            )
            await page.get_by_text("Stale view.", exact=False).wait_for(state="hidden")
            checkpoint("evidence_review")
            await activate(
                page, page.get_by_role("button", name="Evidence and review", exact=True).first
            )
            await page.get_by_role(
                "heading", name="Actual retained citation", exact=True
            ).wait_for()
            quality = page.get_by_role("region", name="Article observation quality", exact=True)
            await quality.get_by_text(
                "Parser-specific reasons are not recorded for this route.", exact=True
            ).wait_for()
            await expect(quality).to_contain_text("Missing affiliations remain unobserved")
            metadata = page.get_by_role("region", name="Retained article metadata", exact=True)
            await expect(metadata).to_contain_text("Example Research Journal")
            await expect(metadata).to_contain_text("Content digest:")
            await expect(metadata).to_contain_text("no inferred calendar date")
            await activate(
                page,
                metadata.get_by_text(
                    "Inspect all retained metadata values and citations", exact=True
                ),
            )
            await expect(metadata.get_by_role("list")).to_be_visible()
            await expect(metadata).to_contain_text("Recorded date type:")
            history = page.get_by_role("region", name="Recorded review history", exact=True)
            await expect(history).to_contain_text("earliest 100 records")
            await channel.request({"kind": "control", "action": "hold_quality"})
            await activate(
                page,
                page.get_by_role("button", name="Refresh association and evidence", exact=True),
            )
            await channel.request({"kind": "control", "action": "wait_held"})
            await expect(quality).to_contain_text("Loading current article quality")
            await expect(quality).not_to_contain_text("Retained parser outcome:")
            await channel.request({"kind": "control", "action": "release_quality"})
            await expect(quality).to_contain_text("Retained parser outcome:")
            await channel.request({"kind": "control", "action": "fault_quality"})
            await activate(
                page,
                page.get_by_role("button", name="Refresh association and evidence", exact=True),
            )
            await expect(quality).to_contain_text("Current article quality is unavailable")
            await expect(quality).not_to_contain_text("Retained parser outcome:")
            await activate(
                page,
                page.get_by_role("button", name="Refresh association and evidence", exact=True),
            )
            await expect(quality).to_contain_text("Retained parser outcome:")
            evidence_checkpoint("escape_close")
            focus_trace = await start_evidence_focus_trace(page)
            await page.keyboard.press("Escape")
            await wait_evidence_closed(page)
            restored, evidence_focus_trace = await check_evidence_focus(page, focus_trace)
            if not restored:
                raise RuntimeError("Evidence dialog did not restore keyboard focus")
            evidence_focus_observations["escape_close"] = (
                evidence_focus_trace.model_dump()
                if isinstance(evidence_focus_trace, EvidenceFocusTrace)
                else "unavailable"
            )
            await activate(
                page, page.get_by_role("button", name="Evidence and review", exact=True).first
            )
            await activate(
                page,
                page.get_by_role("button", name="Refresh association and evidence", exact=True),
            )
            await expect(quality).to_contain_text("Retained parser outcome:")
            evidence_checkpoint("button_close")
            focus_trace = await start_evidence_focus_trace(page)
            await activate(page, page.get_by_role("button", name="Close evidence", exact=True))
            await wait_evidence_closed(page)
            restored, evidence_focus_trace = await check_evidence_focus(page, focus_trace)
            if not restored:
                raise RuntimeError("Evidence dialog did not restore keyboard focus")
            evidence_focus_observations["button_close"] = (
                evidence_focus_trace.model_dump()
                if isinstance(evidence_focus_trace, EvidenceFocusTrace)
                else "unavailable"
            )
            evidence_focus_trace = None
            await activate(
                page, page.get_by_role("button", name="Evidence and review", exact=True).first
            )
            await page.get_by_role(
                "heading", name="Actual retained citation", exact=True
            ).wait_for()
            await type_text(
                page, page.get_by_label("Reason", exact=True), "Synthetic keyboard evidence review"
            )
            await activate(page, page.get_by_role("button", name="Save review", exact=True))
            await page.get_by_role("dialog").wait_for(state="hidden")
            await activate(
                page, page.get_by_role("button", name="Evidence and review", exact=True).first
            )
            history = page.get_by_role("region", name="Recorded review history", exact=True)
            await expect(history).to_contain_text("Synthetic keyboard evidence review")
            await activate(page, history.locator("summary"))
            await expect(history.get_by_role("list")).to_be_visible()
            await expect(history).to_contain_text("Recorded action: accept")
            await expect(history).to_contain_text("Expected association revision:")
            await expect(history.locator("time").first).to_be_visible()
            await activate(page, page.get_by_role("button", name="Close evidence", exact=True))
            await wait_evidence_closed(page)
            # Real retained DOI filtering, using only the authored article-a metadata.
            paper_input = page.get_by_label(
                "Paper DOI (optional; across authorized jobs)", exact=True
            )
            await type_text(page, paper_input, "10.9999/synthetic.article-a")
            paper_table = page.get_by_role("table", name="Current-authorized observed contacts")
            await expect(paper_table.locator("tbody tr")).to_have_count(1)
            await expect(paper_table).to_contain_text("alex.chen@example.org")
            await type_text(page, paper_input, "10.9999/absent-paper")
            await expect(
                page.get_by_text("No contacts match these server filters.", exact=True)
            ).to_be_visible()
            await type_text(page, paper_input, "")
            await expect(paper_table.locator("tbody tr")).to_have_count(3)
            checkpoint("export_preview")
            # Explicit Review → accepted Contacts → Export; no cursor or preview travels.
            await activate(page, page.get_by_role("button", name="Review queue", exact=True))
            await type_text(page, paper_input, "10.9999/synthetic.article-a")
            retained_source = page.get_by_label(re.compile(r"^Retained source"))
            await select_index(page, retained_source, 1)
            await expect(retained_source).to_have_value("synthetic-publisher")
            await activate(
                page,
                page.get_by_role(
                    "button", name="View accepted results for this selection", exact=True
                ),
            )
            await assert_accepted_handoff(page)
            await expect(retained_source).to_have_value("synthetic-publisher")
            await expect(paper_table.locator("tbody tr")).to_have_count(1)
            await activate(
                page, page.get_by_role("button", name="Export this selection", exact=True)
            )
            await expect(paper_input).to_have_value("10.9999/synthetic.article-a")
            await expect(retained_source).to_have_value("synthetic-publisher")
            await expect(page.get_by_role("region", name="Selection handoff")).to_contain_text(
                "source: synthetic-publisher"
            )
            await expect(page.get_by_role("region", name="Selection handoff")).to_contain_text(
                "Accepted contacts"
            )
            await expect(
                page.get_by_role("button", name="Create asynchronous export", exact=True)
            ).to_have_count(0)
            await expect(
                page.get_by_role(
                    "checkbox",
                    name="Explicitly include unresolved observations, labeled as unaccepted",
                    exact=True,
                )
            ).not_to_be_checked()
            await activate(
                page,
                page.get_by_role("button", name="Preview eligible export counts", exact=True),
            )
            paper_preview = page.get_by_role("region", name="Current export preview")
            await expect(paper_preview).to_contain_text("1 contacts; 1 separate article outcomes")
            await expect(paper_preview).to_contain_text("Paper DOI: 10.9999/synthetic.article-a")
            await type_text(page, paper_input, "")
            await expect(paper_preview).not_to_be_visible()
            await activate(
                page, page.get_by_role("button", name="Preview eligible export counts", exact=True)
            )
            await page.get_by_role("region", name="Current export preview").wait_for()
            await focus(page, page.get_by_role("checkbox", name="affiliations", exact=True))
            await page.keyboard.press("Space")
            await page.get_by_role("region", name="Current export preview").wait_for(state="hidden")
            await activate(
                page, page.get_by_role("button", name="Preview eligible export counts", exact=True)
            )
            await page.get_by_role("region", name="Current export preview").wait_for()
            await activate(
                page, page.get_by_role("button", name="Create asynchronous export", exact=True)
            )
            checkpoint("export_worker")
            await channel.request({"kind": "control", "action": "wait_exports"})
            await activate(
                page, page.get_by_role("button", name="Refresh current view", exact=True)
            )
            await activate(page, page.get_by_role("button", name="Download", exact=True).first)
            await asyncio.wait_for(download_seen.wait(), timeout=5)
            checkpoint("metadata_screens")
            await activate(page, page.get_by_role("button", name="Usage", exact=True))
            await page.get_by_role("heading", name="Observed usage metadata", exact=True).wait_for()
            await page.get_by_text(
                "Fixture-probe quota has not been initialized.", exact=True
            ).wait_for()
            await activate(page, page.get_by_role("button", name="Audit", exact=True))
            await page.get_by_role("table", name="Authorized audit metadata").wait_for()
            await activate(page, page.get_by_role("button", name="Settings", exact=True))
            await page.get_by_role("table", name="Current organization members").wait_for()
            await page.get_by_role(
                "heading", name="Synthetic allowances and branding", exact=True
            ).wait_for()
            await type_text(
                page,
                page.get_by_label("Workspace label", exact=True),
                "Keyboard authored workspace",
            )
            await type_text(page, page.get_by_label("Literal accent color", exact=True), "#123456")
            await activate(
                page, page.get_by_role("button", name="Save synthetic configuration", exact=True)
            )
            await activate(
                page,
                page.get_by_role("button", name="Confirm save synthetic configuration", exact=True),
            )
            await page.get_by_role("dialog").wait_for(state="hidden")
            await page.get_by_text("Keyboard authored workspace", exact=True).wait_for()
            checkpoint("url_plan")
            replay_readiness = OutcomeReplayReadiness(setup["initial_organization"])
            observe_replay(replay_readiness)
            # A separate article URL takes the same real create/plan/worker path.
            await activate(page, page.get_by_role("button", name="New extraction", exact=True))
            await activate(page, page.get_by_role("button", name="URL", exact=True))
            await type_text(
                page,
                page.get_by_label("Search-results or article URL", exact=True),
                ORIGIN.replace("app.example.test", "synthetic.publisher.example")
                + "/no-contact.html",
            )
            await activate(
                page, page.get_by_role("button", name="Create and validate plan", exact=True)
            )
            await page.get_by_role("region", name="Server source plan").wait_for()
            await activate(page, page.get_by_role("button", name="Launch extraction", exact=True))
            await channel.request({"kind": "control", "action": "wait_jobs"})
            await activate(
                page, page.get_by_role("button", name="Refresh current view", exact=True)
            )
            checkpoint("url_worker")
            outcome_checkpoint("outcomes_actual_replay")
            # Share the original ten-second visibility budget with replay/render readiness.
            proof, rendered_opener = await wait_outcome_replay(
                page, replay_readiness, replay_changed
            )
            outcome_checkpoint("outcomes_actual_modal")
            outcome_region = page.get_by_role("region", name="Article outcomes", exact=True)
            opener = outcome_region.get_by_role(
                "button", name="Inspect article observation", exact=True
            )
            trace = await start_observation_trace(opener)
            observation_dialog = page.get_by_role(
                "dialog", name="Article observation details", exact=True
            )
            quality_failed = False
            try:
                await focus(page, opener)
                await require_outcome_render(page, replay_readiness, proof, rendered_opener)
                await page.keyboard.press("Enter")
                outcome_checkpoint("outcomes_actual_quality")
                await expect(observation_dialog).to_contain_text(
                    "Retained parser outcome: no contact"
                )
                await require_outcome_render(page, replay_readiness, proof, rendered_opener)
            except AssertionError:
                quality_failed = outcome_phase == "outcomes_actual_quality"
                raise
            finally:
                captured = await finish_observation_trace(trace)
                if quality_failed:
                    observation_trace = captured
            outcome_checkpoint("outcomes_actual_initial_focus")
            await expect(
                observation_dialog.get_by_role(
                    "button", name="Close article observation", exact=True
                )
            ).to_be_focused()
            outcome_checkpoint("outcomes_actual_escape")
            await page.keyboard.press("Escape")
            await expect(observation_dialog).not_to_be_visible()
            await expect(opener).to_be_focused()
            await rendered_opener.dispose()
            observe_replay(None)
            outcome_checkpoint("outcomes_actual_filter_preview")
            actual_job = (
                await page.get_by_role(
                    "heading", name=re.compile(r"^Job [0-9a-f-]{36}$")
                ).inner_text()
            ).removeprefix("Job ")
            actual_cell = outcome_region.get_by_role(
                "table", name="Current-authorized article outcomes"
            ).locator("tbody tr td:first-child")
            actual_item = re.search(r"Item: ([0-9a-f-]{36})", await actual_cell.inner_text())
            assert actual_item is not None
            presence_select = outcome_region.get_by_role(
                "combobox", name="Article-outcome candidate presence", exact=True
            )
            await select_index(page, presence_select, 1)
            await expect(outcome_region).to_contain_text("Page 1: 0 article outcomes")
            await select_index(page, presence_select, 2)
            await expect(outcome_region).to_contain_text("Page 1: 1 article outcomes")
            await activate(
                page,
                outcome_region.get_by_role("button", name="Contacts for this article", exact=True),
            )
            await expect(
                page.get_by_label("Article item UUID (optional; requires job)", exact=True)
            ).to_have_value(actual_item.group(1))
            await expect(
                page.get_by_text("No contacts match these server filters.", exact=True)
            ).to_be_visible()
            # Empty accepted Contacts still carries the exact selector, not an unfiltered fallback.
            await activate(
                page, page.get_by_role("button", name="Export this selection", exact=True)
            )
            await expect(
                page.get_by_label("Job UUID (blank selects authorized matching jobs)", exact=True)
            ).to_have_value(actual_job)
            await expect(
                page.get_by_label("Article item UUID (optional; requires job)", exact=True)
            ).to_have_value(actual_item.group(1))
            export_presence = page.get_by_role(
                "combobox", name="Article-outcome candidate presence", exact=True
            )
            await select_index(page, export_presence, 2)
            await activate(
                page,
                page.get_by_role("button", name="Preview eligible export counts", exact=True),
            )
            filtered_preview = page.get_by_role("region", name="Current export preview")
            await expect(filtered_preview).to_contain_text(
                "0 contacts; 1 separate article outcomes"
            )
            await expect(filtered_preview).to_contain_text(
                actual_job + " / " + actual_item.group(1)
            )
            await expect(filtered_preview).to_contain_text(
                "This predicate does not filter Contacts."
            )
            await select_index(page, export_presence, 3)
            await expect(filtered_preview).not_to_be_visible()
            await activate(
                page,
                page.get_by_role("button", name="Preview eligible export counts", exact=True),
            )
            await expect(filtered_preview).to_contain_text(
                "0 contacts; 0 separate article outcomes"
            )
            await type_text(
                page,
                page.get_by_label("Job UUID (blank selects authorized matching jobs)", exact=True),
                "",
            )
            await expect(
                page.get_by_label("Article item UUID (optional; requires job)", exact=True)
            ).to_have_value("")
            await expect(filtered_preview).not_to_be_visible()
            await activate(page, page.get_by_role("button", name="Jobs", exact=True))
            await select_index(
                page,
                outcome_region.get_by_role(
                    "combobox", name="Article-outcome candidate presence", exact=True
                ),
                0,
            )
            await authored_outcome_paging(
                page, str(setup["initial_organization"]), outcome_checkpoint
            )
            await prove_delayed_outcome_replay(
                page,
                str(setup["initial_organization"]),
                actual_job,
                observe_replay,
                replay_changed,
                outcome_checkpoint,
            )
            await activate(page, page.get_by_role("button", name="Contacts", exact=True))
            await authored_contact_request_ownership(page, outcome_checkpoint)
            await type_text(
                page,
                page.get_by_label("Search loaded scope", exact=True),
                "no-such-observed-person",
            )
            checkpoint("empty_contacts")
            await page.get_by_text("No contacts match these server filters.", exact=True).wait_for()
            await type_text(page, page.get_by_label("Search loaded scope", exact=True), "")
            await page.get_by_role("table", name="Current-authorized observed contacts").wait_for()
            old_address = (
                await page.get_by_role("table", name="Current-authorized observed contacts")
                .locator("tbody tr")
                .first.locator("td")
                .nth(2)
                .inner_text()
            ).splitlines()[0]
            checkpoint("old_contact_response")
            await channel.request({"kind": "control", "action": "hold_contacts"})
            await activate(
                page, page.get_by_role("button", name="Refresh current view", exact=True)
            )
            await channel.request({"kind": "control", "action": "wait_held"})
            await select_index(
                page,
                page.get_by_role("combobox", name="Active organization", exact=True),
                (
                    await page.get_by_role("combobox", name="Active organization", exact=True)
                    .locator("option")
                    .evaluate_all("nodes => nodes.map(node => node.value)")
                ).index(setup["other_organization"]),
            )
            await channel.request({"kind": "control", "action": "release_contacts"})
            await page.get_by_role("heading", name="Synthetic tenant 1", exact=True).wait_for()
            await page.get_by_text(
                "No jobs yet. Create a bounded extraction plan.", exact=True
            ).wait_for()
            if old_address in await page.locator("body").inner_text():
                raise RuntimeError("Previous organization results survived switch")
            await activate(page, page.get_by_role("button", name="Exports", exact=True))
            checkpoint("readonly_role")
            await page.get_by_text(
                "Export capability is not available for this role.", exact=False
            ).wait_for()
            if context.service_workers or await page.evaluate(
                "navigator.serviceWorker.getRegistrations().then(rows=>rows.length)"
            ):
                raise RuntimeError("UI service workers must remain absent")

            async def settled_requests() -> None:
                while channel.pending:
                    await asyncio.sleep(0.05)

            await asyncio.wait_for(settled_requests(), timeout=10)
            if old_address in await page.locator("body").inner_text():
                raise RuntimeError("Late previous-tenant response survived switch")
            await activate(page, page.get_by_role("button", name="Settings", exact=True))
            await page.get_by_text(
                "Current owner authority is required to change configuration.", exact=True
            ).wait_for()
            if await page.get_by_role(
                "button", name="Save synthetic configuration", exact=True
            ).is_enabled():
                raise RuntimeError("Read-only tenant configuration edit was enabled")
            if "Keyboard authored workspace" in await page.locator("body").inner_text():
                raise RuntimeError("Previous organization branding survived switch")
            checkpoint("final_cleanup")
            print(
                json.dumps(
                    {
                        "kind": "result",
                        "diagnostic": "synthetic-operator-ui",
                        "keyboard": True,
                        "built_assets": accepted,
                        "sandbox": sandbox,
                        "network_errno": network,
                        "interfaces": interfaces,
                        "api_statuses": api_statuses,
                        "keyword_partial": True,
                        "url_no_contact": True,
                        "actual_zero_contact_quality_dialog": True,
                        "actual_terminal_replay_render_ready": True,
                        "delayed_terminal_replay_render_proof": True,
                        "authored_127_outcome_paging": True,
                        "review": True,
                        "pause_resume_cancel_dismiss": True,
                        "dialog_focus_restore": True,
                        "evidence_focus_observations": evidence_focus_observations,
                        "configuration_keyboard": True,
                        "branding_scope_clear": True,
                        "optional_field_preview": True,
                        "usage_audit_settings": True,
                        "download_cancelled": True,
                        "org_switch": True,
                        "readonly_role": True,
                        "stale_network_retry": True,
                        "late_old_response_refused": True,
                        "late_old_replay_refused": True,
                    }
                ),
                flush=True,
            )
            await context.close()
            await browser.close()
    except Exception as error:
        name = type(error).__name__
        handoff = handoff_trace if stage == "export_preview" else None
        # Report before cancelling the owned stdin reader: its executor shutdown awaits host EOF.
        print(
            json.dumps(
                {
                    "kind": "failure",
                    "stage": stage,
                    "error": name if name in ERRORS else "UnexpectedError",
                    "reason": failure_reason(error),
                    **(
                        {
                            "handoff_trace": handoff.model_dump()
                            if isinstance(handoff, HandoffTrace)
                            else handoff
                        }
                        if handoff is not None
                        else {}
                    ),
                    **(
                        {"export_assertion_line": export_assertion_line(error)}
                        if stage == "export_preview" and type(error) is AssertionError
                        else {}
                    ),
                    **({"outcome_phase": outcome_phase} if outcome_phase is not None else {}),
                    **(
                        {
                            "observation_trace": observation_trace.model_dump()
                            if isinstance(observation_trace, ObservationTrace)
                            else observation_trace
                        }
                        if observation_trace is not None
                        else {}
                    ),
                    **(
                        {
                            "evidence_focus_trace": evidence_focus_trace.model_dump()
                            if isinstance(evidence_focus_trace, EvidenceFocusTrace)
                            else evidence_focus_trace
                        }
                        if failure_reason(error) == "dialog_focus_restore"
                        else {}
                    ),
                    **({"evidence_phase": evidence_phase} if evidence_phase is not None else {}),
                    **(
                        {
                            "focus_exhaustion": focus_exhaustion.model_dump()
                            if isinstance(focus_exhaustion, FocusExhaustion)
                            else focus_exhaustion
                        }
                        if failure_reason(error) == "keyboard_focus"
                        else {}
                    ),
                    "api_statuses": api_statuses,
                }
            ),
            flush=True,
        )
        raise
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())

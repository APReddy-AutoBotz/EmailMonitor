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
from typing import Any
from urllib.parse import parse_qs, urlsplit

from browser_acceptance import sandbox_status
from operator_ui_protocol import (
    ERRORS,
    OUTCOME_PHASES,
    STAGES,
    asset_manifest,
    failure_reason,
    route_failure_reason,
    route_headers_reason,
    validate_journey,
)
from playwright.async_api import (
    Error,
    Locator,
    Page,
    Request,
    Route,
    async_playwright,
    expect,
)

ORIGIN = "https://app.example.test"
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
    await target.wait_for(state="visible", timeout=10000)
    await expect(target).to_be_enabled(timeout=10000)
    for _ in range(100):
        if await target.evaluate("node => node === document.activeElement"):
            return
        await page.keyboard.press("Tab")
    raise RuntimeError("Control not reachable by keyboard")


async def activate(page: Page, target: Locator) -> None:
    await focus(page, target)
    await page.keyboard.press("Enter")


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
            for index in range(offset, min(offset + 25, 127))
        ]
        payload = {"items": items, "next_cursor": str(offset + 25) if offset + 25 < 127 else None}
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
            seen.extend(await rows.locator("td:first-child").all_text_contents())
            if number < 5:
                await activate(
                    page, region.get_by_role("button", name="Next article outcome page", exact=True)
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
                page, region.get_by_role("button", name="Previous article outcome page", exact=True)
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
            page, dialog.get_by_role("button", name="Refresh article observation", exact=True)
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
            page, dialog.get_by_role("button", name="Refresh article observation", exact=True)
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
        checkpoint("outcomes_late_job")
        # Abandon a held second page, change jobs, then release it. Old rows must not
        # overwrite the newly selected job or its page cursor.
        hold = True
        await activate(
            page, region.get_by_role("button", name="Next article outcome page", exact=True)
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
            page, page.get_by_role("button", name="Review queue for this job", exact=True)
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
        await activate(
            page, region.get_by_role("button", name="Next article outcome page", exact=True)
        )
        await asyncio.wait_for(requested.wait(), timeout=5)
        assert held_offset == 25
        organization_select = page.get_by_role("combobox", name="Active organization", exact=True)
        values = await organization_select.locator("option").evaluate_all(
            "nodes => nodes.map(node => node.value)"
        )
        await select_index(page, organization_select, 1 - values.index(organization))
        hold = False
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=5)
        await expect(page.locator("body")).not_to_contain_text("authored-outcome-")
        await expect(page.locator("dialog[open]")).to_have_count(0)
        await select_index(page, organization_select, values.index(organization))
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
    stage = "browser_launch"
    outcome_phase: str | None = None

    def checkpoint(value: str) -> None:
        nonlocal stage, outcome_phase
        if value not in STAGES:
            raise RuntimeError("Fixed UI stage required")
        stage = value
        outcome_phase = None
        print(json.dumps({"kind": "stage", "stage": value}), flush=True)

    def outcome_checkpoint(value: str) -> None:
        nonlocal outcome_phase
        if stage != "url_worker" or value not in OUTCOME_PHASES:
            raise RuntimeError("Fixed outcome diagnostic phase required")
        # Preserve emitted stage identity and its existing 32-frame cap.
        outcome_phase = value

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
                    headers = await api_headers(incoming, header_failure)
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
                    try:
                        await route.fulfill(
                            status=reply["status"], headers=reply["headers"], body=body
                        )
                    except Error:
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
                await activate(page, page.get_by_role("button", name="Contacts", exact=True))
                for address in browser_expected_addresses:
                    row = page.get_by_role("row").filter(has_text=address)
                    await expect(row).to_have_count(1)
                    await activate(
                        page,
                        row.get_by_role("button", name="Evidence and review", exact=True),
                    )
                    await page.get_by_role(
                        "heading", name="Actual retained citation", exact=True
                    ).wait_for()
                    await type_text(
                        page,
                        page.get_by_label("Reason", exact=True),
                        (
                            "Inspected combined keyword citation for " + address
                            if keyword_browser
                            else "Inspected controlled tooltip citation through keyboard UI"
                        ),
                    )
                    await activate(page, page.get_by_role("button", name="Save review", exact=True))
                    await page.get_by_role("dialog").wait_for(state="hidden")
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
            await page.keyboard.press("Escape")
            await page.get_by_role("dialog").wait_for(state="hidden")
            if not await page.get_by_role(
                "button", name="Evidence and review", exact=True
            ).first.evaluate("node => node === document.activeElement"):
                raise RuntimeError("Evidence dialog did not restore keyboard focus")
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
            checkpoint("export_preview")
            await activate(page, page.get_by_role("button", name="Exports", exact=True))
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
            await page.get_by_text("no contact", exact=True).first.wait_for()
            outcome_checkpoint("outcomes_actual_modal")
            outcome_region = page.get_by_role("region", name="Article outcomes", exact=True)
            opener = outcome_region.get_by_role(
                "button", name="Inspect article observation", exact=True
            )
            await activate(page, opener)
            observation_dialog = page.get_by_role(
                "dialog", name="Article observation details", exact=True
            )
            outcome_checkpoint("outcomes_actual_quality")
            await expect(observation_dialog).to_contain_text("Retained parser outcome: no contact")
            await expect(
                observation_dialog.get_by_role(
                    "button", name="Close article observation", exact=True
                )
            ).to_be_focused()
            outcome_checkpoint("outcomes_actual_escape")
            await page.keyboard.press("Escape")
            await expect(observation_dialog).not_to_be_visible()
            await expect(opener).to_be_focused()
            await authored_outcome_paging(
                page, str(setup["initial_organization"]), outcome_checkpoint
            )
            await activate(page, page.get_by_role("button", name="Contacts", exact=True))
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
                        "authored_127_outcome_paging": True,
                        "review": True,
                        "pause_resume_cancel_dismiss": True,
                        "dialog_focus_restore": True,
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
        # Report before cancelling the owned stdin reader: its executor shutdown awaits host EOF.
        print(
            json.dumps(
                {
                    "kind": "failure",
                    "stage": stage,
                    "error": name if name in ERRORS else "UnexpectedError",
                    "reason": failure_reason(error),
                    **({"outcome_phase": outcome_phase} if outcome_phase is not None else {}),
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

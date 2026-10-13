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
from urllib.parse import urlsplit

from browser_acceptance import sandbox_status
from operator_ui_protocol import (
    ERRORS,
    STAGES,
    asset_manifest,
    failure_reason,
    route_failure_reason,
    route_headers_reason,
)
from playwright.async_api import Error, Locator, Page, Request, Route, async_playwright, expect

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
        if self.identifier >= 512 or self.admitted >= 16:
            raise RuntimeError("UI diagnostic concurrency/request cap exceeded")
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
                raise RuntimeError("UI diagnostic concurrency/request cap exceeded")
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
            route_headers_reason(incoming.failure),
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

    def checkpoint(value: str) -> None:
        nonlocal stage
        if value not in STAGES:
            raise RuntimeError("Fixed UI stage required")
        stage = value
        print(json.dumps({"kind": "stage", "stage": value}), flush=True)

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
            checkpoint("source_review")
            # Every action below is activated or entered through keyboard events.
            await activate(page, page.get_by_role("button", name="Sources", exact=True))
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

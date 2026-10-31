"""Keyboard installed-service journey; reuse approved browser/RPC helpers unchanged."""

import asyncio
import base64
import errno
import hashlib
import json
import os
import re
import socket
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from browser_acceptance import sandbox_status
from installed_operator_redirects import (
    CallbackDeliveryTrace,
    InstalledDiagnostics,
    LoginRedirects,
    installed_relay_reason,
    observe_error_documents,
)
from operator_ui_protocol import (
    EVIDENCE_PHASES,
    ORIGIN,
    FocusExhaustion,
    InstalledExportStep,
    InstalledLoginPhase,
    InstalledReason,
    LoginTiming,
    failure_reason,
)
from playwright.async_api import Error, Page, Request, Route, async_playwright, expect

if TYPE_CHECKING:
    import operator_ui_acceptance as keyboard_helpers
    from operator_ui_acceptance import Channel, activate, focus, select_index, type_text
else:
    import operator_ui_helpers as keyboard_helpers
    from operator_ui_helpers import Channel, activate, focus, select_index, type_text


CHUNK = 12_288
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


async def assert_explicit_filter_refusal(page: Page) -> None:
    """Real server refusal must not silently broaden either requested filter."""
    await type_text(page, page.get_by_label("Requested journal"), "Synthetic Journal")
    await type_text(page, page.get_by_label("Requested article type"), "review")
    await activate(page, page.get_by_role("button", name="Create and validate plan", exact=True))
    filtered = page.get_by_role("region", name="Server source plan")
    await expect(filtered).to_contain_text("cannot apply the requested filters")
    await expect(filtered).to_contain_text("Requested journal: Synthetic Journal")
    await expect(filtered).to_contain_text("Requested article types: review")
    await expect(
        filtered.get_by_role("button", name="Launch extraction", exact=True)
    ).to_be_disabled()
    await type_text(page, page.get_by_label("Requested journal"), "")
    await type_text(page, page.get_by_label("Requested article type"), "")
    await expect(filtered).to_have_count(0)


async def inspect_contact_article_details(page: Page) -> None:
    await activate(
        page, page.get_by_role("button", name=re.compile(r"^View article details for ")).first
    )
    details = page.get_by_role("region", name="Article details")
    await expect(details).to_contain_text("Publication-date text")
    await activate(page, details.get_by_role("button", name="Close article details"))
    await expect(details).to_have_count(0)


async def transient_context_journey(page: Page) -> None:
    """Compare two real retained fixture citations without making a review link."""
    openers = page.get_by_role("button", name="Evidence and review", exact=True)
    if await openers.count() < 2:
        raise RuntimeError("Two retained observations are required for context acceptance")
    await activate(page, openers.first)
    dialog = page.get_by_role("dialog", name="Evidence and review", exact=True)
    await dialog.get_by_role("heading", name="Actual retained citation", exact=True).wait_for()
    await activate(page, dialog.get_by_text("Reference IDs for temporary context", exact=True))
    batch_text = await dialog.get_by_text(re.compile(r"^Observation batch ID: ")).inner_text()
    evidence_text = await dialog.get_by_text(re.compile(r"evidence ID: ")).first.inner_text()
    identifier = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    source = re.search(identifier, batch_text)
    evidence = re.search(identifier, evidence_text)
    if source is None or evidence is None:
        raise RuntimeError("Current retained context references unavailable")
    await activate(page, dialog.get_by_role("button", name="Close evidence", exact=True))
    await dialog.wait_for(state="hidden")

    found = False
    for index in range(1, await openers.count()):
        await activate(page, openers.nth(index))
        await dialog.get_by_role("heading", name="Actual retained citation", exact=True).wait_for()
        await activate(page, dialog.get_by_text("Reference IDs for temporary context", exact=True))
        current = await dialog.get_by_text(re.compile(r"^Observation batch ID: ")).inner_text()
        if source.group() not in current:
            found = True
            break
        await activate(page, dialog.get_by_role("button", name="Close evidence", exact=True))
        await dialog.wait_for(state="hidden")
    if not found:
        raise RuntimeError("A second retained observation is required for context acceptance")
    section = dialog.get_by_role("region", name="Temporary source context")
    await expect(section).to_contain_text("not attached or saved")
    await type_text(page, section.get_by_label("Other observation batch ID"), source.group())
    await type_text(page, section.get_by_label("Other observation evidence ID"), evidence.group())
    await activate(page, section.get_by_role("button", name="View temporary context", exact=True))
    await expect(section).to_contain_text("Source digest:")
    await expect(section).to_contain_text("does not establish the same person")
    await activate(page, section.get_by_role("button", name="Clear context", exact=True))
    await expect(section).not_to_contain_text("Source digest:")
    await activate(page, dialog.get_by_role("button", name="Close evidence", exact=True))
    await dialog.wait_for(state="hidden")


def isolation() -> list[int]:
    if os.environ.get("EM_ISOLATION_DIAGNOSTIC") != "synthetic-operator-ui" or os.geteuid() == 0:
        raise RuntimeError("Explicit nonroot installed operator diagnostic required")
    for key, value in {
        "HOME": "/tmp/browser-home",
        "XDG_CONFIG_HOME": "/tmp/browser-config",
        "CHROME_CONFIG_HOME": "/tmp/browser-config",
        "XDG_CACHE_HOME": "/tmp/browser-cache",
    }.items():
        if os.environ.get(key) != value:
            raise RuntimeError("Bounded approved browser paths required")
        Path(value).mkdir(mode=0o700, exist_ok=True)
    if any(os.environ.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")):
        raise RuntimeError("Proxy-free browser required")
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if (
        sorted(path.name for path in Path("/sys/class/net").iterdir()) != ["lo"]
        or int(status["CapEff"].strip(), 16)
        or status["NoNewPrivs"].strip() != "1"
        or status["Seccomp"].strip() != "2"
    ):
        raise RuntimeError("Original kernel restrictions required")
    network = []
    for family, target in [
        (socket.AF_INET, ("192.0.2.1", 443)),
        (socket.AF_INET6, ("2001:db8::1", 443)),
    ]:
        with socket.socket(family, socket.SOCK_STREAM) as stream:
            stream.settimeout(0.2)
            result = stream.connect_ex(target)
            if result != errno.ENETUNREACH:
                raise RuntimeError("Actual OS network denial required")
            network.append(result)
    return network


async def main() -> None:
    network = isolation()
    raw = await asyncio.to_thread(sys.stdin.buffer.readline, 65537)
    if not raw.endswith(b"\n") or len(raw) > 65536:
        raise RuntimeError("Bounded installed bootstrap required")
    setup = json.loads(raw)
    api, issuer, assets = setup["api"], setup["issuer"], setup["assets"]
    if setup["kind"] != "bootstrap" or setup["origin"] != ORIGIN or "cookies" in setup:
        raise RuntimeError("Installed login must not receive injected cookies")
    for origin in (api, issuer):
        if not re.fullmatch(r"https://127\.0\.0\.1:[1-9][0-9]{0,4}", origin):
            raise RuntimeError("Exact ephemeral HTTPS origin required")
    channel = Channel()
    receiver = asyncio.create_task(channel.read())
    statuses: list[int] = []
    received_assets: set[str] = set()
    callback_index_seen = False
    download_seen = asyncio.Event()
    stage = "browser_launch"
    export_step: InstalledExportStep | None = None
    evidence_phase: str | None = None
    diagnostics = InstalledDiagnostics()
    login_phase: InstalledLoginPhase | None = None
    login_timing = LoginTiming()
    callback_delivery = CallbackDeliveryTrace()
    callback_target: str | None = None
    login_reason: InstalledReason = "installed_login_failed"
    active_redirects: LoginRedirects | None = None

    def checkpoint(value: str) -> None:
        nonlocal stage, export_step, evidence_phase
        stage = value
        export_step = None
        evidence_phase = None
        print(json.dumps({"kind": "stage", "stage": value}), flush=True)

    def evidence_checkpoint(value: str) -> None:
        nonlocal evidence_phase
        if stage != "evidence_review" or value not in EVIDENCE_PHASES:
            raise RuntimeError("Fixed evidence diagnostic phase required")
        evidence_phase = value

    def export_checkpoint(phase: str, format_name: str | None) -> None:
        nonlocal export_step
        export_step = InstalledExportStep.model_validate({"phase": phase, "format": format_name})

    async def exchange(
        value: dict[str, object], operation: list[InstalledReason]
    ) -> dict[str, Any]:
        try:
            outer = await channel.request(
                {
                    "kind": "request",
                    "url": ORIGIN + "/api/v1/installed-relay",
                    "method": "POST",
                    "headers": {"content-type": "application/json"},
                    "body": json.dumps(value),
                }
            )
        except Exception as error:
            # This operation list belongs only to this route request. Preserve
            # the exact exception, and never retain or emit its message.
            operation[0] = installed_relay_reason(error)
            raise
        if outer["status"] != 200:
            operation[0] = "installed_relay_outer_status"
            raise RuntimeError("Installed HTTPS relay failed")
        return dict(json.loads(base64.b64decode(outer["body"], validate=True)))

    try:
        checkpoint("browser_launch")
        async with async_playwright() as playwright, AsyncExitStack() as observers:
            browser = await playwright.chromium.launch(
                channel="chromium",
                headless=True,
                chromium_sandbox=True,
                args=["--enable-automation"],
            )
            if browser.version != "153.0.8010.12":
                raise RuntimeError("Pinned Chromium required")
            context = await browser.new_context(service_workers="block", accept_downloads=False)
            if await context.cookies():
                raise RuntimeError("Fresh browser session required")
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
                raise RuntimeError("Chromium sandbox required")
            # This coordinator is available only after the original OS/browser
            # isolation checks. It cannot recover arbitrary failed navigations.
            redirects = LoginRedirects(api, issuer)
            active_redirects = redirects

            def failed_navigation(incoming: Request) -> None:
                if not redirects.active or not incoming.is_navigation_request():
                    return
                try:
                    redirects.observe_failure(
                        target=incoming.url,
                        method=incoming.method,
                        main_frame=(
                            incoming.is_navigation_request() and incoming.frame == page.main_frame
                        ),
                        redirected_from=incoming.redirected_from,
                        failure=incoming.failure,
                    )
                except RuntimeError as error:
                    # The permanent latch wakes the bounded login and prevents
                    # any success receipt. Never print an authentication URL.
                    diagnostics.capture(
                        error, redirects.failure_reason or "installed_redirect_order", login_phase
                    )

            def observer_failure(error: RuntimeError) -> None:
                diagnostics.capture(
                    error, redirects.failure_reason or "installed_redirect_order", login_phase
                )

            observer = await observers.enter_async_context(
                observe_error_documents(context, page, redirects, observer_failure)
            )
            page.on("requestfailed", failed_navigation)

            async def route_request(route: Route, operation: list[InstalledReason]) -> None:
                nonlocal callback_index_seen
                incoming = route.request
                parsed = urlsplit(incoming.url)
                origin = f"{parsed.scheme}://{parsed.netloc}"
                if origin not in {api, issuer} or parsed.fragment:
                    await route.abort("blockedbyclient")
                    return
                callback_generation = callback_delivery.generation
                callback_document = (
                    origin == api
                    and parsed.path == "/auth/complete"
                    and incoming.url == callback_target
                    and incoming.is_navigation_request()
                    and incoming.frame == page.main_frame
                    and login_phase == "callback_document"
                )
                if callback_document:
                    callback_delivery.observe(callback_generation, incoming, "request_received")
                operation[0] = "installed_route_headers"
                headers = {
                    key: value
                    for key, value in (await incoming.all_headers()).items()
                    if key in HEADERS
                }
                if origin == issuer:
                    # Test issuer and API use different ports of the mandatory same
                    # loopback hostname. Never forward host-scoped application cookies.
                    headers.pop("cookie", None)
                    headers.pop("x-csrf-token", None)
                asset = "index.html" if parsed.path in {"/", "/auth/complete"} else parsed.path[1:]
                static = origin == api and asset in assets
                response: dict[str, Any] = {}
                output = bytearray()
                if static:
                    size = setup["asset_sizes"][asset]
                    for offset in range(0, size, CHUNK):
                        operation[0] = "installed_route_relay"
                        response = await exchange(
                            {
                                "target": incoming.url,
                                "method": "GET",
                                "headers": headers,
                                "body": "",
                                "offset": offset,
                            },
                            operation,
                        )
                        operation[0] = "installed_static_range"
                        piece = base64.b64decode(response["body"], validate=True)
                        if response["status"] != 206 or len(piece) != min(CHUNK, size - offset):
                            raise RuntimeError("Actual installed static range missing")
                        output.extend(piece)
                    operation[0] = "installed_static_hash"
                    if hashlib.sha256(output).hexdigest() != assets[asset]:
                        raise RuntimeError(
                            "Actual installed web asset differs from package receipt"
                        )
                    received_assets.add(asset)
                    if callback_document:
                        callback_delivery.observe(callback_generation, incoming, "asset_verified")
                    callback_index_seen |= parsed.path == "/auth/complete"
                    response["headers"].pop("content-range", None)
                    response["status"] = 200
                else:
                    operation[0] = "installed_route_relay"
                    response = await exchange(
                        {
                            "target": incoming.url,
                            "method": incoming.method,
                            "headers": headers,
                            "body": incoming.post_data or "",
                            "offset": None,
                        },
                        operation,
                    )
                    output.extend(base64.b64decode(response["body"], validate=True))
                    statuses.append(response["status"])
                    if (
                        300 <= response["status"] < 400
                        or incoming.url == api + "/api/v1/auth/start"
                        or (origin == issuer and parsed.path == "/authorize")
                    ):
                        operation[0] = "installed_redirect_arm"
                        observer.arm(
                            incoming,
                            source=incoming.url,
                            method=incoming.method,
                            main_frame=(
                                incoming.is_navigation_request()
                                and incoming.frame == page.main_frame
                            ),
                            redirected_from=incoming.redirected_from,
                            status=response["status"],
                            headers=response["headers"],
                        )
                operation[0] = "installed_route_fulfill"
                await route.fulfill(
                    status=response["status"], headers=response["headers"], body=bytes(output)
                )
                if callback_document:
                    previous_delivery = callback_delivery.value
                    callback_delivery.observe(callback_generation, incoming, "fulfilled")
                    if previous_delivery != "fulfilled" and callback_delivery.value == "fulfilled":
                        login_timing.fulfilled()

            async def safe_route(route: Route) -> None:
                operation: list[InstalledReason] = ["installed_route_headers"]
                try:
                    await route_request(route, operation)
                except Exception as error:
                    if isinstance(error, Error) and route.request.failure == "net::ERR_ABORTED":
                        # Same observed navigation-abort allowance as the existing UI harness.
                        return
                    # Route callback exceptions otherwise surface asynchronously and
                    # can include request URLs. Emit only the fixed diagnostic shape.
                    fixed = diagnostics.capture(
                        error, redirects.failure_reason or operation[0], login_phase
                    )
                    print(
                        json.dumps(
                            {
                                "kind": "failure",
                                "stage": stage,
                                **fixed,
                                **(
                                    {"installed_export_step": export_step.model_dump()}
                                    if stage == "export_preview"
                                    and export_step is not None
                                    and fixed.get("installed_login_phase") is None
                                    else {}
                                ),
                                "api_statuses": statuses,
                            }
                        ),
                        flush=True,
                    )
                    try:
                        await route.abort("failed")
                    except Exception:
                        pass

            await context.route("**/*", safe_route)
            await context.route_web_socket(
                "**/*", lambda route: route.close(code=1008, reason="Excluded")
            )

            async def download(download: Any) -> None:
                if not download.suggested_filename.startswith("emailmonitor-"):
                    raise RuntimeError("Bounded export filename required")
                await download.cancel()
                download_seen.set()

            page.on("download", download)

            async def login() -> None:
                nonlocal login_phase, login_reason, callback_target
                callback_delivery.reset()
                callback_target = None
                login_timing.begin()
                async with asyncio.timeout(10):
                    login_phase = "initial_session"
                    login_timing.phase()
                    await expect(
                        page.get_by_role("button", name="Retry connection", exact=True)
                    ).to_be_enabled()
                    login_phase = "start_activation"
                    login_timing.phase()
                    redirects.begin()
                    await activate(
                        page,
                        page.get_by_role(
                            "link", name="Sign in with configured identity", exact=True
                        ),
                    )
                    login_phase = "authorize_failure"
                    login_timing.phase()
                    authorization = await observer.next_target()
                    login_phase = "authorize_navigation"
                    login_timing.phase()
                    try:
                        await page.goto(authorization, wait_until="domcontentloaded")
                    except Error:
                        # Only the separately observed exact failed child of the
                        # real issuer 303 can release its one-use callback target.
                        login_phase = "callback_failure"
                        login_timing.phase()
                        callback = await observer.next_target()
                    else:
                        login_reason = "installed_expected_navigation_mismatch"
                        raise RuntimeError("Expected isolated redirect failure missing")
                    login_phase = "callback_document"
                    login_timing.phase()
                    callback_target = callback
                    await page.goto(callback, wait_until="domcontentloaded")
                    login_phase = "callback_session"
                    login_timing.phase()
                    await expect(
                        page.get_by_role("button", name="Retry connection", exact=True)
                    ).to_be_enabled()
                    login_phase = "callback_complete"
                    login_timing.phase()
                    await activate(
                        page, page.get_by_role("button", name="Complete sign-in", exact=True)
                    )
                    await page.get_by_role(
                        "combobox", name="Active organization", exact=True
                    ).wait_for()
                    login_phase = "organization"
                    login_timing.phase()
                    organization = page.get_by_role(
                        "combobox", name="Active organization", exact=True
                    )
                    values = await organization.locator("option").evaluate_all(
                        "nodes => nodes.map(node => node.value)"
                    )
                    await select_index(
                        page, organization, values.index(setup["initial_organization"])
                    )
                    await page.get_by_role(
                        "heading", name="Synthetic tenant 0", exact=True
                    ).wait_for()
                    redirects.finish()
                    login_phase = None

            checkpoint("assets_session")
            await page.goto(api, wait_until="domcontentloaded")
            await login()
            if not callback_index_seen or 303 not in statuses:
                raise RuntimeError("Actual callback navigation missing")
            controlled_pdf = setup.get("journey") == "installed-authored-pdf"
            controlled_xml = setup.get("journey") == "installed-controlled-xml" or controlled_pdf
            if controlled_xml:
                from installed_xml_browser import xml_journey

                job = await xml_journey(
                    page,
                    channel,
                    setup,
                    checkpoint,
                    login,
                    download_seen,
                    export_checkpoint,
                    evidence_checkpoint,
                )
            else:
                checkpoint("source_review")
                await activate(page, page.get_by_role("button", name="Sources", exact=True))
                await expect(
                    page.get_by_role("combobox", name="Synthetic policy profile", exact=True)
                ).to_have_value("html")
                await activate(
                    page,
                    page.get_by_role("button", name="Request synthetic source review", exact=True),
                )
                await activate(
                    page, page.get_by_role("button", name="Approve synthetic policy", exact=True)
                )
                await activate(
                    page,
                    page.get_by_role("button", name="Confirm approve synthetic policy", exact=True),
                )
                await page.get_by_role("dialog").wait_for(state="hidden")
                await page.get_by_text("Current synthetic policy", exact=True).wait_for()
                checkpoint("keyword_plan")
                await activate(page, page.get_by_role("button", name="New extraction", exact=True))
                await assert_refused_preflight(page, api, setup["initial_organization"])
                await type_text(
                    page, page.get_by_label("Keyword", exact=True), "Myocardial Infarction"
                )
                await assert_explicit_filter_refusal(page)
                await activate(
                    page, page.get_by_role("button", name="Create and validate plan", exact=True)
                )
                await page.get_by_role("region", name="Server source plan").wait_for()
                await assert_supported_preflight(page)
                await activate(
                    page, page.get_by_role("button", name="Launch extraction", exact=True)
                )
                job = (
                    await page.get_by_role(
                        "heading", name=re.compile(r"^Job [0-9a-f-]{36}$")
                    ).inner_text()
                ).removeprefix("Job ")
                checkpoint("keyword_worker")
                # Host shortens only this browser-created session to a future deadline,
                # waits for elapsed expiry, then releases the independent publisher.
                await channel.request({"kind": "control", "action": "publish"})
                # A fresh navigation avoids racing the UI's simultaneous expired-session
                # notification. The new document must obtain its own real 401/session.
                await page.goto(api, wait_until="domcontentloaded")
                await page.get_by_role(
                    "link", name="Sign in with configured identity", exact=True
                ).wait_for()
                await login()
                await activate(page, page.get_by_role("button", name="Jobs", exact=True))
                await activate(page, page.get_by_role("button", name="Open job " + job, exact=True))
                # Initial progress fetch and real scoped SSE update this rendered
                # status. Repeated global refreshes would overlap seven resource
                # requests while their previous relay calls are still outstanding.
                async with asyncio.timeout(55):
                    await page.get_by_text("completed partial", exact=True).wait_for(
                        state="visible", timeout=55000
                    )
                await channel.request({"kind": "control", "action": "wait_jobs"})
                checkpoint("evidence_review")
                await activate(page, page.get_by_role("button", name="Contacts", exact=True))
                await inspect_contact_article_details(page)
                await transient_context_journey(page)
                await activate(
                    page, page.get_by_role("button", name="Evidence and review", exact=True).first
                )
                await page.get_by_role(
                    "heading", name="Actual retained citation", exact=True
                ).wait_for()
                await type_text(
                    page,
                    page.get_by_label("Reason", exact=True),
                    "Installed synthetic evidence review",
                )
                await activate(page, page.get_by_role("button", name="Save review", exact=True))
                await page.get_by_role("dialog").wait_for(state="hidden")
                checkpoint("export_preview")
                export_checkpoint("navigate", None)
                await activate(page, page.get_by_role("button", name="Exports", exact=True))
                for index, format_name in enumerate(("xlsx", "csv")):
                    export_checkpoint("format", format_name)
                    await select_index(page, page.get_by_label(re.compile(r"^Format")), index)
                    if format_name == "csv":
                        outcomes = page.get_by_role(
                            "checkbox",
                            name=re.compile(r"^Include separate article-outcome dataset"),
                        )
                        await focus(page, outcomes)
                        await page.keyboard.press("Space")
                        await expect(outcomes).not_to_be_checked()
                    export_checkpoint("preview_activate", format_name)
                    await activate(
                        page,
                        page.get_by_role(
                            "button", name="Preview eligible export counts", exact=True
                        ),
                    )
                    export_checkpoint("preview_wait", format_name)
                    await page.get_by_role("region", name="Current export preview").wait_for()
                    export_checkpoint("create", format_name)
                    await activate(
                        page,
                        page.get_by_role("button", name="Create asynchronous export", exact=True),
                    )
                    row = page.get_by_role("row").filter(has_text=" · " + format_name)
                    export_checkpoint("row_wait", format_name)
                    await row.wait_for()
                    export_checkpoint("ready_wait", format_name)
                    async with asyncio.timeout(30):
                        while not await row.get_by_role(
                            "button", name="Download", exact=True
                        ).is_enabled():
                            await asyncio.sleep(0.4)
                            export_checkpoint("refresh", format_name)
                            await activate(
                                page,
                                page.get_by_role("button", name="Refresh current view", exact=True),
                            )
                            export_checkpoint("ready_wait", format_name)
                    download_seen.clear()
                    export_checkpoint("download_activate", format_name)
                    await activate(page, row.get_by_role("button", name="Download", exact=True))
                    export_checkpoint("download_wait", format_name)
                    await asyncio.wait_for(download_seen.wait(), timeout=5)
                export_checkpoint("verify", None)
                await channel.request({"kind": "control", "action": "wait_exports"})
                checkpoint("url_plan")
                await activate(page, page.get_by_role("button", name="New extraction", exact=True))
                await activate(page, page.get_by_role("button", name="URL", exact=True))
                await type_text(
                    page,
                    page.get_by_label("Search-results or article URL", exact=True),
                    "https://synthetic.publisher.example/no-contact.html",
                )
                await activate(
                    page, page.get_by_role("button", name="Create and validate plan", exact=True)
                )
                await page.get_by_role("region", name="Server source plan").wait_for()
                await activate(
                    page, page.get_by_role("button", name="Launch extraction", exact=True)
                )
                checkpoint("url_worker")
                async with asyncio.timeout(30):
                    await page.get_by_text("completed", exact=True).wait_for(
                        state="visible", timeout=30000
                    )
                await page.get_by_text(
                    "1 of 1 discovered article units terminal", exact=True
                ).wait_for()
                outcomes = page.get_by_role("table", name="Actual article outcomes and failures")
                await expect(outcomes.get_by_role("row")).to_have_count(2)
                await expect(
                    outcomes.get_by_role("row").nth(1).locator("td:nth-child(2), td:nth-child(3)")
                ).to_have_text(["no contact", "no contact"])
                if setup.get("retained_reuse") is True:
                    checkpoint("reuse_plan")
                    await activate(
                        page, page.get_by_role("button", name="New extraction", exact=True)
                    )
                    await activate(page, page.get_by_role("button", name="URL", exact=True))
                    await type_text(
                        page,
                        page.get_by_label("Search-results or article URL", exact=True),
                        "https://synthetic.publisher.example/article-a.html",
                    )
                    reuse_checkbox = page.get_by_label(
                        "Request retained observation reuse", exact=True
                    )
                    await focus(page, reuse_checkbox)
                    await page.keyboard.press("Space")
                    await expect(reuse_checkbox).to_be_checked()
                    cutoff = page.get_by_label("Reuse freshness cutoff UTC", exact=True)
                    await focus(page, cutoff)
                    # Native datetime controls have locale-dependent keyboard segments;
                    # Playwright's native input action emits the normal input/change events.
                    await cutoff.fill("2000-01-01T00:00")
                    await activate(
                        page,
                        page.get_by_role("button", name="Create and validate plan", exact=True),
                    )
                    await page.get_by_role("region", name="Server source plan").wait_for()
                    await activate(
                        page, page.get_by_role("button", name="Launch extraction", exact=True)
                    )
                    checkpoint("reuse_worker")
                    async with asyncio.timeout(30):
                        await page.get_by_text("completed", exact=True).wait_for(
                            state="visible", timeout=30000
                        )
                    checkpoint("reuse_results")
                    target_outcomes = page.get_by_role(
                        "table", name="Current-authorized article outcomes"
                    )
                    await target_outcomes.get_by_text("Reused observation", exact=False).wait_for()
                    await expect(
                        target_outcomes.get_by_role("row").nth(1).locator("td:nth-child(2)")
                    ).to_have_text("needs review")
                    checkpoint("reuse_review")
                    await activate(
                        page,
                        page.get_by_role("button", name="Review queue for this job", exact=True),
                    )
                    await page.get_by_role(
                        "button", name="Evidence and review", exact=True
                    ).first.wait_for()
                    checkpoint("reuse_export")
                    await activate(
                        page,
                        page.get_by_role(
                            "button", name="View accepted results for this selection", exact=True
                        ),
                    )
                    await activate(
                        page, page.get_by_role("button", name="Export this selection", exact=True)
                    )
                    checkpoint("reuse_preview")
                    await activate(
                        page,
                        page.get_by_role(
                            "button", name="Preview eligible export counts", exact=True
                        ),
                    )
                    preview = page.get_by_role("region", name="Current export preview")
                    await preview.wait_for()
                    await preview.get_by_text(re.compile(r"^0 contacts; ")).wait_for()
            checkpoint("readonly_role")
            organization = page.get_by_role("combobox", name="Active organization", exact=True)
            values = await organization.locator("option").evaluate_all(
                "nodes => nodes.map(node => node.value)"
            )
            await select_index(page, organization, values.index(setup["other_organization"]))
            await page.get_by_role("heading", name="Synthetic tenant 1", exact=True).wait_for()
            await page.get_by_text(
                "No jobs yet. Create a bounded extraction plan.", exact=True
            ).wait_for()
            if controlled_xml:
                tenant_body = await page.locator("body").inner_text()
                if any(
                    address in tenant_body
                    for address in (
                        "Second@example.org",
                        "beta@example.org",
                        "alex.chen@example.org",
                    )
                ):
                    raise RuntimeError("Installed XML contacts survived tenant switch")
            # Read-only adversarial browser probe complements the keyboard switch:
            # a tenant-B path cannot return the known tenant-A job.
            denied = await page.evaluate(
                "async ({organization, job}) => (await fetch('/api/v1/organizations/' + "
                "organization + '/jobs/' + job, {credentials:'same-origin'})).status",
                {"organization": setup["other_organization"], "job": job},
            )
            if denied != 404:
                raise RuntimeError("Foreign tenant job disclosure was not refused")
            await activate(page, page.get_by_role("button", name="Sources", exact=True))
            await page.get_by_text(
                "Source management unavailable for this role.", exact=True
            ).wait_for()
            if await page.get_by_role(
                "button", name="Request synthetic source review", exact=True
            ).count():
                raise RuntimeError("Viewer source mutation control leaked")
            await activate(page, page.get_by_role("button", name="Exports", exact=True))
            await page.get_by_text(
                "Export capability is not available for this role.", exact=False
            ).wait_for()
            if context.service_workers or await page.evaluate(
                "navigator.serviceWorker.getRegistrations().then(rows=>rows.length)"
            ):
                raise RuntimeError("Service workers forbidden")
            async with asyncio.timeout(10):
                while channel.pending:
                    await asyncio.sleep(0.05)
            await observers.aclose()
            await context.close()
            await browser.close()
            if received_assets != set(assets):
                raise RuntimeError("Complete installed built asset set was not served")
            checkpoint("final_cleanup")
            print(
                json.dumps(
                    {
                        "kind": "result",
                        "diagnostic": "synthetic-operator-ui",
                        "journey": (
                            "installed-authored-pdf"
                            if controlled_pdf
                            else "installed-controlled-xml"
                            if controlled_xml
                            else "installed-authored-service"
                        ),
                        "direct_article_url": setup.get("direct_article_url", False),
                        "keyboard": True,
                        "actual_callback": callback_index_seen,
                        "cookie_injection": False,
                        **redirects.receipt(),
                        "source_policy_review": True,
                        "review": True,
                        **(
                            {"url_no_contact": False}
                            if controlled_xml
                            else {"url_no_contact": True}
                        ),
                        "formats": ["xlsx", "csv"],
                        "tenant_switch": True,
                        "foreign_tenant_job_denied": True,
                        "session_expiry_reauthentication": True,
                        "network_errno": network,
                        "interfaces": ["lo"],
                        "sandbox": sandbox,
                        "built_assets": len(received_assets),
                        "download_cancelled": True,
                    }
                ),
                flush=True,
            )
    except BaseException as error:
        reason: str = (
            active_redirects.failure_reason
            if active_redirects is not None and active_redirects.failure_reason is not None
            else "installed_login_deadline"
            if login_phase is not None and type(error) is TimeoutError
            else login_reason
            if login_phase is not None
            else "keyboard_focus"
            if failure_reason(error) == "keyboard_focus"
            else "unknown"
        )
        fixed = diagnostics.capture(error, reason, login_phase)
        print(
            json.dumps(
                {
                    "kind": "failure",
                    "stage": stage,
                    **fixed,
                    **(
                        {"installed_login_timing": login_timing.snapshot().model_dump()}
                        if login_phase is not None
                        else {}
                    ),
                    **(
                        {"evidence_phase": evidence_phase}
                        if stage == "evidence_review" and evidence_phase is not None
                        else {}
                    ),
                    **(
                        {
                            "focus_exhaustion": keyboard_helpers.focus_exhaustion.model_dump()
                            if isinstance(keyboard_helpers.focus_exhaustion, FocusExhaustion)
                            else "unavailable"
                        }
                        if fixed.get("reason") == "keyboard_focus"
                        else {}
                    ),
                    **(
                        {"installed_callback_delivery": callback_delivery.value}
                        if login_phase == "callback_document"
                        and fixed.get("installed_login_phase") == "callback_document"
                        else {}
                    ),
                    **(
                        {"installed_export_step": export_step.model_dump()}
                        if stage == "export_preview"
                        and export_step is not None
                        and fixed.get("installed_login_phase") is None
                        else {}
                    ),
                    "api_statuses": statuses,
                }
            ),
            flush=True,
        )
        raise RuntimeError("Installed browser journey failed: " + fixed["error"]) from None
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)


async def assert_refused_preflight(page: Page, api: str, organization: str) -> None:
    """Exercise refinement without starting work; restore the empty keyword input."""
    keyword = page.get_by_label("Keyword", exact=True)
    await type_text(page, keyword, "Unsupported fixture topic")
    pattern = api + "/api/v1/organizations/" + organization + "/jobs/*/plan"
    held, release = asyncio.Event(), asyncio.Event()

    async def hold_response(route: Route) -> None:
        if route.request.method != "POST":
            await route.fallback()
            return
        held.set()
        await asyncio.wait_for(release.wait(), timeout=10)
        await route.fallback()

    await page.route(pattern, hold_response)
    try:
        async with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith("/plan")
        ) as stale_response:
            await activate(
                page, page.get_by_role("button", name="Create and validate plan", exact=True)
            )
            await asyncio.wait_for(held.wait(), timeout=10)
            await type_text(page, keyword, "Changed fixture topic")
            release.set()
        assert (await stale_response.value).status == 200
        await (
            page.get_by_role("status")
            .filter(has_text="Server plan checked. Review it before launching.")
            .wait_for()
        )
        await expect(page.get_by_role("region", name="Server source plan")).to_have_count(0)
    finally:
        release.set()
        await page.unroute(pattern, hold_response)

    async def malformed_response(route: Route) -> None:
        if route.request.method != "POST":
            await route.fallback()
            return
        await route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"plan": {"classification": ["article"], "reason": "unknown"}}),
        )

    await page.route(pattern, malformed_response)
    try:
        await activate(
            page, page.get_by_role("button", name="Create and validate plan", exact=True)
        )
        malformed = page.get_by_role("region", name="Server source plan")
        await malformed.wait_for()
        await expect(malformed).to_contain_text("Unavailable")
        await expect(malformed).to_contain_text("did not provide a recognized explanation")
        await expect(
            malformed.get_by_role("button", name="Launch extraction", exact=True)
        ).to_be_disabled()
    finally:
        await page.unroute(pattern, malformed_response)

    await type_text(page, keyword, "Unsupported fixture topic")
    await expect(page.get_by_role("region", name="Server source plan")).to_have_count(0)
    await activate(page, page.get_by_role("button", name="Create and validate plan", exact=True))
    summary = page.get_by_role("region", name="Server source plan")
    await summary.wait_for()
    await expect(summary).to_contain_text("Needs refinement")
    await expect(summary).to_contain_text(
        "This fixture source does not support the requested topic."
    )
    await expect(summary).to_contain_text("The server did not persist this plan")
    await expect(
        summary.get_by_role("button", name="Launch extraction", exact=True)
    ).to_be_disabled()
    await type_text(page, keyword, "")
    await expect(summary).to_have_count(0)


async def assert_supported_preflight(page: Page) -> None:
    """Check and repeat the existing authored job's plan before the original launch."""
    summary = page.get_by_role("region", name="Server source plan")
    await expect(summary).to_contain_text("Search results")
    await expect(
        summary.locator("dl > div").filter(has_text="Requested article limit")
    ).to_contain_text("50")
    await expect(
        summary.locator("dl > div").filter(has_text="Effective article cap")
    ).to_contain_text("50")
    await expect(
        summary.locator("dl > div").filter(has_text="Source-reported total at planning")
    ).to_contain_text("Unavailable")
    await expect(summary).to_contain_text("not permission to acquire it")
    async with page.expect_response(
        lambda response: response.request.method == "POST" and response.url.endswith("/plan")
    ) as repeated_plan:
        await activate(
            page, page.get_by_role("button", name="Create and validate plan", exact=True)
        )
    assert (await repeated_plan.value).status == 200
    await (
        page.get_by_role("status")
        .filter(has_text="Server plan checked. Review it before launching.")
        .wait_for()
    )
    await summary.wait_for()
    await expect(summary).to_contain_text("Search results")


if __name__ == "__main__":
    asyncio.run(main())

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
    InstalledDiagnostics,
    LoginRedirects,
    installed_relay_reason,
    observe_error_documents,
)
from operator_ui_protocol import ORIGIN, InstalledLoginPhase, InstalledReason
from playwright.async_api import Error, Request, Route, async_playwright, expect

if TYPE_CHECKING:
    from operator_ui_acceptance import Channel, activate, focus, select_index, type_text
else:
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
    diagnostics = InstalledDiagnostics()
    login_phase: InstalledLoginPhase | None = None
    login_reason: InstalledReason = "installed_login_failed"
    active_redirects: LoginRedirects | None = None

    def checkpoint(value: str) -> None:
        nonlocal stage
        stage = value
        print(json.dumps({"kind": "stage", "stage": value}), flush=True)

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
                    print(
                        json.dumps(
                            {
                                "kind": "failure",
                                "stage": stage,
                                **diagnostics.capture(
                                    error,
                                    redirects.failure_reason or operation[0],
                                    login_phase,
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
                nonlocal login_phase, login_reason
                async with asyncio.timeout(10):
                    login_phase = "initial_session"
                    await expect(
                        page.get_by_role("button", name="Retry connection", exact=True)
                    ).to_be_enabled()
                    login_phase = "start_activation"
                    redirects.begin()
                    await activate(
                        page,
                        page.get_by_role(
                            "link", name="Sign in with configured identity", exact=True
                        ),
                    )
                    login_phase = "authorize_failure"
                    authorization = await observer.next_target()
                    login_phase = "authorize_navigation"
                    try:
                        await page.goto(authorization, wait_until="domcontentloaded")
                    except Error:
                        # Only the separately observed exact failed child of the
                        # real issuer 303 can release its one-use callback target.
                        login_phase = "callback_failure"
                        callback = await observer.next_target()
                    else:
                        login_reason = "installed_expected_navigation_mismatch"
                        raise RuntimeError("Expected isolated redirect failure missing")
                    login_phase = "callback_document"
                    await page.goto(callback, wait_until="domcontentloaded")
                    login_phase = "callback_session"
                    await expect(
                        page.get_by_role("button", name="Retry connection", exact=True)
                    ).to_be_enabled()
                    login_phase = "callback_complete"
                    await activate(
                        page, page.get_by_role("button", name="Complete sign-in", exact=True)
                    )
                    await page.get_by_role(
                        "combobox", name="Active organization", exact=True
                    ).wait_for()
                    login_phase = "organization"
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
            checkpoint("source_review")
            await activate(page, page.get_by_role("button", name="Sources", exact=True))
            await expect(
                page.get_by_role("combobox", name="Synthetic policy profile", exact=True)
            ).to_have_value("html")
            await activate(
                page, page.get_by_role("button", name="Request synthetic source review", exact=True)
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
            await type_text(page, page.get_by_label("Keyword", exact=True), "Myocardial Infarction")
            await activate(
                page, page.get_by_role("button", name="Create and validate plan", exact=True)
            )
            await page.get_by_role("region", name="Server source plan").wait_for()
            await activate(page, page.get_by_role("button", name="Launch extraction", exact=True))
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
            async with asyncio.timeout(55):
                while not await page.get_by_text("completed partial", exact=True).count():
                    await asyncio.sleep(0.4)
                    await activate(
                        page, page.get_by_role("button", name="Refresh current view", exact=True)
                    )
            await channel.request({"kind": "control", "action": "wait_jobs"})
            checkpoint("evidence_review")
            await activate(page, page.get_by_role("button", name="Contacts", exact=True))
            await activate(
                page, page.get_by_role("button", name="Evidence and review", exact=True).first
            )
            await page.get_by_role(
                "heading", name="Actual retained citation", exact=True
            ).wait_for()
            await type_text(
                page, page.get_by_label("Reason", exact=True), "Installed synthetic evidence review"
            )
            await activate(page, page.get_by_role("button", name="Save review", exact=True))
            await page.get_by_role("dialog").wait_for(state="hidden")
            checkpoint("export_preview")
            await activate(page, page.get_by_role("button", name="Exports", exact=True))
            for index, format_name in enumerate(("xlsx", "csv")):
                await select_index(page, page.get_by_label(re.compile(r"^Format")), index)
                if format_name == "csv":
                    outcomes = page.get_by_role(
                        "checkbox", name=re.compile(r"^Include separate article-outcome dataset")
                    )
                    await focus(page, outcomes)
                    await page.keyboard.press("Space")
                    await expect(outcomes).not_to_be_checked()
                await activate(
                    page,
                    page.get_by_role("button", name="Preview eligible export counts", exact=True),
                )
                await page.get_by_role("region", name="Current export preview").wait_for()
                await activate(
                    page, page.get_by_role("button", name="Create asynchronous export", exact=True)
                )
                row = page.get_by_role("row").filter(has_text=" · " + format_name)
                await row.wait_for()
                async with asyncio.timeout(30):
                    while not await row.get_by_role(
                        "button", name="Download", exact=True
                    ).is_enabled():
                        await asyncio.sleep(0.4)
                        await activate(
                            page,
                            page.get_by_role("button", name="Refresh current view", exact=True),
                        )
                download_seen.clear()
                await activate(page, row.get_by_role("button", name="Download", exact=True))
                await asyncio.wait_for(download_seen.wait(), timeout=5)
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
            await activate(page, page.get_by_role("button", name="Launch extraction", exact=True))
            checkpoint("url_worker")
            async with asyncio.timeout(30):
                while not await page.get_by_text("completed", exact=True).count():
                    await asyncio.sleep(0.4)
                    await activate(
                        page, page.get_by_role("button", name="Refresh current view", exact=True)
                    )
            await page.get_by_text(
                "1 of 1 discovered article units terminal", exact=True
            ).wait_for()
            outcomes = page.get_by_role("table", name="Actual article outcomes and failures")
            await expect(outcomes.get_by_role("row")).to_have_count(2)
            await expect(outcomes.get_by_role("cell", name="no contact", exact=True)).to_have_count(
                1
            )
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
                        "journey": "installed-authored-service",
                        "keyboard": True,
                        "actual_callback": callback_index_seen,
                        "cookie_injection": False,
                        **redirects.receipt(),
                        "source_policy_review": True,
                        "review": True,
                        "url_no_contact": True,
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
            else "unknown"
        )
        fixed = diagnostics.capture(error, reason, login_phase)
        print(
            json.dumps(
                {
                    "kind": "failure",
                    "stage": stage,
                    **fixed,
                    "api_statuses": statuses,
                }
            ),
            flush=True,
        )
        raise RuntimeError("Installed browser journey failed: " + fixed["error"]) from None
    finally:
        receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())

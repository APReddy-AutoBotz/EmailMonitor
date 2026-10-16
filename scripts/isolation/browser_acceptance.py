"""Approved synthetic-only guest. Network-none OS boundary is mandatory."""

import asyncio
import base64
import errno
import hashlib
import json
import os
import socket
import sys
from collections.abc import Awaitable
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from emailmonitor.config import Settings
from emailmonitor.extraction.html import parse_article
from playwright.async_api import CDPSession, Error, Route, WebSocketRoute, async_playwright

URL = "https://synthetic.publisher.example/tooltip.html"
NETWORK_DIAGNOSTIC_URL = "http://192.0.2.1:443/"
POPUP_URL = "https://denied.fixture.example/popup"
POPUP_EVIDENCE_LIMIT = 16


def sandbox_status(text: str, evaluation: str) -> dict[str, bool]:
    """Require complete pinned Linux rows, never unrelated positive substrings."""
    diagnostic = json.dumps({"table_text": text[:4096], "evaluation": evaluation[:128]})
    expected_names = {
        "Layer 1 Sandbox",
        "PID namespaces",
        "Network namespaces",
        "Seccomp-BPF sandbox",
        "Seccomp-BPF sandbox supports TSYNC",
        "Ptrace Protection with Yama LSM (Broker)",
        "Ptrace Protection with Yama LSM (Non-broker)",
    }
    rows: dict[str, str] = {}
    if len(text) > 8192 or len(evaluation) > 128:
        raise RuntimeError("Chromium sandbox status exceeds bound: " + diagnostic)
    for line in text.splitlines():
        fields = [field.strip() for field in line.split("\t")]
        if len(fields) != 2 or fields[0] not in expected_names or fields[0] in rows:
            raise RuntimeError("Chromium sandbox status rows are invalid: " + diagnostic)
        rows[fields[0]] = fields[1]
    if set(rows) != expected_names or any(
        value not in ({"Namespace", "SUID", "None"} if name == "Layer 1 Sandbox" else {"Yes", "No"})
        for name, value in rows.items()
    ):
        raise RuntimeError("Chromium sandbox status rows are incomplete/unknown: " + diagnostic)
    result = {
        "namespace": rows["Layer 1 Sandbox"] == "Namespace",
        "pid_namespace": rows["PID namespaces"] == "Yes",
        "network_namespace": rows["Network namespaces"] == "Yes",
        "seccomp_bpf": rows["Seccomp-BPF sandbox"] == "Yes",
        "adequate": evaluation.strip() == "You are adequately sandboxed.",
    }
    if not all(result.values()):
        raise RuntimeError("Chromium's own sandbox evidence is missing: " + diagnostic)
    return result


def classify_browser_network_error(text: str) -> str:
    """Exact pinned navigation error only; independent OS evidence is mandatory."""
    first_line = text.split("\n", 1)[0]
    for code in ("ERR_ADDRESS_UNREACHABLE", "ERR_INTERNET_DISCONNECTED"):
        if first_line == f"Page.goto: net::{code} at {NETWORK_DIAGNOSTIC_URL}":
            return code
    raise RuntimeError("Browser network rejection code not established: " + text[:1024])


def trace_stage(name: str) -> None:
    print("synthetic-browser-stage:" + name, file=sys.stderr, flush=True)


def pending_task_evidence(value: object) -> str:
    labels = {
        "image",
        "stylesheet",
        "script",
        "iframe",
        "fetch_denied",
        "fetch_allowed",
        "post_denied",
        "xhr",
        "websocket",
        "service_worker",
    }
    if type(value) is not dict or not value or len(value) > len(labels):
        return '{"pending_task_evidence":"unavailable"}'
    if any(
        label not in labels or status not in ("pending", "fulfilled", "rejected")
        for label, status in value.items()
    ):
        return '{"pending_task_evidence":"unavailable"}'
    return json.dumps({"pending_task_evidence": value}, sort_keys=True)


async def boundary_readiness(readiness: Awaitable[object]) -> None:
    """Keep the existing ten-second gate independent of driver timeout delivery."""
    await asyncio.wait_for(readiness, timeout=10)


class FixtureChannel:
    """Serialize bounded exchanges; keep stdin reads off the Playwright loop."""

    def __init__(self, reader: BinaryIO, writer: TextIO) -> None:
        self.reader = reader
        self.writer = writer
        self.requests = 0
        self.lock = asyncio.Lock()
        self.failed = False

    async def request(self, url: str, method: str, resource: str) -> dict[str, object]:
        async with self.lock:
            if self.failed:
                raise RuntimeError("Gateway channel cannot be reused after failure")
            if self.requests >= 64:
                raise RuntimeError("Diagnostic request cap exceeded")
            self.requests += 1
            message = {
                "kind": "request",
                "identifier": self.requests,
                "url": url,
                "method": method,
                "resource": resource,
            }
            try:
                print(json.dumps(message), file=self.writer, flush=True)
                trace_stage(f"request_sent:{self.requests}:{resource[:32]}")
                raw = await asyncio.to_thread(self.reader.readline, 65537)
                if not raw.endswith(b"\n") or len(raw) > 65536:
                    raise RuntimeError("Bounded gateway reply missing")
                reply = json.loads(raw)
                if not isinstance(reply, dict):
                    raise RuntimeError("Gateway reply must be an object")
                trace_stage(f"reply_received:{self.requests}")
                return reply
            except BaseException:
                # Cancellation does not stop a threaded read. Poison the channel
                # so no subsequent exchange can consume that in-flight reply.
                self.failed = True
                raise


async def refuse_websocket(
    route: WebSocketRoute, channel: FixtureChannel, denied: list[str]
) -> None:
    reply = await channel.request(route.url, "GET", "websocket")
    if reply.get("status") != "denied":
        raise RuntimeError("WebSocket must be denied")
    denied.append("websocket")
    trace_stage("websocket_close_start")
    await route.close(code=1008, reason="synthetic boundary")
    trace_stage("websocket_close_complete")


async def wait_artifact_completion(
    popup_closed: asyncio.Event, download_cancelled: asyncio.Event, timeout: float = 3
) -> None:
    """Both independent callbacks must actually finish; missing evidence times out."""
    if not 0 < timeout <= 3:
        raise ValueError("Artifact observation cannot extend the three-second ceiling")
    await asyncio.wait_for(
        asyncio.gather(popup_closed.wait(), download_cancelled.wait()), timeout=timeout
    )


def popup_target_summary(parent: object, targets: object) -> dict[str, object]:
    """Emit no target metadata, only closed categories for this synthetic parent."""
    if not isinstance(parent, dict) or not isinstance(targets, dict):
        return {"status": "malformed"}
    info, rows = parent.get("targetInfo"), targets.get("targetInfos")
    if not isinstance(info, dict) or not isinstance(rows, list):
        return {"status": "malformed"}
    identifier = info.get("targetId")
    if (
        info.get("type") != "page"
        or info.get("url") != URL
        or type(identifier) is not str
        or not 0 < len(identifier) <= 128
    ):
        return {"status": "parent_unverified"}
    if len(rows) > POPUP_EVIDENCE_LIMIT:
        return {"status": "over_cap"}
    classes = {"synthetic_popup": 0, "blank": 0, "initial": 0, "error_document": 0, "other": 0}
    for row in rows:
        if not isinstance(row, dict):
            return {"status": "malformed"}
        kind, opener = row.get("type"), row.get("openerId")
        if (
            type(kind) is not str
            or not 0 < len(kind) <= 64
            or "openerId" in row
            and (type(opener) is not str or not 0 < len(opener) <= 128)
        ):
            return {"status": "malformed"}
        # Never disclose unrelated targets, titles, IDs, or their URL classes.
        if kind != "page" or opener != identifier:
            continue
        value = row.get("url")
        if type(value) is not str or len(value) > 4096:
            return {"status": "malformed"}
        category = (
            "synthetic_popup"
            if value == POPUP_URL
            else "blank"
            if value == "about:blank"
            else "initial"
            if value in {"", ":"}
            else "error_document"
            if value == "chrome-error://chromewebdata/"
            else "other"
        )
        classes[category] += 1
    return {"status": "observed", "children": sum(classes.values()), "classes": classes}


async def popup_failure_message(cdp: CDPSession, **observations: Any) -> str:
    """Failure-only, one-second read-only snapshot; late events cannot make it pass."""
    counts = {
        "popup_count",
        "download_count",
        "popup_route_seen",
        "popup_abort_completed",
        "context_page_events",
        "context_pages",
    }
    flags = {"popup_closed", "download_cancelled"}
    if (
        set(observations) != counts | flags
        or any(type(observations[key]) is not bool for key in flags)
        or any(type(observations[key]) is not int or observations[key] < 0 for key in counts)
    ):
        safe: dict[str, object] = {"observations": "invalid"}
    else:
        safe = {key: min(observations[key], POPUP_EVIDENCE_LIMIT) for key in counts}
        safe.update({key: observations[key] for key in flags})
        safe["count_over_cap"] = any(observations[key] > POPUP_EVIDENCE_LIMIT for key in counts)

    async def snapshot() -> dict[str, object]:
        parent = await cdp.send("Target.getTargetInfo")
        verified = popup_target_summary(parent, {"targetInfos": []})
        if verified["status"] != "observed":
            return verified
        # Page-only query, no discovery subscription or browser/target mutation.
        targets = await cdp.send(
            "Target.getTargets", {"filter": [{"type": "page", "exclude": False}, {"exclude": True}]}
        )
        return popup_target_summary(parent, targets)

    try:
        evidence = await asyncio.wait_for(snapshot(), timeout=1)
    except TimeoutError:
        evidence = {"status": "timeout"}
    except Exception:
        evidence = {"status": "unavailable"}
    safe["target_snapshot"] = evidence
    return "Popup/download completion missing: " + json.dumps(safe, sort_keys=True)


async def main() -> None:
    if os.environ.get("EM_ISOLATION_DIAGNOSTIC") != "synthetic-browser-only":
        raise RuntimeError("Explicit browser diagnostic required")
    if os.geteuid() == 0 or any(
        os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
    ):
        raise RuntimeError("Nonroot, proxy-free browser required")
    # Browser profile/cache/crash diagnostics must stay in the existing bounded
    # disposable tmpfs; the image root and original user home remain read-only.
    for name, expected in (
        ("HOME", "/tmp/browser-home"),
        ("XDG_CONFIG_HOME", "/tmp/browser-config"),
        ("CHROME_CONFIG_HOME", "/tmp/browser-config"),
        ("XDG_CACHE_HOME", "/tmp/browser-cache"),
    ):
        if os.environ.get(name) != expected:
            raise RuntimeError("Bounded disposable browser data paths required")
        Path(expected).mkdir(mode=0o700, exist_ok=True)
    interfaces = sorted(p.name for p in Path("/sys/class/net").iterdir())
    if interfaces != ["lo"]:
        raise RuntimeError("Network-none namespace required")
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if int(status["CapEff"].strip(), 16) or status["NoNewPrivs"].strip() != "1":
        raise RuntimeError("Zero capabilities and no-new-privileges required")
    if status["Seccomp"].strip() != "2":
        raise RuntimeError("Approved seccomp boundary required")
    network: list[int] = []
    for family, target in (
        (socket.AF_INET, ("192.0.2.1", 443)),
        (socket.AF_INET6, ("2001:db8::1", 443)),
    ):
        with socket.socket(family, socket.SOCK_STREAM) as stream:
            stream.settimeout(0.2)
            result = stream.connect_ex(target)
            if result != errno.ENETUNREACH:
                raise RuntimeError("Actual namespace network denial not established")
            network.append(result)
    trace_stage("os_verified")
    channel = FixtureChannel(sys.stdin.buffer, sys.stdout)
    denied: list[str] = []
    allowed = 0
    acquisition_digest: str | None = None
    popup_count = 0
    download_count = 0
    popup_route_seen = 0
    popup_abort_completed = 0
    context_page_events = 0
    popup_closed = asyncio.Event()
    download_cancelled = asyncio.Event()

    async def route_request(route: Route) -> None:
        nonlocal allowed, acquisition_digest, popup_route_seen, popup_abort_completed
        incoming = route.request
        is_popup = incoming.url == POPUP_URL and incoming.resource_type == "document"
        if is_popup:
            popup_route_seen += 1
        reply = await channel.request(incoming.url, incoming.method, incoming.resource_type)
        if reply.get("status") != "ok":
            denied.append(incoming.resource_type)
            await route.abort("blockedbyclient")
            if is_popup:
                popup_abort_completed += 1
            return
        encoded = reply.get("body")
        if not isinstance(encoded, str) or reply.get("type") != "text/html":
            raise RuntimeError("Unexpected synthetic gateway payload")
        body = base64.b64decode(encoded, validate=True)
        if len(body) > 32768:
            raise RuntimeError("Gateway byte cap exceeded")
        if incoming.resource_type == "document" and incoming.url == URL:
            acquisition_digest = hashlib.sha256(body).hexdigest()
        allowed += 1
        # No source response headers, cookies, credentials or redirects are relayed.
        await route.fulfill(status=200, content_type="text/html", body=body)

    async def websocket(route: WebSocketRoute) -> None:
        await refuse_websocket(route, channel, denied)

    async with async_playwright() as playwright:
        # Explicit True: the API otherwise defaults to disabling Chromium sandbox.
        browser = await playwright.chromium.launch(
            channel="chromium",
            headless=True,
            chromium_sandbox=True,
            args=["--enable-automation"],
        )
        trace_stage("browser_launched")
        if browser.version != "153.0.8010.12":
            raise RuntimeError("Pinned Chromium version mismatch")
        context = await browser.new_context(
            service_workers="block",
            accept_downloads=False,
            extra_http_headers={"Authorization": "synthetic-diagnostic-only"},
        )
        await context.add_cookies([{"name": "diagnostic", "value": "synthetic-only", "url": URL}])
        page = await context.new_page()
        await page.goto("chrome://sandbox", wait_until="domcontentloaded")
        sandbox_text = await page.locator("#sandbox-status").inner_text()
        sandbox_evaluation = await page.locator("#evaluation").inner_text()
        own_sandbox = sandbox_status(sandbox_text, sandbox_evaluation)
        cdp = await context.new_cdp_session(page)
        command = await cdp.send("Browser.getBrowserCommandLine")
        arguments = command["arguments"]
        if any(x in arguments for x in ("--no-sandbox", "--disable-setuid-sandbox")):
            raise RuntimeError("Sandbox disabling flag present")
        trace_stage("sandbox_verified")
        try:
            # No interception yet: actual Chromium navigation must fail. The
            # independent sockets above establish observed kernel ENETUNREACH.
            # Reserved documentation address only; no offline emulation.
            await page.goto(NETWORK_DIAGNOSTIC_URL, timeout=5000)
        except Error as error:
            try:
                browser_network_error = classify_browser_network_error(str(error))
            except RuntimeError as invalid:
                raise invalid from error
        else:
            raise RuntimeError("Browser escaped network-none namespace")
        trace_stage("direct_network_rejected")
        trace_stage("route_registration_started")
        await context.route("**/*", route_request)
        trace_stage("route_registration_completed")
        trace_stage("websocket_registration_started")
        await context.route_web_socket("**/*", websocket)
        trace_stage("websocket_registration_completed")

        async def popup(child: object) -> None:
            nonlocal popup_count
            popup_count += 1
            # Close even an about:blank popup; no navigation/fallback grant.
            from playwright.async_api import Page

            if not isinstance(child, Page):
                raise RuntimeError("Unexpected popup")
            await child.close()
            popup_closed.set()

        async def download(item: object) -> None:
            nonlocal download_count
            download_count += 1
            from playwright.async_api import Download

            if not isinstance(item, Download):
                raise RuntimeError("Unexpected download")
            await item.cancel()
            download_cancelled.set()

        def context_page(_: object) -> None:
            nonlocal context_page_events
            context_page_events += 1

        # Registered after our initial page: counts only subsequently reported pages.
        context.on("page", context_page)
        page.on("popup", popup)
        page.on("download", download)
        trace_stage("routes_registered")
        await page.goto(URL, wait_until="domcontentloaded")
        trace_stage("fixture_loaded")
        trace_stage("click_start")
        await page.locator("#reveal").click()
        trace_stage("click_complete")
        trace_stage("boundary_wait_start")
        try:
            await boundary_readiness(
                page.wait_for_function("globalThis.boundaryReady === true", timeout=10000)
            )
        except (Error, TimeoutError):
            trace_stage("boundary_wait_failed")
            try:
                pending = await asyncio.wait_for(
                    page.evaluate("globalThis.boundaryPending"), timeout=1
                )
            except Exception:
                pending = None
            trace_stage(pending_task_evidence(pending))
            raise
        trace_stage("boundary_ready")
        # JavaScript's boundaryReady does not await Playwright's independent
        # popup/download callbacks. Require their actual close/cancel completion
        # within a fixed deadline, rather than a timing-dependent 300ms sleep.
        try:
            await wait_artifact_completion(popup_closed, download_cancelled)
        except TimeoutError as error:
            # Values are captured before the diagnostic await. Even if a late
            # callback completes meanwhile, this original timeout stays failed.
            raise RuntimeError(
                await popup_failure_message(
                    cdp,
                    popup_closed=popup_closed.is_set(),
                    download_cancelled=download_cancelled.is_set(),
                    popup_count=popup_count,
                    download_count=download_count,
                    popup_route_seen=popup_route_seen,
                    popup_abort_completed=popup_abort_completed,
                    context_page_events=context_page_events,
                    context_pages=len(context.pages),
                )
            ) from error
        if await page.locator("#marker").inner_text() != "synthetic marker revealed":
            raise RuntimeError("Approved synthetic browser interaction failed")
        state = await page.evaluate("globalThis.boundaryState")
        required = {
            "image",
            "stylesheet",
            "script",
            "iframe",
            "fetch",
            "xhr",
            "websocket",
        }
        # iframe resources are reported as document by Playwright.
        observed = set(denied)
        if not (required - {"iframe"}).issubset(observed) or "document" not in observed:
            raise RuntimeError("Required browser subresource denial not observed")
        registrations = await page.evaluate(
            "navigator.serviceWorker.getRegistrations().then(r=>r.length)"
        )
        if registrations != 0 or not state["worker_blocked"]:
            raise RuntimeError("Service worker registration was not blocked")
        if not state["fetch_denied"] or not state["post_denied"]:
            raise RuntimeError("Worker/method/fetch refusal missing")
        if not state["allowed_fetch"] or not popup_count or not download_count:
            raise RuntimeError(
                "Positive gateway/popup/download evidence missing: "
                + json.dumps(
                    {
                        "allowed_fetch": state.get("allowed_fetch") is True,
                        "popup_count": popup_count,
                        "download_count": download_count,
                        "popup_closed": popup_closed.is_set(),
                        "download_cancelled": download_cancelled.is_set(),
                    }
                )
            )
        if context.service_workers or len(context.pages) != 1:
            raise RuntimeError("Service worker or popup remained active")
        # Server-owned, fixed ordinary public hover only. Never click mailto,
        # submit forms or evaluate instructions from source text.
        await page.locator("#contact-reveal").hover(timeout=2000)
        await page.locator("#contact-tooltip").wait_for(state="visible", timeout=2000)
        if acquisition_digest is None:
            raise RuntimeError("Acquired tooltip document digest missing")
        rendered = await asyncio.wait_for(page.content(), timeout=2)
        article = parse_article(
            Settings(environment="test", fixture_mode=True),
            URL,
            rendered.encode("utf-8"),
            browser_dom=True,
            acquisition_digest=acquisition_digest,
        )
        if (
            article.status != "observed"
            or len(article.candidates) != 1
            or article.candidates[0].raw_address != "elena.park@example.org"
            or article.candidates[0].evidence.kind != "browser_dom"
        ):
            raise RuntimeError("Actual tooltip reveal did not yield scoped observed evidence")
        trace_stage("checks_complete")
        await context.close()
        await browser.close()
        trace_stage("browser_closed")
    print(
        json.dumps(
            {
                "kind": "result",
                "diagnostic": "synthetic-browser-boundary",
                "sandbox": own_sandbox,
                "sandbox_table": sandbox_text,
                "sandbox_evaluation": sandbox_evaluation,
                "chromium_version": "153.0.8010.12",
                "network_errno": network,
                "browser_network_error": browser_network_error,
                "interfaces": interfaces,
                "requests": channel.requests,
                "allowed": allowed,
                "denied_resources": sorted(observed),
                "popup_closed": popup_count,
                "downloads_cancelled": download_count,
                "service_workers": 0,
                "service_worker_registrations": registrations,
                "contact_extraction": True,
                "article_observation": article.model_dump(),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())

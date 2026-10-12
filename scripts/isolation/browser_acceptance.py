"""Approved synthetic-only guest. Network-none OS boundary is mandatory."""

import asyncio
import base64
import errno
import json
import os
import socket
import sys
from pathlib import Path
from typing import BinaryIO, TextIO

from playwright.async_api import Error, Route, WebSocketRoute, async_playwright

URL = "https://synthetic.publisher.example/tooltip.html"
NETWORK_DIAGNOSTIC_URL = "http://192.0.2.1:443/"


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
    popup_count = 0
    download_count = 0

    async def route_request(route: Route) -> None:
        nonlocal allowed
        incoming = route.request
        reply = await channel.request(incoming.url, incoming.method, incoming.resource_type)
        if reply.get("status") != "ok":
            denied.append(incoming.resource_type)
            await route.abort("blockedbyclient")
            return
        encoded = reply.get("body")
        if not isinstance(encoded, str) or reply.get("type") != "text/html":
            raise RuntimeError("Unexpected synthetic gateway payload")
        body = base64.b64decode(encoded, validate=True)
        if len(body) > 32768:
            raise RuntimeError("Gateway byte cap exceeded")
        allowed += 1
        # No source response headers, cookies, credentials or redirects are relayed.
        await route.fulfill(status=200, content_type="text/html", body=body)

    async def websocket(route: WebSocketRoute) -> None:
        await refuse_websocket(route, channel, denied)

    async with async_playwright() as playwright:
        # Explicit True: the API otherwise defaults to disabling Chromium sandbox.
        browser = await playwright.chromium.launch(
            channel="chromium", headless=True, chromium_sandbox=True, args=["--enable-automation"]
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
        await context.route("**/*", route_request)
        await context.route_web_socket("**/*", websocket)

        async def popup(child: object) -> None:
            nonlocal popup_count
            popup_count += 1
            # Close even an about:blank popup; no navigation/fallback grant.
            from playwright.async_api import Page

            if not isinstance(child, Page):
                raise RuntimeError("Unexpected popup")
            await child.close()

        async def download(item: object) -> None:
            nonlocal download_count
            download_count += 1
            from playwright.async_api import Download

            if not isinstance(item, Download):
                raise RuntimeError("Unexpected download")
            await item.cancel()

        page.on("popup", popup)
        page.on("download", download)
        trace_stage("routes_registered")
        await page.goto(URL, wait_until="domcontentloaded")
        trace_stage("fixture_loaded")
        trace_stage("click_start")
        await page.locator("#reveal").click()
        trace_stage("click_complete")
        await page.wait_for_function("globalThis.boundaryReady === true", timeout=10000)
        trace_stage("boundary_ready")
        await page.wait_for_timeout(300)
        if await page.locator("#marker").inner_text() != "synthetic marker revealed":
            raise RuntimeError("Approved synthetic browser interaction failed")
        state = await page.evaluate("globalThis.boundaryState")
        required = {"image", "stylesheet", "script", "iframe", "fetch", "xhr", "websocket"}
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
            raise RuntimeError("Positive gateway/popup/download evidence missing")
        if context.service_workers or len(context.pages) != 1:
            raise RuntimeError("Service worker or popup remained active")
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
                "contact_extraction": False,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())

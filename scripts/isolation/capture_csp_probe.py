"""Synthetic Chromium negative control for the production app's style CSP."""

import asyncio

from browser_acceptance import sandbox_status
from operator_capture import FINISH, INSTALL, SHAPE, style_for
from playwright.async_api import Route, async_playwright
from test_operator_capture_pixels import ORIGIN, fixture, require_existing_isolation

CSS_URL = ORIGIN + "synthetic.css"
POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'"
)


async def exercise() -> None:
    original = fixture("plan")
    prefix, remainder = original.split("<style>", 1)
    css, suffix = remainder.split("</style>", 1)
    meta = '<meta http-equiv="Content-Security-Policy" content="' + POLICY + '">'
    current = {"policy": False}

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel="chromium", headless=True, chromium_sandbox=True, args=["--enable-automation"]
        )
        try:
            if browser.version != "153.0.8010.12":
                raise RuntimeError("Synthetic CSP control refused")
            context = await browser.new_context(service_workers="block", accept_downloads=False)
            page = await context.new_page()
            await page.goto("chrome://sandbox", wait_until="domcontentloaded")
            sandbox_status(
                await page.locator("#sandbox-status").inner_text(),
                await page.locator("#evaluation").inner_text(),
            )
            command = await (await context.new_cdp_session(page)).send(
                "Browser.getBrowserCommandLine"
            )
            if "--no-sandbox" in command["arguments"]:
                raise RuntimeError("Synthetic CSP control refused")

            async def route_request(route: Route) -> None:
                if route.request.method == "GET" and route.request.url == ORIGIN:
                    html = (
                        prefix
                        + (meta if current["policy"] else "")
                        + '<link rel="stylesheet" href="/synthetic.css">'
                        + suffix
                    )
                    await route.fulfill(status=200, content_type="text/html", body=html)
                elif route.request.method == "GET" and route.request.url == CSS_URL:
                    await route.fulfill(status=200, content_type="text/css", body=css)
                else:
                    await route.abort()

            await page.route("**/*", route_request)
            for policy in (False, True):
                current["policy"] = policy
                await page.goto(ORIGIN, wait_until="load")
                await page.evaluate("""() => {
                  window.__emStyleViolation = false;
                  document.addEventListener('securitypolicyviolation', event => {
                    if (['style-src', 'style-src-elem'].includes(event.violatedDirective))
                      window.__emStyleViolation = true;
                  });
                }""")
                handle = await page.locator('dl[aria-label="Plan summary"]').element_handle()
                if handle is None:
                    raise RuntimeError("Synthetic CSP control refused")
                style = style_for("plan")
                if await handle.evaluate(SHAPE, {"name": "plan", "style": style}) is not True:
                    raise RuntimeError("Synthetic CSP control refused")
                try:
                    installed = await handle.evaluate(INSTALL, style)
                finally:
                    finished = await handle.evaluate(FINISH)
                if type(installed) is not bool or installed is policy:
                    raise RuntimeError("Synthetic CSP control refused")
                if not policy and finished != "ok":
                    raise RuntimeError("Synthetic CSP control refused")
                if policy:
                    await page.wait_for_function("window.__emStyleViolation === true", timeout=2000)
            await context.close()
        finally:
            await browser.close()


def run() -> None:
    require_existing_isolation()
    try:
        asyncio.run(asyncio.wait_for(exercise(), timeout=180))
    except BaseException:  # noqa: BLE001 - never emit guest data or tracebacks
        raise RuntimeError("Synthetic CSP control refused") from None

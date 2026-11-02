"""No-output synthetic control for evidence-dialog focus during capture."""

import asyncio
import contextlib
import io

from browser_acceptance import sandbox_status
from operator_capture import capture
from playwright.async_api import Route, async_playwright
from test_operator_capture_pixels import ORIGIN, fixture, require_existing_isolation


async def exercise() -> None:
    html = fixture("evidence-quality").replace(
        "<dialog open aria-labelledby='evidence-title'>",
        "<dialog open aria-labelledby='evidence-title'>"
        "<button class='close' autofocus>Close evidence</button>",
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel="chromium", headless=True, chromium_sandbox=True, args=["--enable-automation"]
        )
        try:
            if browser.version != "153.0.8010.12":
                raise RuntimeError("Synthetic focus control refused")
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
                raise RuntimeError("Synthetic focus control refused")

            async def route_request(route: Route) -> None:
                if route.request.method == "GET" and route.request.url == ORIGIN:
                    await route.fulfill(status=200, content_type="text/html", body=html)
                elif (
                    route.request.method == "GET" and route.request.url == ORIGIN + "synthetic.css"
                ):
                    await route.fulfill(
                        status=200, content_type="text/css", body="body{font:16px sans-serif}"
                    )
                else:
                    await route.abort()

            await page.route("**/*", route_request)
            await page.goto(ORIGIN, wait_until="load")
            await page.locator("dialog").evaluate(
                "dialog => { dialog.removeAttribute('open'); dialog.showModal(); }"
            )
            close = page.locator("dialog[open] > button.close")
            await close.focus()
            focused = await page.evaluate("""() => document.activeElement ===
              document.querySelector('dialog[open] > button.close')""")
            if focused is not True:
                raise RuntimeError("Synthetic focus control refused")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                try:
                    await capture(page, "evidence-quality")
                except ValueError as error:
                    if error.args != ("capture_state_focus",):
                        raise RuntimeError("Synthetic focus control refused") from None
                else:
                    raise RuntimeError("Synthetic focus control refused")
            if output.getvalue():
                raise RuntimeError("Synthetic focus control refused")
            await context.close()
        finally:
            await browser.close()


def run() -> None:
    require_existing_isolation()
    try:
        asyncio.run(asyncio.wait_for(exercise(), timeout=180))
    except BaseException:  # noqa: BLE001 - no guest data or traceback is emitted
        raise RuntimeError("Synthetic focus control refused") from None

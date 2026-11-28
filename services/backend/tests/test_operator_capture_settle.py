"""Capture settling regression: the post-action refresh race, in local synthetic Chromium.

Every successful web `act` ends with `refresh()`, which re-requests the organization
detail; while it is in flight the workspace heading is replaced by a loading status.
A capture taken in that window is refused. These tests reproduce the race on a fixed
synthetic page and prove the harness waits for a settled page without loosening any
capture check: a page that never settles is still refused by `capture()` itself.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import operator_ui_acceptance as guest
import pytest
from operator_capture import capture
from playwright.async_api import Page, Route, async_playwright

ORIGIN = "https://app.example.test/"
LABELS = (
    "Source identity",
    "Planned start URL",
    "Original query",
    "Effective query",
    "Requested article limit",
    "Effective article cap",
    "Maximum result pages",
    "Author selection",
    "Browser work",
    "Authored PDF fixtures",
    "Policy version at planning",
    "Source-reported total at planning",
    "Article URLs listed at planning",
)
ROWS = "".join(
    f"<div><dt>{label}</dt><dd>synthetic value {index}</dd></div>"
    for index, label in enumerate(LABELS)
)
PAGE = (
    "<!doctype html><html><head></head><body>"
    "<main id='main' class='workspace' aria-busy='false'>"
    "<div class='workspace-heading'><div><h2>Synthetic tenant 0</h2><h3>New extraction</h3></div>"
    "</div><section aria-label='Server source plan'>"
    f"<dl aria-label='Plan summary'>{ROWS}</dl></section></main></body></html>"
)
# The same transition the web app performs after `act`: busy, heading replaced by the
# loading status, then the refetched heading returns (or, for `never`, does not).
REFRESH = """restoreAfterMs => {
  const main = document.querySelector('main#main');
  const holder = document.querySelector('.workspace-heading > div');
  const heading = holder.querySelector('h2');
  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  status.textContent = 'Loading current organization data\\u2026';
  main.setAttribute('aria-busy', 'true');
  holder.replaceChild(status, heading);
  setTimeout(() => main.setAttribute('aria-busy', 'false'), 50);
  if (restoreAfterMs >= 0) setTimeout(() => holder.replaceChild(heading, status), restoreAfterMs);
}"""
CHURN = """() => {
  const holder = document.querySelector('.workspace-heading h3');
  window.__churn = setInterval(() => holder.setAttribute('data-tick', String(Date.now())), 100);
}"""


@asynccontextmanager
async def synthetic_page() -> AsyncIterator[Page]:
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception as error:  # noqa: BLE001 - no local Chromium is a skip, not a pass
            pytest.skip(f"Local Chromium unavailable: {type(error).__name__}")
        try:
            context = await browser.new_context(service_workers="block", accept_downloads=False)
            page = await context.new_page()

            async def route_request(route: Route) -> None:
                if route.request.url == ORIGIN and route.request.method == "GET":
                    await route.fulfill(status=200, content_type="text/html", body=PAGE)
                else:
                    await route.abort()

            await page.route("**/*", route_request)
            await page.goto(ORIGIN, wait_until="load")
            yield page
        finally:
            await browser.close()


def run(scenario: Callable[[Page], Awaitable[Any]]) -> Any:
    async def main() -> Any:
        async with synthetic_page() as page:
            return await scenario(page)

    return asyncio.run(main())


def frames(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


def test_capture_during_post_action_refresh_is_refused_without_settling(capsys: Any) -> None:
    async def scenario(page: Page) -> None:
        await page.evaluate(REFRESH, 700)
        with pytest.raises(ValueError, match="^capture_session_refused$"):
            await capture(page, "plan")

    run(scenario)
    assert frames(capsys.readouterr().out) == []


def test_harness_waits_for_refreshed_heading_then_captures(capsys: Any) -> None:
    async def scenario(page: Page) -> None:
        await page.evaluate(REFRESH, 700)
        await guest.capture_business(page, "plan")

    run(scenario)
    emitted = frames(capsys.readouterr().out)
    assert emitted and all(frame["kind"] == "capture" for frame in emitted)
    assert {frame["name"] for frame in emitted} == {"plan"}


def test_unsettled_page_is_still_refused_by_capture_checks(
    capsys: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guest, "CAPTURE_SETTLE_TIMEOUT_MS", 600)

    async def scenario(page: Page) -> bool:
        await page.evaluate(REFRESH, -1)
        with pytest.raises(ValueError, match="^capture_session_refused$"):
            await guest.capture_business(page, "plan")
        return await guest.settle_for_capture(page)

    assert run(scenario) is False
    assert frames(capsys.readouterr().out) == []


def test_settle_is_bounded_under_continuous_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guest, "CAPTURE_SETTLE_TIMEOUT_MS", 800)

    async def scenario(page: Page) -> tuple[bool, float]:
        await page.evaluate(CHURN)
        loop = asyncio.get_running_loop()
        started = loop.time()
        settled = await guest.settle_for_capture(page)
        return settled, loop.time() - started

    settled, elapsed = run(scenario)
    assert settled is False
    assert elapsed < 5


def test_settled_page_returns_promptly_and_changes_nothing() -> None:
    async def scenario(page: Page) -> tuple[bool, str, str]:
        before = await page.evaluate("() => document.documentElement.outerHTML")
        focused = await page.evaluate("() => document.activeElement.tagName")
        settled = await guest.settle_for_capture(page)
        after = await page.evaluate("() => document.documentElement.outerHTML")
        assert after == before
        return settled, focused, await page.evaluate("() => document.activeElement.tagName")

    settled, focused_before, focused_after = run(scenario)
    assert settled is True and focused_before == focused_after


def test_settle_timeout_on_host_side_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class HungPage:
        async def evaluate(self, *args: Any) -> bool:
            await asyncio.sleep(3600)
            return True

    monkeypatch.setattr(guest, "CAPTURE_SETTLE_TIMEOUT_MS", 0)
    monkeypatch.setattr(guest, "CAPTURE_SETTLE_HOST_MARGIN_S", 0.05)
    assert asyncio.run(guest.settle_for_capture(HungPage())) is False  # type: ignore[arg-type]


def test_capture_business_always_runs_fixed_capture_after_settle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def settle(page: Any) -> bool:
        calls.append("settle")
        return False

    async def fixed(page: Any, name: str) -> None:
        calls.append("capture:" + name)

    monkeypatch.setattr(guest, "settle_for_capture", settle)
    monkeypatch.setattr(guest, "capture_fixed_crop", fixed)
    asyncio.run(guest.capture_business(object(), "export"))  # type: ignore[arg-type]
    assert calls == ["settle", "capture:export"]

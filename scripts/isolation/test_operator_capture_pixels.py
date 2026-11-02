"""Standalone real-Chromium regression; requires the existing isolated guest profile.

This is synthetic browser evidence, not the installed-app acceptance journey.
It never emits raw screenshot bytes or creates a server, identity or credential.
"""

import asyncio
import base64
import contextlib
import errno
import io
import json
import os
import socket
import struct
import zlib
from pathlib import Path
from typing import Any, cast

from browser_acceptance import sandbox_status
from operator_capture import (
    GEOMETRY,
    TARGETS,
    capture,
    redaction_rectangles,
    style_for,
    validate_png,
)
from playwright.async_api import Page, Route, async_playwright

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
ORIGIN = "https://app.example.test/"


def require_existing_isolation() -> None:
    if os.getuid() != 1000 or any(
        os.environ.get(key) for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
    ):
        raise RuntimeError("Isolated proxy-free nonroot browser required")
    if any(os.environ.get(key) for key in ("DEBUG", "DEBUG_FILE", "PWDEBUG")):
        raise RuntimeError("Browser debug logging must be disabled")
    if sorted(os.listdir("/sys/class/net")) != ["lo"]:
        raise RuntimeError("Network-none browser required")
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if (
        int(status["CapEff"].strip(), 16)
        or status["NoNewPrivs"].strip() != "1"
        or status["Seccomp"].strip() != "2"
    ):
        raise RuntimeError("Original OS isolation controls required")
    for name, value in {
        "HOME": "/tmp/browser-home",
        "XDG_CONFIG_HOME": "/tmp/browser-config",
        "CHROME_CONFIG_HOME": "/tmp/browser-config",
        "XDG_CACHE_HOME": "/tmp/browser-cache",
    }.items():
        if os.environ.get(name) != value:
            raise RuntimeError("Bounded browser paths required")
        Path(value).mkdir(mode=0o700, exist_ok=True)
    for family, target in (
        (socket.AF_INET, ("192.0.2.1", 443)),
        (socket.AF_INET6, ("2001:db8::1", 443)),
    ):
        with socket.socket(family, socket.SOCK_STREAM) as stream:
            stream.settimeout(0.2)
            if stream.connect_ex(target) != errno.ENETUNREACH:
                raise RuntimeError("Actual OS network denial missing")


def fixture(name: str) -> str:
    rows = "".join(
        f"<div><dt>{label}</dt><dd>synthetic sentinel {index}</dd></div>"
        for index, label in enumerate(LABELS)
    )
    quality = (
        "<section aria-label='Article observation quality'><h4>Article observation quality</h4>"
        "<p>synthetic sentinel evidence</p>"
        "<p>Parser-specific reasons are not recorded for this route.</p>"
        "<p>Missing affiliations remain unobserved, not confirmed absent. Accepting or correcting "
        "an author-email association does not resolve affiliation uncertainty or change "
        "the retained "
        "parser outcome.</p></section>"
    )
    if name == "plan":
        target = f"<dl aria-label='Plan summary'>{rows}</dl>"
    elif name == "evidence-quality":
        target = (
            "<dialog open aria-labelledby='evidence-title'><h2 id='evidence-title'>Evidence</h2>"
            f"{quality}</dialog>"
        )
    elif name == "export":
        target = (
            "<section aria-label='Current export preview'><h4>Current eligible preview</h4>"
            "<p>synthetic sentinel selection</p><p>synthetic sentinel count</p>"
            "<ul><li>synthetic sentinel reason</li></ul><p>synthetic sentinel detail</p>"
            "<button>Create asynchronous export</button></section>"
        )
    elif name in ("suppression", "deletion"):
        title = (
            "Suppress observed contact"
            if name == "suppression"
            else "Stage job deletion"
        )
        confirm = (
            "Confirm suppress observed contact"
            if name == "suppression"
            else "Confirm stage job deletion"
        )
        target = (
            f"<dialog open aria-labelledby='confirm-title'><h2 id='confirm-title'>{title}</h2>"
            "<p>synthetic sentinel organization</p><p>synthetic sentinel detail</p>"
            f"<div><button>Keep unchanged</button><button>{confirm}</button></div></dialog>"
        )
    else:
        raise ValueError("Fixed synthetic crop required")
    return (
        "<!doctype html><html><head><style>"
        "body{font:16px sans-serif} dl{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}"
        "dd{margin:0;overflow-wrap:anywhere}"
        "</style></head><body><div class='workspace-heading'><h2>Synthetic tenant 0</h2></div>"
        f"{target}</body></html>"
    )


EXPOSE = """spec => {
  const sheets = Array.from(document.querySelectorAll('style'))
    .filter(s => s.textContent === spec.style);
  if (sheets.length !== 1) return false;
  const sheet = sheets[0].sheet;
  window.__syntheticCaptureRules = sheet.cssRules.length;
  for (const part of spec.masks) sheet.insertRule(
    ':root ' + spec.selector + ' ' + part + '{visibility:visible!important}',sheet.cssRules.length
  );
  return spec.masks.every(part => Array.from(document.querySelectorAll(spec.selector + ' ' + part))
    .every(e => getComputedStyle(e).visibility === 'visible'));
}"""

CONTROL = """spec => {
  const sheets = Array.from(document.querySelectorAll('style'))
    .filter(s => s.textContent === spec.style);
  if (sheets.length !== 1) return false;
  const sheet = sheets[0].sheet;
  for (const part of spec.masks) {
    const target = ':root ' + spec.selector + ' ' + part;
    sheet.insertRule(target + ',' + target + ' *{color:transparent!important;'
      + '-webkit-text-fill-color:transparent!important}',sheet.cssRules.length);
  }
  return true;
}"""

RESTORE = """spec => {
  const sheets = Array.from(document.querySelectorAll('style'))
    .filter(s => s.textContent === spec.style);
  const initial = window.__syntheticCaptureRules;
  if (sheets.length !== 1 || !Number.isInteger(initial)) return false;
  const sheet = sheets[0].sheet;
  if (sheet.cssRules.length !== initial + spec.masks.length * 2) return false;
  while (sheet.cssRules.length > initial) sheet.deleteRule(sheet.cssRules.length - 1);
  delete window.__syntheticCaptureRules;
  return true;
}"""

PIXEL_ORACLE = """async images => {
  const decoded = [];
  for (const encoded of images) {
    const bytes = Uint8Array.from(atob(encoded), c => c.charCodeAt(0));
    const bitmap = await createImageBitmap(new Blob([bytes], {type:'image/png'}));
    const canvas = document.createElement('canvas');
    canvas.width = bitmap.width; canvas.height = bitmap.height;
    const context = canvas.getContext('2d', {willReadFrequently:true});
    if (!context) return null;
    context.drawImage(bitmap, 0, 0);
    decoded.push({width:bitmap.width,height:bitmap.height,
      pixels:context.getImageData(0,0,bitmap.width,bitmap.height).data});
    bitmap.close();
  }
  if (decoded.length !== 3 || decoded.some(x => x.width !== decoded[0].width ||
      x.height !== decoded[0].height)) return null;
  const [exposed, control, sanitized] = decoded.map(x => x.pixels);
  let changed = 0, leaked = 0;
  for (let i=0; i<exposed.length; i+=4) {
    if (exposed[i] !== control[i] || exposed[i+1] !== control[i+1] ||
        exposed[i+2] !== control[i+2] || exposed[i+3] !== control[i+3]) {
      changed += 1;
      if (sanitized[i] !== 0 || sanitized[i+1] !== 0 || sanitized[i+2] !== 0 ||
          sanitized[i+3] !== 255) leaked += 1;
    }
  }
  return {changed, leaked};
}"""


class CaptureHandle:
    def __init__(self, handle: Any, page: Page, name: str) -> None:
        self.handle, self.page, self.name = handle, page, name
        self.geometry: list[Any] = []
        self.exposure_verified = False
        self.exposed_image: bytes | None = None
        self.control_image: bytes | None = None

    async def evaluate(self, expression: str, *arguments: Any) -> Any:
        result = await self.handle.evaluate(expression, *arguments)
        if expression == GEOMETRY:
            self.geometry.append(result)
        return result

    async def screenshot(self, **options: Any) -> bytes:
        selector, masks = TARGETS[self.name]
        spec = {
            "style": style_for(self.name),
            "selector": selector,
            "masks": masks.split(", "),
        }
        exposed = await self.page.evaluate(EXPOSE, spec) is True
        if not exposed:
            raise RuntimeError("Synthetic exposure was not established")
        try:
            image = await self.handle.screenshot(**options)
            if await self.page.evaluate(CONTROL, spec) is not True:
                raise RuntimeError("Synthetic control was not established")
            self.control_image = await self.handle.screenshot(**options)
            validate_png(image)
            validate_png(self.control_image)
            self.exposed_image = image
        finally:
            self.exposure_verified = await self.page.evaluate(RESTORE, spec) is True
        if not self.exposure_verified:
            raise RuntimeError("Synthetic exposure was not established and restored")
        return cast(bytes, image)


class CaptureLocator:
    def __init__(self, locator: Any, page: Page, name: str) -> None:
        self.locator, self.page, self.name = locator, page, name
        self.handle: CaptureHandle | None = None

    async def count(self) -> int:
        return cast(int, await self.locator.count())

    async def element_handle(self) -> CaptureHandle:
        self.handle = CaptureHandle(
            await self.locator.element_handle(), self.page, self.name
        )
        return self.handle


class CapturePage:
    def __init__(self, page: Page, name: str) -> None:
        self.page, self.name = page, name
        self.capture_locator: CaptureLocator | None = None

    @property
    def url(self) -> str:
        return self.page.url

    async def evaluate(self, expression: str) -> Any:
        return await self.page.evaluate(expression)

    def locator(self, selector: str) -> CaptureLocator:
        self.capture_locator = CaptureLocator(
            self.page.locator(selector), self.page, self.name
        )
        return self.capture_locator


def assert_black_rectangles(
    image: bytes, boxes: list[tuple[int, int, int, int]]
) -> None:
    validate_png(image)
    width, height, _, color, _, _, _ = struct.unpack(">IIBBBBB", image[16:29])
    channels = 3 if color == 2 else 4
    offset, body = 8, bytearray()
    while offset < len(image):
        length = struct.unpack(">I", image[offset : offset + 4])[0]
        if image[offset + 4 : offset + 8] == b"IDAT":
            body.extend(image[offset + 8 : offset + 8 + length])
        offset += 12 + length
    raw = zlib.decompress(bytes(body))
    stride = width * channels
    black = bytes((0, 0, 0) if channels == 3 else (0, 0, 0, 255))
    for x0, y0, x1, y1 in boxes:
        for y in range(y0, y1):
            if raw[y * (stride + 1)] != 0:
                raise RuntimeError("Synthetic PNG row format refused")
            row = raw[y * (stride + 1) + 1 : (y + 1) * (stride + 1)]
            if row[x0 * channels : x1 * channels] != black * (x1 - x0):
                raise RuntimeError("Synthetic pixel redaction refused")
    if not (0 < width <= 1800 and 0 < height <= 1800):
        raise RuntimeError("Synthetic PNG dimensions refused")


async def exercise() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel="chromium",
            headless=True,
            chromium_sandbox=True,
            args=["--enable-automation"],
        )
        try:
            if browser.version != "153.0.8010.12":
                raise RuntimeError("Pinned Chromium required")
            context = await browser.new_context(
                service_workers="block", accept_downloads=False
            )
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
                raise RuntimeError("Chromium sandbox must remain enabled")

            current = {"name": "plan"}

            async def route_request(route: Route) -> None:
                if route.request.url == ORIGIN and route.request.method == "GET":
                    await route.fulfill(
                        status=200,
                        content_type="text/html",
                        body=fixture(current["name"]),
                    )
                else:
                    await route.abort()

            await page.route("**/*", route_request)
            for name in TARGETS:
                current["name"] = name
                await page.goto(ORIGIN, wait_until="domcontentloaded")
                wrapped = CapturePage(page, name)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    await capture(cast(Page, wrapped), name)
                handle = (
                    wrapped.capture_locator.handle if wrapped.capture_locator else None
                )
                if (
                    handle is None
                    or not handle.exposure_verified
                    or len(handle.geometry) != 2
                    or handle.exposed_image is None
                    or handle.control_image is None
                ):
                    raise RuntimeError("Synthetic exposure evidence missing")
                frames = [json.loads(line) for line in output.getvalue().splitlines()]
                if not frames or any(
                    set(frame) != {"kind", "name", "part", "parts", "data"}
                    or frame["kind"] != "capture"
                    or frame["name"] != name
                    or frame["part"] != index
                    or frame["parts"] != len(frames)
                    for index, frame in enumerate(frames)
                ):
                    raise RuntimeError("Synthetic capture frame refused")
                image = base64.b64decode(
                    "".join(frame["data"] for frame in frames), validate=True
                )
                width, height = struct.unpack(">II", image[16:24])
                boxes = redaction_rectangles(
                    handle.geometry[0], handle.geometry[1], width, height, name
                )
                assert_black_rectangles(image, boxes)
                encoded = [
                    base64.b64encode(item).decode("ascii")
                    for item in (handle.exposed_image, handle.control_image, image)
                ]
                try:
                    oracle = await page.evaluate(PIXEL_ORACLE, encoded)
                except Exception:  # noqa: BLE001 - suppress browser data in tracebacks
                    raise RuntimeError(
                        "Synthetic independent pixel oracle unavailable"
                    ) from None
                if (
                    not isinstance(oracle, dict)
                    or set(oracle) != {"changed", "leaked"}
                    or type(oracle["changed"]) is not int
                    or oracle["changed"] <= 0
                    or oracle["leaked"] != 0
                ):
                    raise RuntimeError("Synthetic independent pixel oracle refused")
                handle.exposed_image = None
                handle.control_image = None
            await context.close()
        finally:
            await browser.close()


def test_actual_sandboxed_chromium_redacts_temporarily_exposed_synthetic_values() -> (
    None
):
    require_existing_isolation()
    # The oracle temporarily handles unredacted synthetic images. Never include
    # its internal frames in a pytest --showlocals report on failure.
    try:
        asyncio.run(asyncio.wait_for(exercise(), timeout=180))
    except BaseException as exc:  # noqa: BLE001 - prevent pixels in any failure traceback
        category = (
            "interrupt"
            if isinstance(exc, KeyboardInterrupt)
            else "exit"
            if isinstance(exc, SystemExit)
            else "cancelled"
            if isinstance(exc, asyncio.CancelledError)
            else "error"
        )
    else:
        return
    if category == "interrupt":
        raise KeyboardInterrupt() from None
    if category == "exit":
        raise SystemExit(1) from None
    if category == "cancelled":
        raise asyncio.CancelledError() from None
    raise RuntimeError("Synthetic Chromium regression refused") from None

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
    FINISH,
    GEOMETRY,
    INSTALL,
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
            "<dialog open aria-labelledby='evidence-title'>"
            "<button class='close' autofocus>Close evidence</button>"
            "<h2 id='evidence-title'>Evidence and review</h2>"
            f"{quality}</dialog>"
        )
    elif name == "export":
        target = (
            "<form><button type='submit'>Preview eligible export counts</button></form>"
            "<section aria-label='Current export preview'><h4>Current eligible preview</h4>"
            "<p>synthetic sentinel selection</p><p>synthetic sentinel count</p>"
            "<ul><li>synthetic sentinel reason</li></ul><p>synthetic sentinel detail</p>"
            "<button>Create asynchronous export</button></section>"
        )
    elif name in ("suppression", "deletion"):
        title = "Suppress observed contact" if name == "suppression" else "Stage job deletion"
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
    policy = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'"
    )
    return (
        '<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="'
        + policy
        + '"><link rel="stylesheet" href="/synthetic.css"></head>'
        + "<body><div class='workspace-heading'><h2>Synthetic tenant 0</h2></div>"
        + target
        + "</body></html>"
    )


EXPOSE = """spec => {
  const root = document.querySelector(spec.selector);
  const sheet = root && root.__emCaptureOwnedStyle;
  if (!sheet || document.adoptedStyleSheets.length !== 1 ||
      document.adoptedStyleSheets[0] !== sheet) return false;
  window.__syntheticCaptureRules = sheet.cssRules.length;
  for (const part of spec.masks) sheet.insertRule(
    ':root ' + spec.selector + ' ' + part + '{visibility:visible!important}',sheet.cssRules.length
  );
  return spec.masks.every(part => Array.from(document.querySelectorAll(spec.selector + ' ' + part))
    .every(e => getComputedStyle(e).visibility === 'visible'));
}"""

CONTROL = """spec => {
  const root = document.querySelector(spec.selector);
  const sheet = root && root.__emCaptureOwnedStyle;
  if (!sheet || document.adoptedStyleSheets.length !== 1 ||
      document.adoptedStyleSheets[0] !== sheet) return false;
  for (const part of spec.masks) {
    const target = ':root ' + spec.selector + ' ' + part;
    sheet.insertRule(target + ',' + target + ' *{color:transparent!important;'
      + '-webkit-text-fill-color:transparent!important}',sheet.cssRules.length);
  }
  return true;
}"""

RESTORE = """spec => {
  const root = document.querySelector(spec.selector);
  const sheet = root && root.__emCaptureOwnedStyle;
  const initial = window.__syntheticCaptureRules;
  if (!sheet || document.adoptedStyleSheets.length !== 1 ||
      document.adoptedStyleSheets[0] !== sheet || !Number.isInteger(initial)) return false;
  if (sheet.cssRules.length !== initial + spec.masks.length * 2) return false;
  while (sheet.cssRules.length > initial) sheet.deleteRule(sheet.cssRules.length - 1);
  delete window.__syntheticCaptureRules;
  return true;
}"""

FOCUS_EXPOSE = """() => {
  const root = document.querySelector('section[aria-label="Article observation quality"]');
  const sheet = root && root.__emCaptureOwnedStyle;
  const close = document.querySelector('dialog[open] > button.close:first-child');
  if (!sheet || document.adoptedStyleSheets.length !== 1 ||
      document.adoptedStyleSheets[0] !== sheet || document.activeElement !== close) return false;
  window.__syntheticFocusRules = sheet.cssRules.length;
  sheet.insertRule(':root dialog[open][aria-labelledby="evidence-title"] > '
    + 'button.close:first-child:focus{opacity:1!important}', sheet.cssRules.length);
  return getComputedStyle(close).opacity === '1';
}"""

FOCUS_RESTORE = """() => {
  const root = document.querySelector('section[aria-label="Article observation quality"]');
  const sheet = root && root.__emCaptureOwnedStyle;
  const close = document.querySelector('dialog[open] > button.close:first-child');
  const initial = window.__syntheticFocusRules;
  if (!sheet || !Number.isInteger(initial) || sheet.cssRules.length !== initial + 1) return false;
  sheet.deleteRule(initial);
  delete window.__syntheticFocusRules;
  return document.activeElement === close && getComputedStyle(close).opacity === '0';
}"""

EXPORT_FOCUS_EXPOSE = """() => {
  const root = document.querySelector('section[aria-label="Current export preview"]');
  const sheet = root && root.__emCaptureOwnedStyle;
  const button = root?.previousElementSibling?.lastElementChild;
  if (!sheet || document.adoptedStyleSheets.length !== 1 ||
      document.adoptedStyleSheets[0] !== sheet || document.activeElement !== button) return false;
  window.__syntheticFocusRules = sheet.cssRules.length;
  sheet.insertRule(':root form:has(+ section[aria-label="Current export preview"]) > '
    + 'button[type="submit"]:last-child:focus{opacity:1!important}', sheet.cssRules.length);
  return getComputedStyle(button).opacity === '1';
}"""

EXPORT_FOCUS_RESTORE = """() => {
  const root = document.querySelector('section[aria-label="Current export preview"]');
  const sheet = root && root.__emCaptureOwnedStyle;
  const button = root?.previousElementSibling?.lastElementChild;
  const initial = window.__syntheticFocusRules;
  if (!sheet || !Number.isInteger(initial) || sheet.cssRules.length !== initial + 1) return false;
  sheet.deleteRule(initial);
  delete window.__syntheticFocusRules;
  return document.activeElement === button && getComputedStyle(button).opacity === '0';
}"""

FOCUS_ORACLE = """async images => {
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
  const [visible, transparent, sanitized] = decoded.map(x => x.pixels);
  let changed = 0, leaked = 0;
  for (let i=0; i<visible.length; i+=4) {
    if (visible[i] !== transparent[i] || visible[i+1] !== transparent[i+1] ||
        visible[i+2] !== transparent[i+2] || visible[i+3] !== transparent[i+3]) {
      changed += 1;
      if (sanitized[i] !== transparent[i] || sanitized[i+1] !== transparent[i+1] ||
          sanitized[i+2] !== transparent[i+2] || sanitized[i+3] !== transparent[i+3]) leaked += 1;
    }
  }
  return {changed, leaked};
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


FAULT = """fault => {
  const root = document.querySelector('dl[aria-label="Plan summary"]');
  const owned = root.__emCaptureOwnedStyle;
  if (fault === 'preexisting') {
    const foreign = new CSSStyleSheet(); window.__foreign = foreign;
    document.adoptedStyleSheets = [foreign];
  } else if (fault === 'removed') document.adoptedStyleSheets = [];
  else if (fault === 'disabled') owned.disabled = true;
  else if (fault === 'mutated') owned.insertRule('body{color:red}', owned.cssRules.length);
  else if (fault === 'foreign' || fault === 'replaced') {
    const foreign = new CSSStyleSheet(); window.__foreign = foreign;
    document.adoptedStyleSheets = fault === 'foreign' ? [owned,foreign] : [foreign];
  } else if (fault === 'unexpected') document.body.append(document.createElement('div'));
  else if (fault === 'detached') root.remove();
  else if (fault === 'cleanup') {
    const current = document.adoptedStyleSheets;
    Object.defineProperty(document,'adoptedStyleSheets',{
      configurable:true,get(){return current;},set(){throw new Error('synthetic cleanup fault');}
    });
  } else return false;
  return true;
}"""


class CaptureHandle:
    def __init__(
        self,
        handle: Any,
        page: Page,
        name: str,
        fault: str | None = None,
        *,
        test_focus_pixels: bool = True,
    ) -> None:
        self.handle, self.page, self.name, self.fault = handle, page, name, fault
        self.test_focus_pixels = test_focus_pixels
        self.geometry: list[Any] = []
        self.fault_applied = False
        self.screenshot_attempted = False
        self.exposure_verified = False
        self.exposed_image: bytes | None = None
        self.control_image: bytes | None = None
        self.focus_visible_image: bytes | None = None
        self.focus_hidden_image: bytes | None = None

    async def evaluate(self, expression: str, *arguments: Any) -> Any:
        result = await self.handle.evaluate(expression, *arguments)
        if expression == GEOMETRY:
            self.geometry.append(result)
        if expression == INSTALL and result is True and self.fault:
            if await self.page.evaluate(FAULT, self.fault) is not True:
                raise RuntimeError("Synthetic fault unavailable")
            self.fault_applied = True
        return result

    async def screenshot(self, **options: Any) -> bytes:
        self.screenshot_attempted = True
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
            if self.name in {"evidence-quality", "export"} and self.test_focus_pixels:
                expose_focus = (
                    FOCUS_EXPOSE if self.name == "evidence-quality" else EXPORT_FOCUS_EXPOSE
                )
                restore_focus = (
                    FOCUS_RESTORE if self.name == "evidence-quality" else EXPORT_FOCUS_RESTORE
                )
                if await self.page.evaluate(expose_focus) is not True:
                    raise RuntimeError("Synthetic focus exposure unavailable")
                self.focus_visible_image = await self.handle.screenshot(**options)
                if await self.page.evaluate(restore_focus) is not True:
                    raise RuntimeError("Synthetic focus restoration unavailable")
                self.focus_hidden_image = await self.handle.screenshot(**options)
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

    async def scroll_into_view_if_needed(self, **options: Any) -> None:
        await self.handle.scroll_into_view_if_needed(**options)


class CaptureLocator:
    def __init__(
        self,
        locator: Any,
        page: Page,
        name: str,
        fault: str | None = None,
        *,
        test_focus_pixels: bool = True,
    ) -> None:
        self.locator, self.page, self.name, self.fault = locator, page, name, fault
        self.test_focus_pixels = test_focus_pixels
        self.handle: CaptureHandle | None = None

    async def count(self) -> int:
        return cast(int, await self.locator.count())

    async def element_handle(self) -> CaptureHandle:
        self.handle = CaptureHandle(
            await self.locator.element_handle(),
            self.page,
            self.name,
            self.fault,
            test_focus_pixels=self.test_focus_pixels,
        )
        return self.handle


class CapturePage:
    def __init__(
        self,
        page: Page,
        name: str,
        fault: str | None = None,
        *,
        test_focus_pixels: bool = True,
    ) -> None:
        self.page, self.name, self.fault = page, name, fault
        self.test_focus_pixels = test_focus_pixels
        self.capture_locator: CaptureLocator | None = None

    @property
    def url(self) -> str:
        return self.page.url

    async def evaluate(self, expression: str) -> Any:
        return await self.page.evaluate(expression)

    def locator(self, selector: str) -> CaptureLocator:
        self.capture_locator = CaptureLocator(
            self.page.locator(selector),
            self.page,
            self.name,
            self.fault,
            test_focus_pixels=self.test_focus_pixels,
        )
        return self.capture_locator


def assert_black_rectangles(image: bytes, boxes: list[tuple[int, int, int, int]]) -> None:
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
                raise RuntimeError("Chromium sandbox must remain enabled")

            current = {"name": "plan"}

            async def route_request(route: Route) -> None:
                if route.request.url == ORIGIN and route.request.method == "GET":
                    await route.fulfill(
                        status=200,
                        content_type="text/html",
                        body=fixture(current["name"]),
                    )
                elif (
                    route.request.url == ORIGIN + "synthetic.css" and route.request.method == "GET"
                ):
                    await route.fulfill(
                        status=200,
                        content_type="text/css",
                        body="body{font:16px sans-serif} "
                        "dl{display:grid;grid-template-columns:repeat(3,1fr);gap:8px} "
                        "dd{margin:0;overflow-wrap:anywhere} "
                        "button:focus{outline:3px solid #087f70;outline-offset:3px}",
                    )
                else:
                    await route.abort()

            await page.route("**/*", route_request)
            for name in TARGETS:
                current["name"] = name
                await page.goto(ORIGIN, wait_until="load")
                if name == "evidence-quality":
                    await page.locator("dialog").evaluate(
                        "dialog => { dialog.removeAttribute('open'); dialog.showModal(); }"
                    )
                    await page.locator("dialog > button.close").focus()
                    overlap = await page.evaluate("""() => {
                      const button = document.querySelector('dialog > button.close');
                      const heading = document.querySelector(
                        'section[aria-label="Article observation quality"] > h4');
                      const box = heading.getBoundingClientRect();
                      if (box.width < 96 || box.height < 16) return false;
                      button.style.position = 'fixed'; button.style.left = (box.left + 8) + 'px';
                      button.style.top = (box.top + 2) + 'px'; button.style.zIndex = '9999';
                      button.style.width = Math.min(80, box.width - 16) + 'px';
                      button.style.height = Math.min(12, box.height - 4) + 'px';
                      button.style.fontSize = '8px'; button.style.lineHeight = '8px';
                      button.style.padding = '0'; button.style.borderWidth = '1px';
                      const b = button.getBoundingClientRect();
                      const intersects = r => b.left < r.right && b.right > r.left &&
                        b.top < r.bottom && b.bottom > r.top;
                      const masks = Array.from(heading.parentElement.querySelectorAll('p'));
                      const clear = r => b.left - 8 >= r.right || b.right + 8 <= r.left ||
                        b.top - 8 >= r.bottom || b.bottom + 8 <= r.top;
                      return intersects(box) && masks.every(e => clear(e.getBoundingClientRect()));
                    }""")
                    if overlap is not True:
                        raise RuntimeError("Synthetic focus overlap unavailable")
                    focused = await page.evaluate("""() => document.activeElement ===
                      document.querySelector('dialog > button.close')""")
                    if focused is not True:
                        raise RuntimeError("Synthetic evidence focus unavailable")
                elif name == "export":
                    await page.locator("form > button[type=submit]:last-child").focus()
                    overlap = await page.evaluate("""() => {
                      const root = document.querySelector(
                        'section[aria-label="Current export preview"]');
                      const button = root?.previousElementSibling?.lastElementChild;
                      const heading = root?.querySelector('h4');
                      if (!button || document.activeElement !== button || !heading) return false;
                      const box = heading.getBoundingClientRect();
                      if (box.width < 96 || box.height < 16) return false;
                      document.styleSheets[0].insertRule(
                        'form:has(+ section[aria-label="Current export preview"]) > '
                        + 'button[type="submit"]:last-child{position:fixed;left:' + (box.left + 8)
                        + 'px;top:' + (box.top + 2) + 'px;z-index:9999;width:'
                        + Math.min(80, box.width - 16) + 'px;height:'
                        + Math.min(12, box.height - 4) + 'px;font-size:8px;line-height:8px;'
                        + 'padding:0;border-width:1px}', 0);
                      const b = button.getBoundingClientRect();
                      const intersects = r => b.left < r.right && b.right > r.left &&
                        b.top < r.bottom && b.bottom > r.top;
                      const clear = r => b.left - 8 >= r.right || b.right + 8 <= r.left ||
                        b.top - 8 >= r.bottom || b.bottom + 8 <= r.top;
                      return intersects(box) && Array.from(root.querySelectorAll('p, ul')).every(
                        e => clear(e.getBoundingClientRect()));
                    }""")
                    if overlap is not True:
                        raise RuntimeError("Synthetic export focus overlap unavailable")
                wrapped = CapturePage(page, name)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    await capture(cast(Page, wrapped), name)
                handle = wrapped.capture_locator.handle if wrapped.capture_locator else None
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
                image = base64.b64decode("".join(frame["data"] for frame in frames), validate=True)
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
                    raise RuntimeError("Synthetic independent pixel oracle unavailable") from None
                if (
                    not isinstance(oracle, dict)
                    or set(oracle) != {"changed", "leaked"}
                    or type(oracle["changed"]) is not int
                    or oracle["changed"] <= 0
                    or oracle["leaked"] != 0
                ):
                    raise RuntimeError("Synthetic independent pixel oracle refused")
                if name in {"evidence-quality", "export"}:
                    if handle.focus_visible_image is None or handle.focus_hidden_image is None:
                        raise RuntimeError("Synthetic focus pixels unavailable")
                    focus_images = [
                        base64.b64encode(item).decode("ascii")
                        for item in (
                            handle.focus_visible_image,
                            handle.focus_hidden_image,
                            image,
                        )
                    ]
                    result = await page.evaluate(FOCUS_ORACLE, focus_images)
                    if (
                        not isinstance(result, dict)
                        or set(result) != {"changed", "leaked"}
                        or type(result["changed"]) is not int
                        or result["changed"] <= 0
                        or result["leaked"] != 0
                    ):
                        raise RuntimeError("Synthetic focus pixel oracle refused")
                handle.exposed_image = None
                handle.control_image = None
                handle.focus_visible_image = None
                handle.focus_hidden_image = None
                if name == "evidence-quality":
                    focused = await page.evaluate("""() => document.activeElement ===
                      document.querySelector('dialog > button.close')""")
                    if focused is not True:
                        raise RuntimeError("Synthetic evidence focus changed")
                elif name == "export":
                    focused = await page.evaluate("""() => {
                      const root = document.querySelector(
                        'section[aria-label="Current export preview"]');
                      return document.activeElement ===
                        root?.previousElementSibling?.lastElementChild;
                    }""")
                    if focused is not True:
                        raise RuntimeError("Synthetic export focus changed")
            current["name"] = "plan"
            reasons = {
                "preexisting": "capture_shape_refused",
                "removed": "capture_geometry_refused",
                "disabled": "capture_geometry_refused",
                "mutated": "capture_geometry_refused",
                "foreign": "capture_geometry_refused",
                "replaced": "capture_geometry_refused",
                "unexpected": "capture_change_child",
                "detached": "capture_geometry_refused",
                "cleanup": "capture_mask_absent",
            }
            for fault, expected_reason in reasons.items():
                await page.goto(ORIGIN, wait_until="load")
                if fault == "preexisting" and await page.evaluate(FAULT, fault) is not True:
                    raise RuntimeError("Synthetic fault unavailable")
                wrapped = CapturePage(page, "plan", None if fault == "preexisting" else fault)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    try:
                        await capture(cast(Page, wrapped), "plan")
                    except ValueError as error:
                        if error.args != (expected_reason,):
                            raise RuntimeError("Synthetic refusal category refused") from None
                    else:
                        raise RuntimeError("Synthetic refusal missing")
                if output.getvalue():
                    raise RuntimeError("Synthetic refusal emitted output")
                handle = wrapped.capture_locator.handle if wrapped.capture_locator else None
                if handle is None or (fault != "preexisting" and not handle.fault_applied):
                    raise RuntimeError("Synthetic fault not applied")
                if handle.screenshot_attempted != (fault in ("unexpected", "cleanup")):
                    raise RuntimeError("Synthetic refusal phase refused")
                if fault in ("preexisting", "foreign", "replaced"):
                    intact = await page.evaluate("""() =>
                      document.adoptedStyleSheets.length === 1 &&
                      document.adoptedStyleSheets[0] === window.__foreign
                    """)
                    if intact is not True:
                        raise RuntimeError("Synthetic foreign sheet was not preserved")
                elif fault != "cleanup":
                    if await page.evaluate("document.adoptedStyleSheets.length") != 0:
                        raise RuntimeError("Synthetic owned sheet remained")
            current["name"] = "evidence-quality"
            focus_faults = {
                "wrong_text": "capture_mask_install_refused",
                "extra_dialog": "capture_shape_refused",
                "active_other": "capture_state_focus",
                "animation": "capture_mask_install_refused",
                "opacity_override": "capture_mask_install_refused",
            }
            for fault, expected_reason in focus_faults.items():
                await page.goto(ORIGIN, wait_until="load")
                await page.locator("dialog").evaluate(
                    "dialog => { dialog.removeAttribute('open'); dialog.showModal(); }"
                )
                await page.locator("dialog > button.close").focus()
                applied = await page.evaluate(
                    """fault => {
                  const close = document.querySelector('dialog > button.close');
                  if (fault === 'wrong_text') close.textContent = 'Other';
                  else if (fault === 'extra_dialog') {
                    const dialog = document.createElement('dialog');
                    dialog.setAttribute('open', ''); document.body.append(dialog);
                  } else if (fault === 'active_other') {
                    const button = document.createElement('button');
                    button.textContent = 'Other'; close.parentElement.append(button);
                    button.focus();
                  } else if (fault === 'animation') {
                    close.animate([{opacity: 0}, {opacity: 1}], {duration: 30000});
                  } else if (fault === 'opacity_override') {
                    document.styleSheets[0].insertRule(
                      'html body dialog[open][aria-labelledby="evidence-title"] > '
                      + 'button.close:first-child:focus{opacity:1!important}', 0);
                  } else return false;
                  return true;
                }""",
                    fault,
                )
                if applied is not True:
                    raise RuntimeError("Synthetic focus fault unavailable")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    try:
                        await capture(
                            cast(
                                Page,
                                CapturePage(page, "evidence-quality", test_focus_pixels=False),
                            ),
                            "evidence-quality",
                        )
                    except ValueError as error:
                        if error.args != (expected_reason,):
                            raise RuntimeError("Synthetic focus refusal category refused") from None
                    else:
                        raise RuntimeError("Synthetic focus refusal missing")
                if output.getvalue():
                    raise RuntimeError("Synthetic focus refusal emitted output")
            current["name"] = "export"
            export_focus_faults = {
                "wrong_text": "capture_shape_refused",
                "inline": "capture_shape_refused",
                "nested": "capture_shape_refused",
                "wrong_type": "capture_shape_refused",
                "active_other": "capture_shape_refused",
                "animation": "capture_mask_install_refused",
                "opacity_override": "capture_mask_install_refused",
            }
            for fault, expected_reason in export_focus_faults.items():
                await page.goto(ORIGIN, wait_until="load")
                await page.locator("form > button[type=submit]:last-child").focus()
                applied = await page.evaluate(
                    """fault => {
                  const root = document.querySelector(
                    'section[aria-label="Current export preview"]');
                  const button = root?.previousElementSibling?.lastElementChild;
                  if (!button || document.activeElement !== button) return false;
                  if (fault === 'wrong_text') button.textContent = 'Other';
                  else if (fault === 'inline') button.style.color = 'red';
                  else if (fault === 'nested') button.append(document.createElement('span'));
                  else if (fault === 'wrong_type') { button.type = 'button'; button.focus(); }
                  else if (fault === 'active_other') {
                    const other = document.createElement('button');
                    other.textContent = 'Other'; document.body.append(other); other.focus();
                  } else if (fault === 'animation') {
                    button.animate([{opacity: 0}, {opacity: 1}], {duration: 30000});
                  } else if (fault === 'opacity_override') {
                    document.styleSheets[0].insertRule(
                      'html body form:has(+ section[aria-label="Current export preview"]) > '
                      + 'button[type="submit"]:last-child:focus{opacity:1!important}', 0);
                  } else return false;
                  return true;
                }""",
                    fault,
                )
                if applied is not True:
                    raise RuntimeError("Synthetic export focus fault unavailable")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    try:
                        await capture(cast(Page, CapturePage(page, "export")), "export")
                    except ValueError as error:
                        if error.args != (expected_reason,):
                            raise RuntimeError("Synthetic export focus refusal refused") from None
                    else:
                        raise RuntimeError("Synthetic export focus refusal missing")
                if output.getvalue():
                    raise RuntimeError("Synthetic export focus refusal emitted output")
            await context.close()
        finally:
            await browser.close()


def test_actual_sandboxed_chromium_redacts_temporarily_exposed_synthetic_values() -> None:
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


class ScrollCaptureHandle:
    """Forward the original screenshot once; retain only synthetic test observations."""

    def __init__(
        self,
        handle: Any,
        page: Page,
        *,
        fail_restore: bool = False,
        disturb_document: bool = False,
        pause_finish: str = "",
        entered: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self.handle, self.page = handle, page
        self.fail_restore = fail_restore
        self.disturb_document, self.pause_finish = disturb_document, pause_finish
        self.entered, self.release = entered, release
        self.document_disturbed = False
        self.geometry: list[Any] = []
        self.screenshot_count = 0
        self.dialog_scroll_changed: bool | None = None
        self.outer_scroll_changed: bool | None = None

    async def evaluate(self, expression: str, *arguments: Any) -> Any:
        if expression == FINISH:
            self.dialog_scroll_changed = await self.page.evaluate("""() =>
              document.querySelector('dialog').scrollTop !== window.__emOriginalDialogScroll
            """)
            self.outer_scroll_changed = await self.page.evaluate("""() =>
              document.querySelector('.synthetic-outer').scrollTop !==
                window.__emOriginalOuterScroll
            """)
            if self.fail_restore:
                await self.page.evaluate("""() => {
                  const dialog = document.querySelector('dialog');
                  const current = dialog.scrollTop;
                  Object.defineProperty(dialog, 'scrollTop', {
                    configurable: true, get: () => current, set: () => {}
                  });
                }""")
            if self.disturb_document:
                self.document_disturbed = await self.page.evaluate("""() => {
                  document.body.scrollTop += 23;
                  document.documentElement.scrollTop += 21;
                  return document.body.scrollTop !== window.__emBodyScroll &&
                    document.documentElement.scrollTop !== window.__emDocumentScroll;
                }""")
            if self.pause_finish == "before" and self.entered and self.release:
                self.entered.set()
                await self.release.wait()
        result = await self.handle.evaluate(expression, *arguments)
        if expression == FINISH and self.pause_finish == "after" and self.entered and self.release:
            self.entered.set()
            await self.release.wait()
        if expression == GEOMETRY:
            self.geometry.append(result)
        return result

    async def screenshot(self, **options: Any) -> bytes:
        self.screenshot_count += 1
        return cast(bytes, await self.handle.screenshot(**options))

    async def scroll_into_view_if_needed(self, **options: Any) -> None:
        await self.handle.scroll_into_view_if_needed(**options)


class ScrollCaptureLocator:
    def __init__(self, locator: Any, page: Page, **options: Any) -> None:
        self.locator, self.page = locator, page
        self.options = options
        self.handle: ScrollCaptureHandle | None = None

    async def count(self) -> int:
        return cast(int, await self.locator.count())

    async def element_handle(self) -> ScrollCaptureHandle:
        self.handle = ScrollCaptureHandle(
            await self.locator.element_handle(),
            self.page,
            **self.options,
        )
        return self.handle


class ScrollCapturePage:
    def __init__(self, page: Page, **options: Any) -> None:
        self.page = page
        self.options = options
        self.capture_locator: ScrollCaptureLocator | None = None

    @property
    def url(self) -> str:
        return self.page.url

    async def evaluate(self, expression: str) -> Any:
        return await self.page.evaluate(expression)

    def locator(self, selector: str) -> ScrollCaptureLocator:
        self.capture_locator = ScrollCaptureLocator(
            self.page.locator(selector), self.page, **self.options
        )
        return self.capture_locator


async def exercise_scroll_guard() -> None:
    """Controlled modal mechanism; all screenshot bytes stay inside the guest."""
    html = (
        fixture("evidence-quality")
        .replace(
            "<h2 id='evidence-title'>Evidence and review</h2>",
            "<h2 id='evidence-title'>Evidence and review</h2>"
            "<div class='synthetic-spacer'></div>"
            "<div class='synthetic-outer'><div class='nested-spacer'></div>",
        )
        .replace("</section></dialog>", "</section></div></dialog>")
        .replace("</body>", "<div class='body-spacer'></div></body>")
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel="chromium",
            headless=True,
            chromium_sandbox=True,
            args=["--enable-automation"],
        )
        try:
            if browser.version != "153.0.8010.12":
                raise RuntimeError("Synthetic scroll control refused")
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
                raise RuntimeError("Synthetic scroll control refused")

            async def route_request(route: Route) -> None:
                if route.request.method == "GET" and route.request.url == ORIGIN:
                    await route.fulfill(status=200, content_type="text/html", body=html)
                elif (
                    route.request.method == "GET" and route.request.url == ORIGIN + "synthetic.css"
                ):
                    await route.fulfill(
                        status=200,
                        content_type="text/css",
                        body="html{overflow-y:scroll} "
                        "body{font:16px sans-serif;height:1200px;overflow:auto} "
                        ".body-spacer{height:3000px} "
                        "dialog{max-height:320px;overflow:auto} .synthetic-spacer{height:1000px} "
                        ".synthetic-outer{height:210px;overflow:auto}.nested-spacer{height:500px}",
                    )
                else:
                    await route.abort()

            await page.route("**/*", route_request)
            await page.goto(ORIGIN, wait_until="load")
            await page.locator("dialog").evaluate(
                "dialog => { dialog.removeAttribute('open'); dialog.showModal(); }"
            )
            await page.locator("dialog > button.close").focus()
            initial = await page.evaluate("""() => {
              const dialog = document.querySelector('dialog');
              const quality = document.querySelector(
                'section[aria-label="Article observation quality"]');
              document.body.scrollTop = 41;
              document.documentElement.scrollTop = 37;
              window.__emBodyScroll = document.body.scrollTop;
              window.__emDocumentScroll = document.documentElement.scrollTop;
              dialog.scrollTop = 0;
              document.querySelector('.synthetic-outer').scrollTop = 0;
              window.__emOriginalOuterScroll = 0;
              window.__emOriginalDialogScroll = dialog.scrollTop;
              return window.__emBodyScroll === 41 && window.__emDocumentScroll === 37 &&
                dialog.scrollTop === 0 && quality.getBoundingClientRect().top >=
                dialog.getBoundingClientRect().bottom && document.activeElement ===
                dialog.querySelector('button.close');
            }""")
            if initial is not True:
                raise RuntimeError("Synthetic scroll control refused")
            wrapped = ScrollCapturePage(page, disturb_document=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                await capture(cast(Page, wrapped), "evidence-quality")
            handle = wrapped.capture_locator.handle if wrapped.capture_locator else None
            if (
                not output.getvalue()
                or handle is None
                or handle.screenshot_count != 1
                or handle.dialog_scroll_changed is not True
                or handle.outer_scroll_changed is not True
                or handle.document_disturbed is not True
                or len(handle.geometry) != 2
                or any(type(value) is not dict for value in handle.geometry)
                or handle.geometry[0] != handle.geometry[1]
            ):
                raise RuntimeError("Synthetic scroll control refused")
            frames = [json.loads(line) for line in output.getvalue().splitlines()]
            if not frames or any(
                set(frame) != {"kind", "name", "part", "parts", "data"}
                or frame["kind"] != "capture"
                or frame["name"] != "evidence-quality"
                or frame["part"] != index
                or frame["parts"] != len(frames)
                for index, frame in enumerate(frames)
            ):
                raise RuntimeError("Synthetic scroll control refused")
            image = base64.b64decode("".join(frame["data"] for frame in frames), validate=True)
            width, height = struct.unpack(">II", image[16:24])
            assert_black_rectangles(
                image,
                redaction_rectangles(
                    handle.geometry[0], handle.geometry[1], width, height, "evidence-quality"
                ),
            )
            restored = await page.evaluate("""() => {
              const dialog = document.querySelector('dialog');
              return dialog.scrollTop === 0 &&
                document.querySelector('.synthetic-outer').scrollTop === 0 &&
                document.body.scrollTop === window.__emBodyScroll &&
                document.documentElement.scrollTop === window.__emDocumentScroll &&
                document.activeElement ===
                dialog.querySelector('button.close');
            }""")
            if restored is not True:
                raise RuntimeError("Synthetic scroll control refused")

            wrapped = ScrollCapturePage(page, fail_restore=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                try:
                    await capture(cast(Page, wrapped), "evidence-quality")
                except ValueError as error:
                    if error.args != ("capture_state_scroll",):
                        raise RuntimeError("Synthetic scroll control refused") from None
                else:
                    raise RuntimeError("Synthetic scroll control refused")
            if output.getvalue():
                raise RuntimeError("Synthetic scroll control refused")
            await page.evaluate("delete document.querySelector('dialog').scrollTop")
            await page.evaluate("document.querySelector('dialog').scrollTop = 0")
            await page.evaluate("document.querySelector('.synthetic-outer').scrollTop = 0")

            for phase in ("before", "after"):
                entered, release = asyncio.Event(), asyncio.Event()
                wrapped = ScrollCapturePage(
                    page, pause_finish=phase, entered=entered, release=release
                )
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    task = asyncio.create_task(capture(cast(Page, wrapped), "evidence-quality"))
                    try:
                        await asyncio.wait_for(entered.wait(), timeout=20)
                        task.cancel()
                        await asyncio.sleep(0)
                        release.set()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                        else:
                            raise RuntimeError("Synthetic interruption control refused")
                    finally:
                        release.set()
                        if not task.done():
                            task.cancel()
                        try:
                            await task
                        except BaseException:  # noqa: BLE001 - retain the control's outcome
                            pass
                if output.getvalue() or not await page.evaluate("""() => {
                  const dialog = document.querySelector('dialog');
                  return dialog.scrollTop === 0 &&
                    document.querySelector('.synthetic-outer').scrollTop === 0 &&
                    document.body.scrollTop === window.__emBodyScroll &&
                    document.documentElement.scrollTop === window.__emDocumentScroll &&
                    document.activeElement === dialog.querySelector('button.close');
                }"""):
                    raise RuntimeError("Synthetic interruption control refused")

            quality = page.locator('section[aria-label="Article observation quality"]')
            await quality.scroll_into_view_if_needed(timeout=5000)
            before_visible = await page.evaluate("""() => {
              const dialog = document.querySelector('dialog');
              window.__emOriginalDialogScroll = dialog.scrollTop;
              window.__emOriginalOuterScroll = document.querySelector('.synthetic-outer').scrollTop;
              return document.activeElement === dialog.querySelector('button.close');
            }""")
            if before_visible is not True:
                raise RuntimeError("Synthetic scroll control refused")
            wrapped = ScrollCapturePage(page)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                await capture(cast(Page, wrapped), "evidence-quality")
            handle = wrapped.capture_locator.handle if wrapped.capture_locator else None
            if (
                not output.getvalue()
                or handle is None
                or handle.screenshot_count != 1
                or handle.dialog_scroll_changed is not False
                or handle.outer_scroll_changed is not False
                or len(handle.geometry) != 2
                or handle.geometry[0] != handle.geometry[1]
            ):
                raise RuntimeError("Synthetic scroll control refused")
            after_visible = await page.evaluate("""() => {
              const dialog = document.querySelector('dialog');
              return dialog.scrollTop === window.__emOriginalDialogScroll &&
                document.querySelector('.synthetic-outer').scrollTop ===
                  window.__emOriginalOuterScroll &&
                document.activeElement === dialog.querySelector('button.close');
            }""")
            if after_visible is not True:
                raise RuntimeError("Synthetic scroll control refused")
            await context.close()
        finally:
            await browser.close()


def test_actual_sandboxed_modal_scroll_guard() -> None:
    require_existing_isolation()
    try:
        asyncio.run(asyncio.wait_for(exercise_scroll_guard(), timeout=180))
    except BaseException:  # noqa: BLE001 - never emit screenshot data or guest traces
        raise RuntimeError("Synthetic scroll control refused") from None

"""Fixed synthetic UI crops and strict bounded transport; no raw page dumps."""

import base64
import binascii
import json
import re
import struct
import zlib
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from playwright.async_api import Page

ORIGIN = "app.example.test"
CORE = ("plan", "evidence-quality", "export")
PRIVACY = ("suppression", "deletion")
MAX_IMAGE = 131072
CHUNK = 8192
MAX_SIDE = 1800
FIXED_COLOR_CHUNKS = {
    b"sRGB": b"\x00",
    b"gAMA": struct.pack(">I", 45455),
    b"cHRM": struct.pack(">8I", 31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000),
}
LIMITATIONS = {
    "plan": "All plan values are hidden.",
    "evidence-quality": "Article quality only; this is not the retained citation.",
    "export": "Preview details and counts are hidden.",
    "suppression": "Confirmation details and organization are hidden.",
    "deletion": "Confirmation details and organization are hidden.",
}

# Each selector and mask is code-owned. No caller or frame can provide a selector.
TARGETS = {
    "plan": ('dl[aria-label="Plan summary"]', "dd"),
    "evidence-quality": (
        'section[aria-label="Article observation quality"]',
        "p:nth-of-type(1)",
    ),
    "export": ('section[aria-label="Current export preview"]', "p, ul"),
    "suppression": ('dialog[open][aria-labelledby="confirm-title"]', "p"),
    "deletion": ('dialog[open][aria-labelledby="confirm-title"]', "p"),
}

# Only fixed labels leave the browser in this Boolean check; dynamic values are
# never returned. Every dynamic node is hidden, including overflowing descendants.
SHAPE = r"""(root, config) => {
  const name = config.name;
  const child = e => Array.from(e.children).map(x => x.tagName);
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const leaf = e => e && e.children.length === 0;
  const cleanText = e => Array.from(e.childNodes).every(
    n => n.nodeType !== 3 || !n.textContent.trim()
  );
  const selectors = {
    plan: 'dl[aria-label="Plan summary"]',
    'evidence-quality': 'section[aria-label="Article observation quality"]',
    export: 'section[aria-label="Current export preview"]',
    suppression: 'dialog[open][aria-labelledby="confirm-title"]',
    deletion: 'dialog[open][aria-labelledby="confirm-title"]'
  };
  const matches = document.querySelectorAll(selectors[name]);
  const all = Array.from(document.body.querySelectorAll('*'));
  const safeRules = rules => Array.from(rules).every(rule => {
    if (rule.cssRules && !safeRules(rule.cssRules)) return false;
    return !rule.style || (
      rule.style.getPropertyPriority('visibility') !== 'important' &&
      rule.style.getPropertyPriority('all') !== 'important'
    );
  });
  try {
    if (!Array.from(document.styleSheets).every(sheet => safeRules(sheet.cssRules))) return false;
  } catch (_) { return false; }
  const headings = document.querySelectorAll('.workspace-heading h2');
  if (headings.length !== 1 || headings[0].textContent !== 'Synthetic tenant 0' ||
      Array.from(document.querySelectorAll('a')).some(
        link => link.textContent === 'Sign in with configured identity'
      )) return false;
  const forbidden = ['IFRAME','OBJECT','EMBED','CANVAS','VIDEO','AUDIO','IMG','SVG'];
  if (!cleanText(document.body) || matches.length !== 1 || matches[0] !== root ||
      all.length > 4096 ||
      all.some(e => e.shadowRoot || e.tagName.includes('-') ||
        e.style.getPropertyPriority('visibility') === 'important' ||
        forbidden.includes(e.tagName))) return false;
  const nodes = [root, ...root.querySelectorAll('*')];
  if (!root.isConnected || nodes.some(e => e.shadowRoot || e.tagName.includes('-') ||
      e.hasAttribute('style') || forbidden.includes(e.tagName) ||
      ['INPUT','SELECT','TEXTAREA'].includes(e.tagName))) return false;
  const active = document.activeElement;
  if (active && ['INPUT','SELECT','TEXTAREA'].includes(active.tagName)) return false;
  const dialogs = Array.from(document.querySelectorAll('dialog[open]'));
  if (name === 'evidence-quality') {
    if (dialogs.length !== 1 || !dialogs[0].contains(root) ||
        dialogs[0].getAttribute('aria-labelledby') !== 'evidence-title') return false;
  } else if (name === 'suppression' || name === 'deletion') {
    if (dialogs.length !== 1 || dialogs[0] !== root) return false;
  } else if (dialogs.length !== 0) return false;
  const visible = e => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility === 'visible';
  };
  if (!visible(root)) return false;
  let masks = [];
  if (name === 'plan') {
    const labels = [
      'Source identity', 'Planned start URL', 'Original query', 'Effective query',
      'Requested article limit', 'Effective article cap', 'Maximum result pages',
      'Author selection', 'Browser work', 'Authored PDF fixtures',
      'Policy version at planning', 'Source-reported total at planning',
      'Article URLs listed at planning'
    ];
    const rows = Array.from(root.children);
    if (!cleanText(root) || rows.length !== labels.length || rows.some((r, i) =>
      r.tagName !== 'DIV' || !cleanText(r) || !same(child(r), ['DT','DD']) ||
      !leaf(r.children[0]) || !leaf(r.children[1]) ||
      r.children[0].textContent !== labels[i])) return false;
    masks = rows.map(r => r.children[1]);
  } else if (name === 'evidence-quality') {
    const last = 'Missing affiliations remain unobserved, not confirmed absent. ' +
      'Accepting or correcting an author-email association does not resolve ' +
      'affiliation uncertainty or change the retained parser outcome.';
    const unavailable = 'Parser-specific reasons are not recorded for this route.';
    if (!cleanText(root) || !same(child(root), ['H4','P','P','P']) ||
        !Array.from(root.children).every(leaf) ||
        root.children[0].textContent !== 'Article observation quality' ||
        root.children[2].textContent !== unavailable ||
        root.children[3].textContent !== last) return false;
    masks = [root.children[1]];
  } else if (name === 'export') {
    if (!cleanText(root) || !same(child(root), ['H4','P','P','UL','P','BUTTON']) ||
        !leaf(root.children[0]) || !leaf(root.children[1]) || !leaf(root.children[2]) ||
        !leaf(root.children[4]) || !leaf(root.children[5]) ||
        root.children[0].textContent !== 'Current eligible preview' ||
        root.children[5].textContent !== 'Create asynchronous export' ||
        !cleanText(root.children[3]) || Array.from(root.children[3].children).some(
          e => e.tagName !== 'LI' || !leaf(e)
        )) return false;
    masks = [root.children[1],root.children[2],root.children[4]];
  } else if (name === 'suppression' || name === 'deletion') {
    if (!cleanText(root) || !same(child(root), ['H2','P','P','DIV']) ||
        !leaf(root.children[0]) || !leaf(root.children[1]) || !leaf(root.children[2]) ||
        !cleanText(root.children[3]) || !same(child(root.children[3]), ['BUTTON','BUTTON']) ||
        !Array.from(root.children[3].children).every(leaf)) return false;
    const title = name === 'suppression' ? 'Suppress observed contact' : 'Stage job deletion';
    const confirm = name === 'suppression' ?
      'Confirm suppress observed contact' : 'Confirm stage job deletion';
    if (root.children[0].textContent !== title ||
        root.children[3].children[0].textContent !== 'Keep unchanged' ||
        root.children[3].children[1].textContent !== confirm) return false;
    masks = [root.children[1],root.children[2]];
  } else return false;
  if (masks.some(e => !visible(e) || !e.textContent.trim())) return false;
  if (root.__emCaptureObserver) return false;
  root.__emCaptureChanged = false;
  root.__emCaptureMaskVerified = false;
  root.__emCaptureChangeKind = 'other';
  root.__emCaptureMaskKind = 'absent';
  root.__emCaptureScroll = [
    window.scrollX, window.scrollY,
    all.map(e => [e,e.scrollLeft,e.scrollTop]), document.activeElement
  ];
  root.__emCaptureUnexpected = records => records.some(record => {
    if (record.type !== 'childList' || record.target !== document.documentElement) {
      root.__emCaptureChangeKind = record.type === 'attributes' ? 'attribute' :
        record.type === 'characterData' ? 'text' : 'child';
      return true;
    }
    const nodes = [...record.addedNodes, ...record.removedNodes];
    if (!nodes.length || nodes.some(node => node.nodeType !== 1 ||
        node.tagName !== 'STYLE' || node.textContent !== config.style)) {
      root.__emCaptureChangeKind = 'style';
      return true;
    }
    if (record.addedNodes.length) {
      const masked = name === 'export' ? [...masks, root.children[3]] : masks;
      const target = getComputedStyle(root).visibility === 'visible';
      const values = masked.every(e => getComputedStyle(e).visibility === 'hidden');
      const outside = all.filter(e => !root.contains(e)).every(
        e => getComputedStyle(e).visibility === 'hidden'
      );
      root.__emCaptureMaskKind = !target ? 'target' : !values ? 'values' :
        !outside ? 'outside' : 'verified';
      root.__emCaptureMaskVerified = target && values && outside;
    }
    return false;
  });
  root.__emCaptureObserver = new MutationObserver(records => {
    if (root.__emCaptureUnexpected(records)) root.__emCaptureChanged = true;
  });
  root.__emCaptureObserver.observe(document.documentElement, {
    subtree:true, childList:true, characterData:true, attributes:true
  });
  return true;
}"""

FINISH = """root => {
  if (!root.__emCaptureObserver) return 'observer';
  const changed = root.__emCaptureChanged ||
    root.__emCaptureUnexpected(root.__emCaptureObserver.takeRecords());
  const maskVerified = root.__emCaptureMaskVerified;
  const changeKind = root.__emCaptureChangeKind;
  const maskKind = root.__emCaptureMaskKind;
  root.__emCaptureObserver.disconnect();
  const state = root.__emCaptureScroll;
  let restored = !!state && state[2].every(item => item[0].isConnected);
  let stateKind = 'detached';
  if (restored) {
    for (const [element, left, top] of state[2]) {
      element.scrollLeft = left;
      element.scrollTop = top;
    }
    window.scrollTo(state[0], state[1]);
    restored = window.scrollX === state[0] && window.scrollY === state[1] &&
      document.activeElement === state[3] && state[2].every(
        item => item[0].scrollLeft === item[1] && item[0].scrollTop === item[2]
      );
    stateKind = document.activeElement !== state[3] ? 'focus' : 'scroll';
  }
  delete root.__emCaptureObserver;
  delete root.__emCaptureChanged;
  delete root.__emCaptureMaskVerified;
  delete root.__emCaptureChangeKind;
  delete root.__emCaptureMaskKind;
  delete root.__emCaptureUnexpected;
  delete root.__emCaptureScroll;
  if (!root.isConnected) return 'detached';
  if (changed) return 'changed_' + changeKind;
  if (!restored) return 'state_' + stateKind;
  if (!maskVerified) return 'mask_' + maskKind;
  return 'ok';
}"""


def style_for(name: str) -> str:
    selector, mask = TARGETS[name]
    return (
        "body *{visibility:hidden!important;}"
        + f"{selector},{selector} *{{visibility:visible!important;}}"
        + ",".join(f"{selector} {part.strip()}" for part in mask.split(","))
        + "{visibility:hidden!important;}"
        + ",".join(f"{selector} {part.strip()} *" for part in mask.split(","))
        + "{visibility:hidden!important;}"
        + "*::before,*::after,*::marker,*::backdrop{visibility:hidden!important;"
        "content:none!important;}"
        + "*{background-image:none!important;list-style-image:none!important;"
        "text-shadow:none!important;}"
    )


def validate_png(data: bytes) -> None:
    """Reject oversized/metadata-bearing/corrupt PNGs and decompression bombs."""
    if len(data) > MAX_IMAGE or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("capture_png_refused")
    offset, body = 8, bytearray()
    seen: list[bytes] = []
    dimensions: tuple[int, int, int] | None = None
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("capture_png_refused")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("capture_png_refused")
        kind, chunk = (
            data[offset + 4 : offset + 8],
            data[offset + 8 : offset + 8 + length],
        )
        crc = struct.unpack(">I", data[offset + 8 + length : end])[0]
        if zlib.crc32(kind + chunk) & 0xFFFFFFFF != crc:
            raise ValueError("capture_png_refused")
        if kind == b"IHDR" and not seen and length == 13:
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
            if not (
                1 <= width <= MAX_SIDE
                and 1 <= height <= MAX_SIDE
                and depth == 8
                and color in (2, 6)
                and compression == filtering == interlace == 0
            ):
                raise ValueError("capture_png_refused")
            dimensions = (width, height, 3 if color == 2 else 4)
        elif (
            kind == b"IDAT"
            and dimensions
            and seen[-1] in (b"IHDR", b"sRGB", b"gAMA", b"cHRM", b"IDAT")
        ):
            body.extend(chunk)
        elif (
            kind in FIXED_COLOR_CHUNKS
            and seen
            and seen[-1] != b"IDAT"
            and kind not in seen
            and chunk == FIXED_COLOR_CHUNKS[kind]
        ):
            # Exact constant color profiles carry no arbitrary metadata.
            pass
        elif kind == b"IEND" and length == 0 and body and seen[-1] == b"IDAT" and end == len(data):
            seen.append(kind)
            break
        else:
            raise ValueError("capture_png_refused")
        seen.append(kind)
        offset = end
    if not dimensions or not seen or seen[-1] != b"IEND":
        raise ValueError("capture_png_refused")
    width, height, channels = dimensions
    expected = height * (1 + width * channels)
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(bytes(body), expected + 1)
        if (
            len(pixels) != expected
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
            or any(pixels[row * (1 + width * channels)] > 4 for row in range(height))
        ):
            raise ValueError
    except (ValueError, zlib.error):
        raise ValueError("capture_png_refused") from None


async def capture(page: "Page", name: str) -> None:
    """Emit one fixed crop only after screenshot-only hiding and mutation checks."""
    if name not in TARGETS:
        raise ValueError("capture_checkpoint_refused")
    parsed = urlsplit(page.url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != ORIGIN
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("capture_origin_refused")
    if not await page.evaluate("""() => {
        const headings = document.querySelectorAll('.workspace-heading h2');
        const links = Array.from(document.querySelectorAll('a'));
        return headings.length === 1 && headings[0].textContent === 'Synthetic tenant 0' &&
          !links.some(link => link.textContent === 'Sign in with configured identity');
    }"""):
        raise ValueError("capture_session_refused")
    selector, _ = TARGETS[name]
    locator = page.locator(selector)
    if await locator.count() != 1:
        raise ValueError("capture_region_refused")
    handle = await locator.element_handle()
    style = style_for(name)
    if handle is None or not await handle.evaluate(SHAPE, {"name": name, "style": style}):
        raise ValueError("capture_shape_refused")
    try:
        image = await handle.screenshot(
            type="png", animations="allow", caret="initial", style=style, timeout=5000
        )
    except BaseException as error:
        try:
            await handle.evaluate(FINISH)
        except BaseException:  # noqa: BLE001 - preserve the triggering failure
            error.add_note("capture_cleanup_unavailable")
        raise
    outcome = await handle.evaluate(FINISH)
    if outcome != "ok":
        reasons = {
            "observer": "capture_observer_missing",
            "detached": "capture_target_detached",
            "changed_attribute": "capture_change_attribute",
            "changed_text": "capture_change_text",
            "changed_child": "capture_change_child",
            "changed_style": "capture_change_style",
            "state_detached": "capture_state_detached",
            "state_focus": "capture_state_focus",
            "state_scroll": "capture_state_scroll",
            "mask_absent": "capture_mask_absent",
            "mask_target": "capture_mask_target",
            "mask_values": "capture_mask_values",
            "mask_outside": "capture_mask_outside",
        }
        reason = (
            reasons.get(outcome, "capture_mutated")
            if isinstance(outcome, str)
            else "capture_mutated"
        )
        raise ValueError(reason)
    validate_png(image)
    encoded = base64.b64encode(image).decode("ascii")
    parts = [encoded[index : index + CHUNK] for index in range(0, len(encoded), CHUNK)]
    for index, part in enumerate(parts):
        print(
            json.dumps(
                {
                    "kind": "capture",
                    "name": name,
                    "part": index,
                    "parts": len(parts),
                    "data": part,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )


class Collector:
    """Closed ordered capture grammar; caller decides when to retain images."""

    def __init__(self, expected: tuple[str, ...]) -> None:
        if expected not in (CORE, PRIVACY):
            raise ValueError("capture_session_refused")
        self.expected = expected
        self.images: dict[str, bytes] = {}
        self.parts: list[str] = []
        self.part_count = 0

    def accept(self, value: dict[str, Any]) -> None:
        if (
            set(value) != {"kind", "name", "part", "parts", "data"}
            or value.get("kind") != "capture"
        ):
            raise ValueError("capture_frame_refused")
        index = len(self.images)
        if index >= len(self.expected) or value["name"] != self.expected[index]:
            raise ValueError("capture_order_refused")
        part, parts, data = value["part"], value["parts"], value["data"]
        if (
            type(part) is not int
            or type(parts) is not int
            or not 1 <= parts <= 22
            or part != len(self.parts)
            or part >= parts
            or type(data) is not str
            or not 1 <= len(data) <= CHUNK
            or not re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", data)
        ):
            raise ValueError("capture_frame_refused")
        if self.parts and parts != self.part_count:
            raise ValueError("capture_frame_refused")
        self.part_count = parts
        self.parts.append(data)
        if len(self.parts) == parts:
            try:
                image = base64.b64decode("".join(self.parts), validate=True)
                validate_png(image)
            except (binascii.Error, ValueError):
                raise ValueError("capture_png_refused") from None
            self.images[self.expected[index]] = image
            self.parts = []
            self.part_count = 0

    def finish(self) -> dict[str, bytes]:
        if self.parts or tuple(self.images) != self.expected:
            raise ValueError("capture_incomplete")
        return dict(self.images)


def save_bundle(
    core: dict[str, bytes],
    privacy: dict[str, bytes],
    *,
    runner_temp: str,
    head: str,
    checked_out_commit: str,
    tree: str,
) -> None:
    """Write only fixed validated images after both sessions and final assertions."""
    import os
    from pathlib import Path

    if tuple(core) != CORE or tuple(privacy) != PRIVACY:
        raise ValueError("capture_incomplete")
    if any(not re.fullmatch(r"[0-9a-f]{40}", value) for value in (head, checked_out_commit, tree)):
        raise ValueError("capture_source_refused")
    images = {**core, **privacy}
    for image in images.values():
        validate_png(image)
    root = Path(runner_temp)
    if not root.is_absolute() or root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError("capture_destination_refused")
    target = root / "emailmonitor-synthetic-operator-captures"
    files: list[Path] = []
    made = False
    try:
        target.mkdir(mode=0o700)
        made = True
        manifest: dict[str, object] = {
            "schema": "synthetic-operator-crops-v1",
            "status": "pending_visual_privacy_review",
            "head": head,
            "checked_out_commit": checked_out_commit,
            "tree": tree,
            "sessions": {"core": list(CORE), "privacy": list(PRIVACY)},
            "limitations": LIMITATIONS,
        }
        for index, (name, image) in enumerate(images.items(), 1):
            destination = target / f"{index:02d}-{name}.png"
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            files.append(destination)
            with os.fdopen(fd, "wb") as stream:
                stream.write(image)
        destination = target / "manifest.json"
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        files.append(destination)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, sort_keys=True)
            stream.write("\n")
    except BaseException as error:
        for path in reversed(files):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                error.add_note("capture_cleanup_unavailable")
        if made:
            try:
                target.rmdir()
            except OSError:
                error.add_note("capture_cleanup_unavailable")
        raise


def verify_bundle(*, runner_temp: str, head: str, checked_out_commit: str, tree: str) -> None:
    """Recheck the exact output set before a workflow uploads it."""
    import os
    import stat
    from pathlib import Path

    root = Path(runner_temp)
    if not root.is_absolute() or root.resolve(strict=True) != root or not root.is_dir():
        raise ValueError("capture_destination_refused")
    target = root / "emailmonitor-synthetic-operator-captures"
    state = target.lstat()
    if (
        not stat.S_ISDIR(state.st_mode)
        or state.st_uid != os.getuid()
        or stat.S_IMODE(state.st_mode) != 0o700
    ):
        raise ValueError("capture_destination_refused")
    names = CORE + PRIVACY
    expected = {f"{index:02d}-{name}.png" for index, name in enumerate(names, 1)} | {
        "manifest.json"
    }
    if {path.name for path in target.iterdir()} != expected:
        raise ValueError("capture_bundle_refused")
    for name in expected:
        path = target / name
        item = path.lstat()
        if (
            not stat.S_ISREG(item.st_mode)
            or item.st_uid != os.getuid()
            or stat.S_IMODE(item.st_mode) != 0o600
            or item.st_size > (2048 if name == "manifest.json" else MAX_IMAGE)
        ):
            raise ValueError("capture_bundle_refused")
        if name.endswith(".png"):
            validate_png(path.read_bytes())
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    if manifest != {
        "schema": "synthetic-operator-crops-v1",
        "status": "pending_visual_privacy_review",
        "head": head,
        "checked_out_commit": checked_out_commit,
        "tree": tree,
        "sessions": {"core": list(CORE), "privacy": list(PRIVACY)},
        "limitations": LIMITATIONS,
    } or any(
        not re.fullmatch(r"[0-9a-f]{40}", value) for value in (head, checked_out_commit, tree)
    ):
        raise ValueError("capture_bundle_refused")


def main() -> None:
    """Workflow-only final bundle check; emits no image or DOM data."""
    import os
    import subprocess

    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("EM_OPERATOR_CAPTURE") != "1":
        raise RuntimeError("Reviewed synthetic capture CI required")

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "--no-optional-locks", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()

    verify_bundle(
        runner_temp=os.environ["RUNNER_TEMP"],
        head=os.environ["EM_CAPTURE_HEAD_SHA"],
        checked_out_commit=git("rev-parse", "HEAD"),
        tree=git("rev-parse", "HEAD^{tree}"),
    )
    print("synthetic_capture_bundle_verified")


if __name__ == "__main__":
    main()

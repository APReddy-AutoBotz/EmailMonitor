"""Synthetic capture contracts; no browser, services, credentials or screenshots."""

import asyncio
import base64
import json
import os
import struct
import subprocess
import zlib
from pathlib import Path
from typing import Any, cast

import pytest
from operator_capture import (
    CORE,
    PRIVACY,
    Collector,
    capture,
    redact_png,
    redaction_rectangles,
    save_bundle,
    style_for,
    validate_png,
    verify_bundle,
)
from playwright.async_api import Page


def chunk(kind: bytes, value: bytes) -> bytes:
    return (
        struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value))
    )


def image(*, ancillary: bytes = b"", pixel: bytes = b"\x00\x00\x00\x00") -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + ancillary
        + chunk(b"IDAT", zlib.compress(pixel))
        + chunk(b"IEND", b"")
    )


def frame(name: str, payload: bytes | None = None) -> dict[str, object]:
    return {
        "kind": "capture",
        "name": name,
        "part": 0,
        "parts": 1,
        "data": base64.b64encode(payload or image()).decode(),
    }


def images(names: tuple[str, ...]) -> dict[str, bytes]:
    collector = Collector(names)
    for name in names:
        collector.accept(frame(name))
    return collector.finish()


def test_png_accepts_valid_bounded_pixels() -> None:
    validate_png(image())
    validate_png(image(ancillary=chunk(b"sRGB", b"\x00")))


@pytest.mark.parametrize(
    "data",
    [
        image(ancillary=chunk(b"tEXt", b"private")),
        image(ancillary=chunk(b"sRGB", b"\x01")),
        image(ancillary=chunk(b"gAMA", b"nope")),
        image(ancillary=chunk(b"sRGB", b"\x00") + chunk(b"sRGB", b"\x00")),
        image() + b"trailing",
        image(pixel=b"\x05\x00\x00\x00"),
        image()[:-1],
        b"not-a-png",
    ],
)
def test_png_rejects_metadata_invalid_filters_and_trailing_data(data: bytes) -> None:
    with pytest.raises(ValueError, match="capture_png_refused"):
        validate_png(data)


def test_png_rejects_invalid_crc() -> None:
    data = bytearray(image())
    data[-1] ^= 1
    with pytest.raises(ValueError, match="capture_png_refused"):
        validate_png(bytes(data))


def filtered_image(width: int, height: int, channels: int, kind: int) -> tuple[bytes, bytes]:
    """Build synthetic PNG data with a known filter and distinct pixel values."""
    stride = width * channels
    plain = bytes((index * 31 + 7) % 256 for index in range(stride * height))
    previous = bytes(stride)
    rows = bytearray()
    for y in range(height):
        row = plain[y * stride : (y + 1) * stride]
        rows.append(kind)
        for i, value in enumerate(row):
            left = row[i - channels] if i >= channels else 0
            up = previous[i]
            upper_left = previous[i - channels] if i >= channels else 0
            if kind == 0:
                predictor = 0
            elif kind == 1:
                predictor = left
            elif kind == 2:
                predictor = up
            elif kind == 3:
                predictor = (left + up) // 2
            else:
                p = left + up - upper_left
                distances = (abs(p - left), abs(p - up), abs(p - upper_left))
                predictor = (left, up, upper_left)[distances.index(min(distances))]
            rows.append((value - predictor) & 255)
        previous = row
    header = struct.pack(">IIBBBBB", width, height, 8, 2 if channels == 3 else 6, 0, 0, 0)
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows)))
        + chunk(b"IEND", b"")
    )
    return data, plain


@pytest.mark.parametrize("kind", range(5))
@pytest.mark.parametrize("channels", [3, 4])
def test_redaction_overwrites_sentinel_pixels_for_all_supported_filters(
    kind: int, channels: int
) -> None:
    width, height = 5, 3
    original, plain = filtered_image(width, height, channels, kind)
    result = redact_png(original, [(1, 0, 4, 2), (3, 1, 5, 3)])
    validate_png(result)
    length = struct.unpack(">I", result[33:37])[0]
    decoded = zlib.decompress(result[41 : 41 + length])
    stride = width * channels
    black = bytes((0, 0, 0) if channels == 3 else (0, 0, 0, 255))
    for y in range(height):
        assert decoded[y * (stride + 1)] == 0
        row = decoded[y * (stride + 1) + 1 : (y + 1) * (stride + 1)]
        for x in range(width):
            pixel = row[x * channels : (x + 1) * channels]
            masked = (1 <= x < 4 and y < 2) or (3 <= x < 5 and y >= 1)
            assert pixel == (black if masked else plain[(y * width + x) * channels :][:channels])


@pytest.mark.parametrize(
    "rectangles", [[], [(-1, 0, 1, 1)], [(0, 0, 2, 1)], [(0, 0, 0, 1)], [(True, 0, 1, 1)]]
)
def test_redaction_refuses_invalid_rectangles(rectangles: Any) -> None:
    with pytest.raises(ValueError, match="capture_geometry_refused"):
        redact_png(image(), rectangles)


def test_redaction_removes_ancillary_chunks_and_refuses_excessive_masks() -> None:
    source = image(ancillary=chunk(b"sRGB", b"\x00"), pixel=b"\x00\x12\x34\x56")
    result = redact_png(source, [(0, 0, 1, 1)])
    assert b"sRGB" not in result
    length = struct.unpack(">I", result[33:37])[0]
    assert zlib.decompress(result[41 : 41 + length]) == b"\x00\x00\x00\x00"
    validate_png(redact_png(source, [(0, 0, 1, 1)] * 256))
    with pytest.raises(ValueError, match="capture_geometry_refused"):
        redact_png(source, [(0, 0, 1, 1)] * 257)


def test_redaction_accepts_consecutive_png_data_chunks() -> None:
    source, _ = filtered_image(5, 3, 4, 4)
    length = struct.unpack(">I", source[33:37])[0]
    compressed = source[41 : 41 + length]
    split = len(compressed) // 2
    combined = (
        source[:33]
        + chunk(b"IDAT", compressed[:split])
        + chunk(b"IDAT", compressed[split:])
        + chunk(b"IEND", b"")
    )
    validate_png(redact_png(combined, [(1, 0, 4, 3)]))


def mock_geometry(root: list[float], boxes: list[list[float]]) -> dict[str, Any]:
    return {"root": root, "boxes": boxes, "count": 1, "covered": 1}


def test_geometry_uses_playwright_css_crop_rounding_and_padded_clipping() -> None:
    geometry = mock_geometry([10.2, 20.3, 110.2, 120.3], [[30.5, 40.5, 40.5, 50.5]])
    assert redaction_rectangles(geometry, geometry, 101, 101, "evidence-quality") == [
        (12, 12, 39, 39)
    ]
    edge = mock_geometry([10.2, 20.3, 110.2, 120.3], [[10.2, 20.3, 15, 25]])
    assert redaction_rectangles(edge, edge, 101, 101, "evidence-quality")[0][:2] == (0, 0)


@pytest.mark.parametrize(
    "before,after,width,height",
    [
        (None, None, 1, 1),
        (mock_geometry([0, 0, 1, 1], []), mock_geometry([0, 0, 1, 1], []), 1, 1),
        (mock_geometry([0, 0, 1, 1], [[0, 0, 1, 1]]), None, 1, 1),
        (
            mock_geometry([0, 0, 1, 1], [[-1, 0, 1, 1]]),
            mock_geometry([0, 0, 1, 1], [[-1, 0, 1, 1]]),
            1,
            1,
        ),
        (
            mock_geometry([0, 0, 1, 1], [[0, 0, 1, 1]]),
            mock_geometry([0, 0, 1, 1], [[0, 0, 1, 1]]),
            2,
            1,
        ),
        (
            mock_geometry([0, 0, float("nan"), 1], [[0, 0, 1, 1]]),
            mock_geometry([0, 0, float("nan"), 1], [[0, 0, 1, 1]]),
            1,
            1,
        ),
    ],
)
def test_geometry_refuses_unknown_moved_clipped_or_invalid_inputs(
    before: Any, after: Any, width: int, height: int
) -> None:
    with pytest.raises(ValueError, match="capture_geometry_refused"):
        redaction_rectangles(before, after, width, height, "evidence-quality")


@pytest.mark.parametrize(
    ("name", "count", "covered"),
    [
        ("plan", 13, 13),
        ("evidence-quality", 1, 1),
        ("export", 4, 3),
        ("export", 4, 4),
        ("suppression", 2, 2),
        ("deletion", 2, 2),
    ],
)
def test_geometry_requires_every_fixed_sensitive_region(
    name: str, count: int, covered: int
) -> None:
    geometry = {
        "root": [0, 0, 10, 10],
        "boxes": [[1, 1, 2, 2]] * covered,
        "count": count,
        "covered": covered,
    }
    assert redaction_rectangles(geometry, geometry, 10, 10, name)
    incomplete = {**geometry, "covered": count - (2 if name == "export" else 1)}
    with pytest.raises(ValueError, match="capture_geometry_refused"):
        redaction_rectangles(incomplete, incomplete, 10, 10, name)
    mismatch = {**geometry, "count": count + 1}
    with pytest.raises(ValueError, match="capture_geometry_refused"):
        redaction_rectangles(mismatch, mismatch, 10, 10, name)


def test_geometry_script_refuses_unstable_or_untrusted_layout() -> None:
    """Exercise only the geometry code with a synthetic DOM substitute."""
    from operator_capture import GEOMETRY

    script = r"""
const geometry = new Function('return (' + process.argv[1] + ')')();
const assert = require('node:assert/strict');
class Element {
  constructor(tag,box,text='') { this.tagName=tag; this.box=box; this.textContent=text;
    this.isConnected=true; this.children=[]; this.parentElement=null; this.position='static';
    this.transform='none'; this.fontSize='16px'; this.textShadow='none'; }
  getBoundingClientRect() { const [left,top,right,bottom]=this.box;
    return {left,top,right,bottom,width:right-left,height:bottom-top}; }
  querySelectorAll() { return this.children; }
}
const textNode={textContent:'synthetic value'};
global.NodeFilter={SHOW_TEXT:4};
global.window={scrollX:10,scrollY:20,visualViewport:{scale:1}};
global.getComputedStyle=e=>({transform:e.transform,filter:'none',perspective:'none',
  position:e.position,fontSize:e.fontSize,textShadow:e.textShadow,webkitTextStrokeWidth:'0px'});
const html=new Element('HTML',[0,0,300,300]);
const root=new Element('DL',[0.2,0.3,100.2,100.3]); root.parentElement=html;
const value=new Element('DD',[20.5,20.5,30.5,30.5],'synthetic value');
const row=new Element('DIV',[20,20,40,40]); row.parentElement=root; value.parentElement=row;
root.__emCaptureSensitive=Object.freeze([value]); root.__emCaptureObserver={};
root.__emCaptureOwnedStyle={isConnected:true};
global.document={documentElement:html,
  createTreeWalker() { let seen=false; return {currentNode:null,nextNode() {
    if(seen)return false; seen=true; this.currentNode=textNode; return true; }}; },
  createRange() {return {selectNodeContents(){},
    getClientRects(){return [value.getBoundingClientRect()];}};}
};
const good=geometry(root);
assert.deepEqual(good,{root:[10.2,20.3,110.2,120.3],
  boxes:[[30.5,40.5,40.5,50.5],[30.5,40.5,40.5,50.5]],count:1,covered:1});
window.visualViewport.scale=2; assert.equal(geometry(root),null); window.visualViewport.scale=1;
window.visualViewport=null; assert.equal(geometry(root),null); window.visualViewport={scale:1};
row.transform='matrix(1,0,0,1,0,0)'; assert.equal(geometry(root),null); row.transform='none';
row.position='sticky'; assert.equal(geometry(root),null); row.position='static';
value.position='fixed'; assert.equal(geometry(root),null); value.position='static';
value.transform='matrix(1,0,0,1,0,0)'; assert.equal(geometry(root),null); value.transform='none';
value.fontSize='64px'; assert.equal(geometry(root),null); value.fontSize='16px';
value.textShadow='1px 1px red'; assert.equal(geometry(root),null); value.textShadow='none';
root.__emCaptureOwnedStyle.isConnected=false; assert.equal(geometry(root),null);
"""
    result = subprocess.run(
        ["node", "-e", script, GEOMETRY], capture_output=True, check=False, timeout=5
    )
    assert result.returncode == 0, result.stderr.decode()


def test_closed_order_and_complete_sessions() -> None:
    assert tuple(images(CORE)) == CORE
    assert tuple(images(PRIVACY)) == PRIVACY
    collector = Collector(CORE)
    with pytest.raises(ValueError, match="capture_order_refused"):
        collector.accept(frame("deletion"))
    collector.accept(frame("plan"))
    with pytest.raises(ValueError, match="capture_order_refused"):
        collector.accept(frame("plan"))
    with pytest.raises(ValueError, match="capture_incomplete"):
        collector.finish()


@pytest.mark.parametrize(
    "change", [{"part": True}, {"parts": 0}, {"data": "private!"}, {"part": 1}, {"extra": "x"}]
)
def test_frame_grammar_refuses_untrusted_content(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Collector(CORE).accept({**frame("plan"), **change})


def test_partial_chunks_cannot_be_completed_or_reordered() -> None:
    encoded = base64.b64encode(image()).decode()
    collector = Collector(CORE)
    collector.accept(
        {"kind": "capture", "name": "plan", "part": 0, "parts": 2, "data": encoded[:4]}
    )
    with pytest.raises(ValueError, match="capture_frame_refused"):
        collector.accept(
            {"kind": "capture", "name": "plan", "part": 0, "parts": 2, "data": encoded[4:]}
        )
    with pytest.raises(ValueError, match="capture_incomplete"):
        collector.finish()


def test_bundle_contains_only_fixed_images_and_nonsecret_metadata(tmp_path: Path) -> None:
    options = {
        "runner_temp": str(tmp_path),
        "head": "a" * 40,
        "checked_out_commit": "b" * 40,
        "tree": "c" * 40,
    }
    save_bundle(images(CORE), images(PRIVACY), **options)
    verify_bundle(**options)
    target = tmp_path / "emailmonitor-synthetic-operator-captures"
    assert {p.name for p in target.iterdir()} == {
        "01-plan.png",
        "02-evidence-quality.png",
        "03-export.png",
        "04-suppression.png",
        "05-deletion.png",
        "manifest.json",
    }
    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["status"] == "pending_visual_privacy_review"
    assert os.stat(target).st_mode & 0o777 == 0o700
    assert all(os.stat(p).st_mode & 0o777 == 0o600 for p in target.iterdir())
    (target / "unexpected.txt").write_text("not allowed")
    with pytest.raises(ValueError, match="capture_bundle_refused"):
        verify_bundle(**options)


def test_bundle_refuses_wrong_session_or_source_before_writing(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        save_bundle(
            images(CORE),
            {},
            runner_temp=str(tmp_path),
            head="a" * 40,
            checked_out_commit="b" * 40,
            tree="c" * 40,
        )
    with pytest.raises(ValueError):
        save_bundle(
            images(CORE),
            images(PRIVACY),
            runner_temp=str(tmp_path),
            head="private",
            checked_out_commit="b" * 40,
            tree="c" * 40,
        )
    assert not list(tmp_path.iterdir())


class FakeLocator:
    def __init__(self, count: int = 1, handle: Any = None) -> None:
        self.value, self.handle = count, handle

    async def count(self) -> int:
        return self.value

    async def element_handle(self) -> Any:
        return self.handle


class FakeHandle:
    def __init__(
        self,
        *,
        shape: bool = True,
        installed: bool = True,
        unchanged: bool = True,
        error: bool = False,
        geometry: str = "valid",
    ) -> None:
        self.shape, self.installed, self.unchanged, self.error = shape, installed, unchanged, error
        self.geometry = geometry
        self.calls: list[str] = []

    async def evaluate(self, source: str, *args: Any) -> Any:
        from operator_capture import GEOMETRY, INSTALL, SHAPE

        if source == SHAPE:
            self.calls.append("shape")
            return self.shape
        if source == INSTALL:
            self.calls.append("install")
            return self.installed
        if source == GEOMETRY:
            self.calls.append("geometry")
            if self.geometry == "missing":
                return None
            end = 2 if self.geometry == "changed" and self.calls.count("geometry") == 2 else 1
            return {
                "root": [0, 0, end, 1],
                "boxes": [[0, 0, 1, 1]] * 13,
                "count": 13,
                "covered": 13,
            }
        self.calls.append("finish")
        return "ok" if self.unchanged else "changed_child"

    async def screenshot(self, **options: Any) -> bytes:
        self.calls.append("screenshot")
        assert options["style"] == style_for("plan")
        assert options["animations"] == "allow" and options["caret"] == "initial"
        assert options["scale"] == "css"
        if self.error:
            raise RuntimeError("synthetic screenshot failure")
        return image(pixel=b"\x00\x89\xab\xcd")


class FakePage:
    url = "https://app.example.test/"

    def __init__(self, handle: FakeHandle, *, regions: int = 1, authenticated: bool = True) -> None:
        self.handle, self.regions, self.authenticated = handle, regions, authenticated

    def get_by_role(self, role: str, **kwargs: Any) -> FakeLocator:
        return FakeLocator(1 if role == "heading" and self.authenticated else 0)

    async def evaluate(self, source: str) -> bool:
        assert "Synthetic tenant 0" in source
        return self.authenticated

    def locator(self, selector: str) -> FakeLocator:
        assert selector == 'dl[aria-label="Plan summary"]'
        return FakeLocator(self.regions, self.handle)


def test_capture_sends_only_after_unchanged_masked_screenshot(capsys: Any) -> None:
    handle = FakeHandle()
    asyncio.run(capture(cast(Page, FakePage(handle)), "plan"))
    value = json.loads(capsys.readouterr().out)
    assert value["kind"] == "capture" and value["name"] == "plan"
    payload = base64.b64decode(value["data"], validate=True)
    length = struct.unpack(">I", payload[33:37])[0]
    assert zlib.decompress(payload[41 : 41 + length]) == b"\x00\x00\x00\x00"
    assert handle.calls == ["shape", "install", "geometry", "screenshot", "geometry", "finish"]
    assert "visibility:hidden!important" in style_for("plan")
    assert "::before" in style_for("plan") and "::backdrop" in style_for("plan")


@pytest.mark.parametrize(
    "case",
    [
        "shape",
        "install",
        "geometry",
        "geometry_changed",
        "mutation",
        "duplicate",
        "session",
        "origin",
        "screenshot",
    ],
)
def test_capture_refuses_and_never_emits_on_missing_or_changed_guard(
    case: str, capsys: Any
) -> None:
    handle = FakeHandle(
        shape=case != "shape",
        installed=case != "install",
        unchanged=case != "mutation",
        error=case == "screenshot",
        geometry="missing"
        if case == "geometry"
        else "changed"
        if case == "geometry_changed"
        else "valid",
    )
    page = FakePage(
        handle, regions=2 if case == "duplicate" else 1, authenticated=case != "session"
    )
    if case == "origin":
        page.url = "https://other.example/"
    with pytest.raises((ValueError, RuntimeError)):
        asyncio.run(capture(cast(Page, page), "plan"))
    assert capsys.readouterr().out == ""
    if case == "screenshot":
        assert handle.calls == ["shape", "install", "geometry", "screenshot", "finish"]
    if case == "install":
        assert handle.calls == ["shape", "install", "finish"]


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        ("observer", "capture_observer_missing"),
        ("detached", "capture_target_detached"),
        ("changed_attribute", "capture_change_attribute"),
        ("changed_text", "capture_change_text"),
        ("changed_child", "capture_change_child"),
        ("changed_style", "capture_change_style"),
        ("state_detached", "capture_state_detached"),
        ("state_focus", "capture_state_focus"),
        ("state_scroll", "capture_state_scroll"),
        ("mask_absent", "capture_mask_absent"),
        ("mask_target", "capture_mask_target"),
        ("mask_values", "capture_mask_values"),
        ("mask_outside", "capture_mask_outside"),
        ("untrusted private text", "capture_mutated"),
        ({"untrusted": "private"}, "capture_mutated"),
    ],
)
def test_finish_diagnostics_are_closed_and_never_emit_images_on_refusal(
    outcome: Any, reason: str, capsys: Any
) -> None:
    class ResultHandle(FakeHandle):
        async def evaluate(self, source: str, *args: Any) -> Any:
            from operator_capture import GEOMETRY

            if source == GEOMETRY:
                return {
                    "root": [0, 0, 1, 1],
                    "boxes": [[0, 0, 1, 1]] * 13,
                    "count": 13,
                    "covered": 13,
                }
            return True if args else outcome

    with pytest.raises(ValueError, match=f"^{reason}$"):
        asyncio.run(capture(cast(Page, FakePage(ResultHandle())), "plan"))
    assert capsys.readouterr().out == ""


def test_embedded_javascript_parses_without_running_browser() -> None:
    from operator_capture import FINISH, GEOMETRY, INSTALL, SHAPE

    for source in (SHAPE, INSTALL, GEOMETRY, FINISH):
        result = subprocess.run(
            ["node", "-e", "new Function('return (' + process.argv[1] + ')')", source],
            capture_output=True,
            check=False,
            timeout=5,
        )
        assert result.returncode == 0


def test_real_browser_regression_scripts_parse_without_launching_browser() -> None:
    from test_operator_capture_pixels import CONTROL, EXPOSE, PIXEL_ORACLE, RESTORE

    for source in (EXPOSE, CONTROL, RESTORE, PIXEL_ORACLE):
        result = subprocess.run(
            ["node", "-e", "new Function('return (' + process.argv[1] + ')')", source],
            capture_output=True,
            check=False,
            timeout=5,
        )
        assert result.returncode == 0


def test_independent_pixel_oracle_detects_sentinel_leak_and_dimension_mismatch() -> None:
    from test_operator_capture_pixels import PIXEL_ORACLE

    script = r"""
const oracle = new Function('return (' + process.argv[1] + ')')();
const assert = require('node:assert/strict');
const pixels = [
  [255,255,255,255,200,0,200,255],
  [255,255,255,255,255,255,255,255],
  [255,255,255,255,0,0,0,255],
  [255,255,255,255,200,0,200,255]
];
global.Blob=class {constructor(parts){this.id=parts[0][0];}};
global.createImageBitmap=async blob=>({id:blob.id,width:blob.id===4?3:2,height:1,close(){}});
global.document={createElement(){let bitmap; return {width:0,height:0,getContext(){return {
  drawImage(value){bitmap=value;}, getImageData(){return {data:pixels[bitmap.id]};}
}}};}};
(async()=>{
  assert.deepEqual(await oracle(['AA==','AQ==','Ag==']),{changed:1,leaked:0});
  assert.deepEqual(await oracle(['AA==','AQ==','Aw==']),{changed:1,leaked:1});
  assert.deepEqual(await oracle(['AQ==','AQ==','Ag==']),{changed:0,leaked:0});
  assert.equal(await oracle(['AA==','AQ==','BA==']),null);
})().catch(()=>{process.exitCode=1;});
"""
    result = subprocess.run(
        ["node", "-e", script, PIXEL_ORACLE], capture_output=True, check=False, timeout=5
    )
    assert result.returncode == 0, result.stderr.decode()


def test_browser_regression_preflight_refuses_proxy_before_network_or_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import test_operator_capture_pixels as regression

    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(os, "environ", {"HTTP_PROXY": "synthetic"})

    def no_namespace_inspection(_: str) -> list[str]:
        raise AssertionError("Proxy refusal must happen first")

    monkeypatch.setattr(os, "listdir", no_namespace_inspection)
    with pytest.raises(RuntimeError, match="Isolated proxy-free nonroot browser required"):
        regression.require_existing_isolation()


def test_partial_bundle_write_is_removed_without_hiding_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = os.open

    def fail_second(path: Any, flags: int, mode: int = 0o777, *args: Any, **kwargs: Any) -> int:
        if str(path).endswith("02-evidence-quality.png"):
            raise OSError("synthetic write failure")
        return original(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", fail_second)
    with pytest.raises(OSError, match="synthetic write failure"):
        save_bundle(
            images(CORE),
            images(PRIVACY),
            runner_temp=str(tmp_path),
            head="a" * 40,
            checked_out_commit="b" * 40,
            tree="c" * 40,
        )
    assert not list(tmp_path.iterdir())


def test_bundle_rejects_symlink_replacement(tmp_path: Path) -> None:
    options = {
        "runner_temp": str(tmp_path),
        "head": "a" * 40,
        "checked_out_commit": "b" * 40,
        "tree": "c" * 40,
    }
    save_bundle(images(CORE), images(PRIVACY), **options)
    target = tmp_path / "emailmonitor-synthetic-operator-captures"
    image_path = target / "01-plan.png"
    image_path.unlink()
    image_path.symlink_to(target / "02-evidence-quality.png")
    with pytest.raises(ValueError, match="capture_bundle_refused"):
        verify_bundle(**options)


def test_fixed_css_hides_outside_and_every_variable_field() -> None:
    from operator_capture import TARGETS

    for name, (selector, masks) in TARGETS.items():
        style = style_for(name)
        assert "body *{visibility:hidden!important;}" in style
        for mask in masks.split(","):
            assert (
                selector + " " + mask.strip() + "{visibility:hidden!important;}" in style
                or selector + " " + mask.strip() + "," in style
            )
            assert selector + " " + mask.strip() + " *" in style
        for pseudo in ("::before", "::after", "::marker", "::backdrop"):
            assert pseudo in style
        assert "background-image:none!important" in style


def test_capture_source_requires_global_uniqueness_and_mutation_guard() -> None:
    from operator_capture import FINISH, SHAPE

    assert "matches.length !== 1" in SHAPE
    assert "document.documentElement" in SHAPE and "MutationObserver" in SHAPE
    assert "shadowRoot" in SHAPE and "getPropertyPriority('visibility')" in SHAPE
    assert "document.activeElement === state[3]" in FINISH
    assert "scrollLeft === item[1]" in FINISH and "scrollTop === item[2]" in FINISH


def test_existing_ci_entry_guards_and_limits_remain_in_source() -> None:
    root = Path(__file__).resolve().parents[3]
    host = (root / "scripts/isolation/run_operator_ui_acceptance.py").read_text()
    guest = (root / "scripts/isolation/operator_ui_acceptance.py").read_text()
    assert 'os.environ.get("GITHUB_ACTIONS") != "true"' in host
    assert 'os.environ.get("EM_REQUIRE_OPERATOR_UI") != "true"' in host
    assert "time.monotonic() + 180" in host and "identifier > 512" in host
    assert '"--network=none"' in host and '"--cap-drop=ALL"' in host
    assert "chromium_sandbox=True" in guest and "range(100)" in guest


@pytest.mark.parametrize(
    "reason",
    [
        "capture_checkpoint_refused",
        "capture_origin_refused",
        "capture_session_refused",
        "capture_region_refused",
        "capture_shape_refused",
        "capture_mask_install_refused",
        "capture_geometry_refused",
        "capture_mutated",
        "capture_observer_missing",
        "capture_target_detached",
        "capture_change_attribute",
        "capture_change_text",
        "capture_change_child",
        "capture_change_style",
        "capture_state_detached",
        "capture_state_focus",
        "capture_state_scroll",
        "capture_mask_absent",
        "capture_mask_target",
        "capture_mask_values",
        "capture_mask_outside",
        "capture_png_refused",
    ],
)
def test_capture_failure_reason_is_fixed_and_never_echoes_arbitrary_content(reason: str) -> None:
    from operator_ui_protocol import DiagnosticFrame, failure_reason

    assert failure_reason(ValueError(reason)) == reason
    assert failure_reason(ValueError(reason + " private")) == "unknown"
    assert failure_reason(RuntimeError(reason)) == "unknown"
    assert (
        DiagnosticFrame.model_validate(
            {"kind": "failure", "stage": "keyword_plan", "error": "ValueError", "reason": reason}
        ).reason
        == reason
    )


def test_plan_dom_guard_with_synthetic_node_substitutes() -> None:
    """Exercise actual JavaScript guard without launching a browser or services."""
    from operator_capture import FINISH, SHAPE

    script = r"""
const shape = new Function('return (' + process.argv[1] + ')')();
const finish = new Function('return (' + process.argv[2] + ')')();
const assert = require('node:assert/strict');
class E {
  constructor(tag, text='', children=[]) {
    this.tagName=tag; this.textContent=text; this.children=children;
    this.childNodes=children.length ? children : [{nodeType:3,textContent:text}];
    this.shadowRoot=null; this.isConnected=true; this.scrollLeft=0; this.scrollTop=0;
    this.style={getPropertyPriority: () => ''}; this.visible=true; this.inline=false;
  }
  querySelectorAll() { return this.children.flatMap(e => [e,...e.querySelectorAll('*')]); }
  contains(other) { return this === other || this.querySelectorAll('*').includes(other); }
  hasAttribute(name) { return name === 'style' && this.inline; }
  getAttribute() { return null; }
  getBoundingClientRect() { return {width:this.visible ? 10:0,height:10}; }
}
const labels = ['Source identity','Planned start URL','Original query','Effective query',
  'Requested article limit','Effective article cap','Maximum result pages','Author selection',
  'Browser work','Authored PDF fixtures','Policy version at planning',
  'Source-reported total at planning','Article URLs listed at planning'];
let records = [];
class Observer {
  constructor(callback) { this.callback=callback; }
  observe() {}
  disconnect() {}
  takeRecords() { const copy=records; records=[]; return copy; }
}
global.MutationObserver=Observer;
global.getComputedStyle=e => ({visibility:e.visible ? 'visible':'hidden'});
global.window={scrollX:0,scrollY:0,scrollTo(x,y){this.scrollX=x;this.scrollY=y;}};
function setup() {
  records=[];
  const rows=labels.map(label => new E('DIV','',[new E('DT',label),new E('DD','synthetic')]));
  const root=new E('DL','',rows);
  const heading=new E('H2','Synthetic tenant 0');
  const body=new E('BODY','',[heading,root]);
  const html=new E('HTML','',[body]);
  global.document={body,documentElement:html,activeElement:new E('BUTTON','go'),styleSheets:[],
    querySelectorAll(selector) {
      if (selector === '.workspace-heading h2') return [heading];
      if (selector === 'a' || selector === 'dialog[open]') return [];
      return [root];
    }};
  return {root,rows,body,heading};
}
const config={name:'plan',style:'fixed'};
function applyStyle(root, masks, fault='') {
  const outside=document.body.querySelectorAll('*').filter(e => !root.contains(e));
  for (const e of [...outside,...masks]) e.visible=false;
  if (fault === 'values') masks[0].visible=true;
  if (fault === 'target') root.visible=false;
  if (fault === 'outside') outside[0].visible=true;
  const style=new E('STYLE','fixed'); style.nodeType=1;
  style.parentNode=document.documentElement;
  style.sheet={cssRules:[{cssText:'fixed rule'}]};
  style.remove=()=>{style.isConnected=false;style.parentNode=null;
    for (const e of [...outside,...masks]) e.visible=true; root.visible=true;};
  root.__emCaptureOwnedStyle=style;
  root.__emCaptureStyleRules=JSON.stringify(['fixed rule']);
  root.__emCaptureObserver.callback([{type:'childList',target:document.documentElement,
    addedNodes:[style],removedNodes:[]}]);
}
{
  const {root,rows}=setup(); assert.equal(shape(root,config),true);
  applyStyle(root,rows.map(r => r.children[1]));
  rows[0].scrollTop=9; window.scrollY=7;
  assert.equal(finish(root),'ok');
  assert.equal(rows[0].scrollTop,0); assert.equal(window.scrollY,0);
}
{
  const {root,rows}=setup(); assert.equal(shape(root,config),true);
  applyStyle(root,rows.map(r => r.children[1]));
  const transient=new E('STYLE','fixed'); transient.nodeType=1;
  records.push({type:'childList',target:document.documentElement,addedNodes:[transient],removedNodes:[]},
    {type:'childList',target:document.documentElement,addedNodes:[],removedNodes:[transient]});
  assert.equal(finish(root),'ok'); // Delayed records are verified while owned masking remains.
  assert.equal(root.__emCaptureOwnedStyle,undefined);
}
{
  const {root,rows}=setup(); assert.equal(shape(root,config),true);
  applyStyle(root,rows.map(r => r.children[1]));
  root.__emCaptureOwnedStyle.remove(); assert.equal(finish(root),'mask_absent');
}
{
  const {root,rows}=setup(); assert.equal(shape(root,config),true);
  applyStyle(root,rows.map(r => r.children[1]));
  const owned=root.__emCaptureOwnedStyle;
  records.push({type:'childList',target:document.documentElement,addedNodes:[],removedNodes:[owned]},
    {type:'childList',target:document.documentElement,addedNodes:[owned],removedNodes:[]});
  assert.equal(finish(root),'changed_style');
}
{
  const {root,rows}=setup(); assert.equal(shape(root,config),true);
  applyStyle(root,rows.map(r => r.children[1]));
  root.__emCaptureOwnedStyle.sheet.cssRules[0].cssText='altered';
  assert.equal(finish(root),'mask_absent');
}
{
  const {root,rows}=setup(); rows[0].children[0].textContent='unexpected';
  assert.equal(shape(root,config),false);
}
{
  const {root,rows}=setup(); rows[0].children[1].visible=false;
  assert.equal(shape(root,config),false);
}
{
  const {root,body}=setup(); body.children.push(new E('IMG'));
  assert.equal(shape(root,config),false);
}
{
  const {root,rows}=setup(); rows[0].children[1].inline=true;
  assert.equal(shape(root,config),false);
}
{
  const {root}=setup(); assert.equal(shape(root,config),true);
  records.push({type:'childList',target:document.body,addedNodes:[],removedNodes:[]});
  assert.equal(finish(root),'changed_child');
}
{
  const {root}=setup(); assert.equal(shape(root,config),true);
  assert.equal(finish(root),'mask_absent'); // No observed masking means no accepted image.
}
{
  const {root,rows}=setup(); assert.equal(shape(root,config),true);
  applyStyle(root,rows.map(r => r.children[1]),'values');
  assert.equal(finish(root),'mask_values'); // A visible masked value is refused.
}
for (const fault of ['target','outside']) {
  const {root,rows}=setup(); assert.equal(shape(root,config),true);
  applyStyle(root,rows.map(r => r.children[1]),fault);
  assert.equal(finish(root),'mask_'+fault);
}
for (const [type,kind] of [['attributes','attribute'],['characterData','text']]) {
  const {root}=setup(); assert.equal(shape(root,config),true);
  records.push({type,target:document.body});
  assert.equal(finish(root),'changed_'+kind);
}
{
  const {root}=setup(); assert.equal(shape(root,config),true);
  const style=new E('STYLE','unexpected'); style.nodeType=1;
  records.push({type:'childList',target:document.documentElement,addedNodes:[style],removedNodes:[]});
  assert.equal(finish(root),'changed_style');
}
{
  const {root}=setup(); assert.equal(shape(root,config),true);
  document.activeElement=new E('BUTTON','other'); assert.equal(finish(root),'state_focus');
}
{
  const {root}=setup(); assert.equal(finish(root),'observer');
}
{
  const {root}=setup(); assert.equal(shape(root,config),true);
  root.isConnected=false; assert.equal(finish(root),'detached');
}
{
  const {root,rows}=setup(); assert.equal(shape(root,config),true);
  rows[0].isConnected=false; assert.equal(finish(root),'state_detached');
}
{
  const {root,rows}=setup(); assert.equal(shape(root,config),true);
  applyStyle(root,rows.map(r => r.children[1]));
  window.scrollY=7; const restore=window.scrollTo; window.scrollTo=()=>{};
  assert.equal(finish(root),'state_scroll'); window.scrollTo=restore; window.scrollY=0;
}
"""
    result = subprocess.run(
        ["node", "-e", script, SHAPE, FINISH], capture_output=True, check=False, timeout=5
    )
    assert result.returncode == 0, result.stderr.decode()


def test_owned_mask_remains_during_delayed_style_records_and_is_removed() -> None:
    """Exercise the fixed JS with synthetic DOM timing, without running Chromium."""
    import ast

    from operator_capture import FINISH, INSTALL, SHAPE

    source = ast.parse(Path(__file__).read_text())
    fixture = next(
        node
        for node in source.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_plan_dom_guard_with_synthetic_node_substitutes"
    )
    script = next(
        ast.literal_eval(node.value)
        for node in fixture.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "script" for target in node.targets)
    )
    script += r"""
const install = new Function('return (' + process.argv[3] + ')')();
function installFixture(root,rows,failValues=false) {
  const masks=rows.map(r => r.children[1]);
  const outside=document.body.querySelectorAll('*').filter(e => !root.contains(e));
  document.createElement=()=>{
    const style=new E('STYLE'); style.nodeType=1;
    style.sheet={cssRules:[{cssText:'fixed rule'}]};
    style.remove=()=>{style.isConnected=false;style.parentNode=null;
      for (const e of [...outside,...masks]) e.visible=true;};
    return style;
  };
  document.documentElement.append=style=>{
    style.parentNode=document.documentElement;
    for (const e of [...outside,...masks]) e.visible=false;
    if (failValues) masks[0].visible=true;
    records.push({type:'childList',target:document.documentElement,addedNodes:[style],removedNodes:[]});
  };
}
{
  const {root,rows}=setup(); assert.equal(shape(root,config),true);
  installFixture(root,rows); assert.equal(install(root,'fixed'),true);
  const owned=root.__emCaptureOwnedStyle;
  const transient=new E('STYLE','fixed'); transient.nodeType=1;
  records.push({type:'childList',target:document.documentElement,addedNodes:[transient],removedNodes:[]},
    {type:'childList',target:document.documentElement,addedNodes:[],removedNodes:[transient]});
  assert.equal(finish(root),'ok'); assert.equal(owned.isConnected,false);
  assert.ok(rows.every(row => row.children[1].visible));
}
{
  const {root,rows}=setup(); assert.equal(shape(root,config),true);
  installFixture(root,rows,true); assert.equal(install(root,'fixed'),false);
  const owned=root.__emCaptureOwnedStyle;
  assert.equal(finish(root),'mask_values'); assert.equal(owned.isConnected,false);
}
"""
    result = subprocess.run(
        ["node", "-e", script, SHAPE, FINISH, INSTALL],
        capture_output=True,
        check=False,
        timeout=8,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_capture_bundle_is_written_only_after_two_receipts_and_final_checks() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / "scripts/isolation/test_operator_ui_acceptance.py").read_text()
    assert source.index('core_capture = evidence.pop("_capture_images", None)') < source.index(
        "validate_operator_core(evidence"
    )
    assert source.index(
        'privacy_capture = privacy_evidence.pop("_capture_images", None)'
    ) < source.index("validate_operator_aggregate(")
    assert source.rindex('assert observed["complete"] is True') < source.rindex("save_bundle(")
    workflow = (root / ".github/workflows/operator-ui.yml").read_text()
    assert workflow.index("Verify fixed synthetic screenshot bundle") < workflow.index(
        "Retain synthetic business crops for privacy review"
    )
    assert "retention-days: 1" in workflow and "if-no-files-found: error" in workflow
    assert "EM_CAPTURE_HEAD_SHA:" in workflow


def test_capture_module_is_present_in_both_exact_guest_build_contexts() -> None:
    root = Path(__file__).resolve().parents[3]
    expected = "scripts/isolation/operator_capture.py"
    for path in (
        "scripts/isolation/Dockerfile.operator-ui",
        "scripts/isolation/Dockerfile.installed-operator-ui",
    ):
        assert "COPY " + expected + " ./operator_capture.py" in (root / path).read_text()
    for path in (
        ".dockerignore",
        "scripts/isolation/Dockerfile.installed-operator-ui.dockerignore",
    ):
        assert "!" + expected in (root / path).read_text().splitlines()
    regression = "scripts/isolation/test_operator_capture_pixels.py"
    assert "!" + regression in (root / ".dockerignore").read_text().splitlines()
    assert (
        "COPY " + regression + " ./test_operator_capture_pixels.py"
        in (root / "scripts/isolation/Dockerfile.operator-ui").read_text()
    )


def test_other_crop_guards_with_synthetic_node_substitutes() -> None:
    """Run every non-plan shape and refusal branch in a synthetic JavaScript DOM."""
    from operator_capture import FINISH, SHAPE

    script = r"""
const shape = new Function('return (' + process.argv[1] + ')')();
const finish = new Function('return (' + process.argv[2] + ')')();
const assert = require('node:assert/strict');
class E {
  constructor(tag,text='',children=[]) {
    this.tagName=tag; this.textContent=text; this.children=children;
    this.childNodes=children.length ? children : [{nodeType:3,textContent:text}];
    this.shadowRoot=null; this.isConnected=true; this.scrollLeft=0; this.scrollTop=0;
    this.style={getPropertyPriority: () => ''}; this.visible=true; this.inline=false;
  }
  querySelectorAll() { return this.children.flatMap(e => [e,...e.querySelectorAll('*')]); }
  contains(other) { return this === other || this.querySelectorAll('*').includes(other); }
  hasAttribute(name) { return name === 'style' && this.inline; }
  getAttribute(name) { return name === 'aria-labelledby' ? this.label : null; }
  getBoundingClientRect() { return {width:this.visible ? 10:0,height:10}; }
}
class Observer {
  constructor(callback) { this.callback=callback; }
  observe() {}
  disconnect() {}
  takeRecords() { return []; }
}
global.MutationObserver=Observer;
global.getComputedStyle=e => ({visibility:e.visible ? 'visible':'hidden'});
global.window={scrollX:0,scrollY:0,scrollTo(x,y){this.scrollX=x;this.scrollY=y;}};
function setup(kind) {
  const last = 'Missing affiliations remain unobserved, not confirmed absent. ' +
    'Accepting or correcting an author-email association does not resolve ' +
    'affiliation uncertainty or change the retained parser outcome.';
  let root, dialog, dialogs=[];
  if (kind === 'evidence-quality') {
    root=new E('SECTION','',[new E('H4','Article observation quality'),
      new E('P','Retained parser outcome: synthetic.'),
      new E('P','Parser-specific reasons are not recorded for this route.'),new E('P',last)]);
    dialog=new E('DIALOG','',[root]); dialog.label='evidence-title'; dialogs=[dialog];
  } else if (kind === 'export') {
    root=new E('SECTION','',[new E('H4','Current eligible preview'),new E('P','sensitive'),
      new E('P','counts'),new E('UL'),new E('P','notice'),
      new E('BUTTON','Create asynchronous export')]);
  } else {
    const title=kind === 'suppression' ? 'Suppress observed contact' : 'Stage job deletion';
    const confirm=kind === 'suppression' ? 'Confirm suppress observed contact' :
      'Confirm stage job deletion';
    root=new E('DIALOG','',[new E('H2',title),new E('P','synthetic identifier'),
      new E('P','synthetic detail'),new E('DIV','',[new E('BUTTON','Keep unchanged'),
      new E('BUTTON',confirm)])]);
    root.label='confirm-title'; dialog=root; dialogs=[root];
  }
  const heading=new E('H2','Synthetic tenant 0');
  const body=new E('BODY','',[heading,dialog || root]);
  const html=new E('HTML','',[body]);
  global.document={body,documentElement:html,activeElement:new E('BUTTON','go'),styleSheets:[],
    querySelectorAll(selector) {
      if (selector === '.workspace-heading h2') return [heading];
      if (selector === 'a') return [];
      if (selector === 'dialog[open]') return dialogs;
      return [root];
    }};
  return {root,heading};
}
for (const kind of ['evidence-quality','export','suppression','deletion']) {
  const {root}=setup(kind); assert.equal(shape(root,{name:kind,style:'fixed'}),true);
  const masks=kind === 'evidence-quality' ? [root.children[1]] :
    kind === 'export' ? [root.children[1],root.children[2],root.children[3],root.children[4]] :
    [root.children[1],root.children[2]];
  const outside=document.body.querySelectorAll('*').filter(e => !root.contains(e));
  for (const e of [...outside,...masks]) e.visible=false;
  const style=new E('STYLE','fixed'); style.nodeType=1;
  style.parentNode=document.documentElement;
  style.sheet={cssRules:[{cssText:'fixed rule'}]};
  style.remove=()=>{style.isConnected=false;style.parentNode=null;
    for (const e of [...outside,...masks]) e.visible=true;};
  root.__emCaptureOwnedStyle=style;
  root.__emCaptureStyleRules=JSON.stringify(['fixed rule']);
  root.__emCaptureObserver.callback([{type:'childList',target:document.documentElement,
    addedNodes:[style],removedNodes:[]}]);
  assert.equal(finish(root),'ok');
}
{
  const {root}=setup('export'); root.children.push(new E('P','unexpected'));
  assert.equal(shape(root,{name:'export',style:'fixed'}),false);
}
{
  const {root}=setup('suppression'); root.children[3].children[1].textContent='other';
  assert.equal(shape(root,{name:'suppression',style:'fixed'}),false);
}
{
  const {root}=setup('deletion'); root.children[1].visible=false;
  assert.equal(shape(root,{name:'deletion',style:'fixed'}),false);
}
{
  const {root}=setup('evidence-quality'); root.shadowRoot={};
  assert.equal(shape(root,{name:'evidence-quality',style:'fixed'}),false);
}
{
  const {root,heading}=setup('export'); heading.textContent='other organization';
  assert.equal(shape(root,{name:'export',style:'fixed'}),false);
}
{
  const {root}=setup('export'); document.activeElement=new E('INPUT');
  assert.equal(shape(root,{name:'export',style:'fixed'}),false);
}
{
  const {root}=setup('export'); document.styleSheets=[{get cssRules(){throw Error('blocked');}}];
  assert.equal(shape(root,{name:'export',style:'fixed'}),false);
}
"""
    result = subprocess.run(
        ["node", "-e", script, SHAPE, FINISH], capture_output=True, check=False, timeout=5
    )
    assert result.returncode == 0, result.stderr.decode()


def test_failure_reports_do_not_include_unredacted_pixels(tmp_path: Path) -> None:
    """Even verbose failure locals must not expose in-memory screenshot bytes."""
    import sys

    marker = bytes.fromhex("53454e54494e454c5f505249564154455f504958454c53")
    path = tmp_path / "test_capture_trace.py"
    path.write_text(
        """import asyncio
import operator_capture as oc
import test_operator_capture_pixels as browser

SECRET = bytes.fromhex("53454e54494e454c5f505249564154455f504958454c53")

class Handle:
    def __init__(self): self.calls = 0
    async def evaluate(self, source, *args):
        if source == oc.SHAPE or source == oc.INSTALL: return True
        if source == oc.FINISH: return "ok"
        if source == oc.GEOMETRY:
            self.calls += 1
            if self.calls == 2: raise ValueError(SECRET)
            return {"root": [0,0,1,1], "boxes": [[0,0,1,1]] * 13, "count": 13, "covered": 13}
    async def screenshot(self, **kwargs): return SECRET
class Locator:
    async def count(self): return 1
    async def element_handle(self): return Handle()
class Page:
    url = "https://app.example.test/"
    async def evaluate(self, *args): return True
    def locator(self, *args): return Locator()

def test_capture_failure():
    asyncio.run(oc.capture(Page(), "plan"))

def test_oracle_failure(monkeypatch):
    async def exercise():
        unredacted_image = SECRET
        raise RuntimeError(unredacted_image)
    monkeypatch.setattr(browser, "require_existing_isolation", lambda: None)
    monkeypatch.setattr(browser, "exercise", exercise)
    browser.test_actual_sandboxed_chromium_redacts_temporarily_exposed_synthetic_values()
"""
    )
    environment = os.environ.copy()
    root = Path(__file__).resolve().parents[3]
    scripts = str(root / "scripts" / "isolation")
    backend = str(root / "services" / "backend" / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        (scripts, backend, environment.get("PYTHONPATH", ""))
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--showlocals", "--tb=long", str(path)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    assert result.returncode == 1
    assert marker not in result.stdout
    assert base64.b64encode(marker) not in result.stdout
    assert b"capture_mutated" in result.stdout
    assert b"Synthetic Chromium regression refused" in result.stdout


def test_browser_oracle_control_flow_tracebacks_hide_raw_pixels(tmp_path: Path) -> None:
    import sys

    marker = bytes.fromhex("53454e54494e454c5f505249564154455f504958454c53")
    path = tmp_path / "oracle_control_flow.py"
    path.write_text(
        """import asyncio
import traceback
import test_operator_capture_pixels as browser

browser.require_existing_isolation = lambda: None
for kind in (asyncio.CancelledError, KeyboardInterrupt, SystemExit, RuntimeError):
    async def exercise():
        unredacted_image = bytes.fromhex("53454e54494e454c5f505249564154455f504958454c53")
        raise kind(unredacted_image)
    browser.exercise = exercise
    try:
        browser.test_actual_sandboxed_chromium_redacts_temporarily_exposed_synthetic_values()
    except BaseException as error:
        assert type(error) is kind
        detail = traceback.TracebackException.from_exception(error, capture_locals=True)
        print("".join(detail.format()))
    else:
        raise AssertionError("Expected a failure")
"""
    )
    environment = os.environ.copy()
    root = Path(__file__).resolve().parents[3]
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(root / "scripts" / "isolation"), str(root / "services" / "backend" / "src"))
    )
    result = subprocess.run(
        [sys.executable, str(path)],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    assert marker not in result.stdout
    assert base64.b64encode(marker) not in result.stdout

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
    def __init__(self, *, shape: bool = True, unchanged: bool = True, error: bool = False) -> None:
        self.shape, self.unchanged, self.error = shape, unchanged, error
        self.calls: list[str] = []

    async def evaluate(self, source: str, *args: Any) -> bool:
        self.calls.append("shape" if args else "finish")
        return self.shape if args else self.unchanged

    async def screenshot(self, **options: Any) -> bytes:
        self.calls.append("screenshot")
        assert options["style"] == style_for("plan")
        assert options["animations"] == "allow" and options["caret"] == "initial"
        if self.error:
            raise RuntimeError("synthetic screenshot failure")
        return image()


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
    assert handle.calls == ["shape", "screenshot", "finish"]
    assert "visibility:hidden!important" in style_for("plan")
    assert "::before" in style_for("plan") and "::backdrop" in style_for("plan")


@pytest.mark.parametrize(
    "case", ["shape", "mutation", "duplicate", "session", "origin", "screenshot"]
)
def test_capture_refuses_and_never_emits_on_missing_or_changed_guard(
    case: str, capsys: Any
) -> None:
    handle = FakeHandle(
        shape=case != "shape", unchanged=case != "mutation", error=case == "screenshot"
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
        assert handle.calls == ["shape", "screenshot", "finish"]


def test_embedded_javascript_parses_without_running_browser() -> None:
    from operator_capture import FINISH, SHAPE

    for source in (SHAPE, FINISH):
        result = subprocess.run(
            ["node", "-e", "new Function('return (' + process.argv[1] + ')')", source],
            capture_output=True,
            check=False,
            timeout=5,
        )
        assert result.returncode == 0


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
        "capture_mutated",
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
function applyStyle(root, masks, allHidden=true) {
  const outside=document.body.querySelectorAll('*').filter(e => !root.contains(e));
  for (const e of [...outside,...masks]) e.visible=false;
  if (!allHidden) masks[0].visible=true;
  const style=new E('STYLE','fixed'); style.nodeType=1;
  root.__emCaptureObserver.callback([{type:'childList',target:document.documentElement,
    addedNodes:[style],removedNodes:[]}]);
  for (const e of [...outside,...masks]) e.visible=true;
}
{
  const {root,rows}=setup(); assert.equal(shape(root,config),true);
  applyStyle(root,rows.map(r => r.children[1]));
  rows[0].scrollTop=9; window.scrollY=7;
  assert.equal(finish(root),true);
  assert.equal(rows[0].scrollTop,0); assert.equal(window.scrollY,0);
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
  assert.equal(finish(root),false);
}
{
  const {root}=setup(); assert.equal(shape(root,config),true);
  assert.equal(finish(root),false); // No observed masking means no accepted image.
}
{
  const {root,rows}=setup(); assert.equal(shape(root,config),true);
  applyStyle(root,rows.map(r => r.children[1]),false);
  assert.equal(finish(root),false); // A visible masked value is refused.
}
{
  const {root}=setup(); assert.equal(shape(root,config),true);
  document.activeElement=new E('BUTTON','other'); assert.equal(finish(root),false);
}
"""
    result = subprocess.run(
        ["node", "-e", script, SHAPE, FINISH], capture_output=True, check=False, timeout=5
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
  root.__emCaptureObserver.callback([{type:'childList',target:document.documentElement,
    addedNodes:[style],removedNodes:[]}]);
  for (const e of [...outside,...masks]) e.visible=true;
  assert.equal(finish(root),true);
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

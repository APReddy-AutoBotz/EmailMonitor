"""Pinned authored WebSocket lifecycle probes; no browser or network acceptance."""

import ast
import asyncio
import copy
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from browser_acceptance import (
    BOUNDARY_FAILURE_SNAPSHOT,
    MARKER_SNAPSHOT,
    boundary_failure_evidence,
    boundary_readiness,
)
from playwright._impl._driver import compute_driver_executable
from playwright._impl._network import WebSocketRoute as ImplWebSocketRoute
from playwright.async_api import Error
from run_browser_acceptance import BOUNDARY_PAGE, PAGE

ROOT = Path(__file__).resolve().parents[3]
DOCUMENT = {
    "document_url": "fixture",
    "marker_count": 1,
    "marker_expected": True,
    "boundary_ready": "absent",
    "boundary_state": "object",
}
OBSERVED = {"status": "observed", **DOCUMENT}


@pytest.mark.parametrize("url", ["fixture", "error_document", "other"])
@pytest.mark.parametrize("count", [0, 1, 2])
@pytest.mark.parametrize("ready", ["true", "false", "absent", "other"])
def test_only_closed_current_document_evidence_is_emitted(url: str, count: int, ready: str) -> None:
    value = {
        **DOCUMENT,
        "document_url": url,
        "marker_count": count,
        "marker_expected": count == 1,
        "boundary_ready": ready,
    }
    pending, document = boundary_failure_evidence(
        {"pending": {"websocket": "pending"}, "document": value}
    )
    assert json.loads(pending) == {"pending_task_evidence": {"websocket": "pending"}}
    assert json.loads(document) == {"boundary_document_evidence": {"status": "observed", **value}}
    assert len(document) < 256


@pytest.mark.parametrize(
    "change",
    [
        {"document_url": "private-secret"},
        {"document_url": None},
        {"marker_count": True},
        {"marker_count": -1},
        {"marker_count": 3},
        {"marker_expected": 1},
        {"marker_expected": "private"},
        {"marker_count": 2},
        {"boundary_ready": "private"},
        {"boundary_state": []},
        {"extra": "private token/cookie"},
    ],
)
def test_hostile_document_data_is_never_reflected(change: dict[str, object]) -> None:
    value = {**DOCUMENT, **change}
    result = boundary_failure_evidence({"pending": None, "document": value})
    assert json.loads(result[1]) == {"boundary_document_evidence": {"status": "malformed"}}
    assert "private" not in "".join(result)


def test_document_shape_and_builtin_types_are_strict() -> None:
    class Mapping(dict[str, object]):
        pass

    class Category(str):
        pass

    values: tuple[object, ...] = (
        None,
        [],
        {},
        Mapping(DOCUMENT),
        {**DOCUMENT, "document_url": Category("fixture")},
        {Category(key): value for key, value in DOCUMENT.items()},
    )
    for value in values:
        result = boundary_failure_evidence({"pending": {}, "document": value})
        assert json.loads(result[1]) == {"boundary_document_evidence": {"status": "malformed"}}
    for name in DOCUMENT:
        result = boundary_failure_evidence(
            {
                "pending": {},
                "document": {key: value for key, value in DOCUMENT.items() if key != name},
            }
        )
        assert json.loads(result[1]) == {"boundary_document_evidence": {"status": "malformed"}}
    assert json.loads(boundary_failure_evidence(None)[1]) == {
        "boundary_document_evidence": {"status": "unavailable"}
    }
    for value in ({"extra": "secret"}, [], Mapping({"pending": {}, "document": DOCUMENT})):
        assert json.loads(boundary_failure_evidence(value)[1]) == {
            "boundary_document_evidence": {"status": "malformed"}
        }
    for pending in (
        Mapping({"websocket": "pending"}),
        {Category("websocket"): "pending"},
        {"websocket": Category("pending")},
        {"secret": "pending"},
    ):
        result = boundary_failure_evidence({"pending": pending, "document": DOCUMENT})
        assert json.loads(result[0]) == {"pending_task_evidence": "unavailable"}


@pytest.mark.parametrize(
    "failure", [RuntimeError("authored channel refusal"), Error("authored driver refusal")]
)
def test_actual_pinned_python_close_suppresses_channel_error_without_delivery(
    failure: Exception,
) -> None:
    """Return from close is not an acknowledgment that a DOM event was delivered."""
    calls: list[tuple[str, object, dict[str, object]]] = []

    class Channel:
        async def send(self, method: str, timeout: object, params: dict[str, object]) -> None:
            calls.append((method, timeout, params))
            raise failure

    socket = cast(ImplWebSocketRoute, SimpleNamespace(_channel=Channel()))
    assert (
        asyncio.run(ImplWebSocketRoute.close(socket, code=1008, reason="synthetic boundary"))
        is None
    )
    assert calls == [
        ("closePage", None, {"code": 1008, "reason": "synthetic boundary", "wasClean": True})
    ]


def test_actual_pinned_python_close_does_not_suppress_cancellation() -> None:
    cancelled = asyncio.CancelledError()

    class Channel:
        async def send(self, *args: object) -> None:
            raise cancelled

    socket = cast(ImplWebSocketRoute, SimpleNamespace(_channel=Channel()))
    with pytest.raises(asyncio.CancelledError) as caught:
        asyncio.run(ImplWebSocketRoute.close(socket, code=1008, reason="synthetic boundary"))
    assert caught.value is cancelled


def test_pinned_driver_and_mock_distinguish_close_return_from_fixture_event(tmp_path: Path) -> None:
    """Actual pinned methods plus actual authored fixture, with inert document inputs."""
    node, cli = compute_driver_executable()
    bundle = Path(cli).parent / "lib" / "coreBundle.js"
    fixture = BOUNDARY_PAGE.decode().split("<script>", 1)[1].split("</script>", 1)[0]
    script = tmp_path / "websocket-evidence.cjs"
    script.write_text(r"""
const fs=require('fs'),path=require('path'),Module=require('module'),vm=require('vm');
const file=process.argv[2], inputs=JSON.parse(fs.readFileSync(0,'utf8'));
const owned=new Module(file,module);owned.filename=file;
owned.paths=Module._nodeModulePaths(path.dirname(file));
owned._compile(fs.readFileSync(file,'utf8')+
 '\ninit_webSocketRouteDispatcher(); module.exports.ownedRoute=WebSocketRouteDispatcher;'+
 'module.exports.ownedMock=source11;\n',file);
const Route=owned.exports.ownedRoute;
class OwnedCloseEvent extends Event {
 constructor(type,options){super(type,options);this.code=options.code;this.reason=options.reason;this.wasClean=options.wasClean;}
}
async function probe(mode){
 const creates=[], marker={textContent:'synthetic marker'}, reveal={};
 let nativeCalls=0, settlement=false, settledValues=[];
 const sockets=[];
 class OwnedPromise extends Promise {
  static allSettled(values){
   return super.allSettled(values).then(result=>{settledValues=result;return result;});
  }
 }
 class NoNetwork {constructor(){nativeCalls++;throw Error('network must remain unused');}}
 class OwnedURL extends URL {}
 OwnedURL.createObjectURL=()=> 'blob:authored-only';
 const world={Promise:OwnedPromise,EventTarget,Event,CloseEvent:OwnedCloseEvent,MessageEvent,
  URL:OwnedURL,Uint8Array,
  crypto:require('crypto').webcrypto,WebSocket:NoNetwork,Blob,
  __pwWebSocketBinding:message=>{if(message.type==='onCreate') creates.push(message);},
  document:{baseURI:'https://synthetic.publisher.example/tooltip.html',
   URL:'https://synthetic.publisher.example/tooltip.html',
   querySelectorAll:s=>s==='#marker'?[marker]:[],
   querySelector:s=>s==='#reveal'?reveal:marker,
   createElement:tag=>({tag,click(){}}),
   body:{append(node){if(node.onerror)node.onerror(new Event('error'));}}},
  location:{href:'https://synthetic.publisher.example/tooltip.html'},
  navigator:{serviceWorker:{register:()=>Promise.reject(Error('authored denied'))}},
  fetch:(url,options)=>options||url.includes('denied.fixture')?
   Promise.reject(Error('authored denied')):
   Promise.resolve({text:async()=> 'synthetic marker'}),
  XMLHttpRequest:class{open(){}send(){this.onerror(new Event('error'));}},
  window:{open(){}},module:{exports:{}},
 };
 world.window.document=world.document;world.globalThis=world;
 const context=vm.createContext(world);
 vm.runInContext(owned.exports.ownedMock,context);
 vm.runInContext('(module.exports.inject())(globalThis)',context);
 const Mock=world.WebSocket;
 world.WebSocket=class extends Mock {constructor(...args){super(...args);sockets.push(this);}};
 vm.runInContext(inputs.fixture,context);
 const completion=reveal.onclick().then(()=>{settlement=true;});
 await Promise.resolve();await Promise.resolve();
 // Test-only ownership: this array was populated by the inert VM constructor.
 // No observer or constructor wrapper is installed in the real browser harness.
 const before=JSON.parse(JSON.stringify(vm.runInContext(inputs.snapshot,context)()));
 const beforeState=sockets[0].readyState;
 const delivered=[];
 sockets[0].addEventListener('close',event=>delivered.push(event));
 sockets[0].addEventListener('error',event=>delivered.push(event));
 const message={id:creates[0].id,type:'closePage',code:1008,
  reason:'synthetic boundary',wasClean:true};
 const owner={_frame:{evaluateExpression:async(progress,expression)=>{
  if(mode==='reject')throw Error('authored execution context refusal');
  return vm.runInContext(expression,context);
 }}};
 const returned=await Route.prototype._evaluateAPIRequest.call(owner,{},message);
 if(mode==='deliver') await completion;
 else {await Promise.resolve();await Promise.resolve();}
 const after=JSON.parse(JSON.stringify(vm.runInContext(inputs.snapshot,context)()));
 const ready=world.boundaryReady===true, settled=settlement;
 const afterState=sockets[0].readyState, terminalEvents=delivered.length;
 let originalEvent=settledValues.some(row=>row.value===delivered[0] && delivered.length===1);
 if(mode==='reject'){
  // Pure probe cleanup after the failed-delivery snapshot. Never emitted by harness.
  const event=new Event('error');sockets[0].dispatchEvent(event);await completion;
  originalEvent=settledValues.some(row=>row.value===event);
 }
 for(const created of creates)world.__pwWebSocketDispatch({...message,id:created.id});
 await completion;
 return {before,after,beforeState,afterState,terminalEvents,ready,settlementAtSnapshot:settled,
  returnedUndefined:returned===undefined,nativeCalls,originalEvent};
}
(async()=>process.stdout.write(JSON.stringify({version:owned.exports.getPlaywrightVersion(),
 deliver:await probe('deliver'),reject:await probe('reject')})))().catch(()=>{process.exitCode=1;});
""")
    result = subprocess.run(
        [node, str(script), str(bundle)],
        input=json.dumps({"fixture": fixture, "snapshot": BOUNDARY_FAILURE_SNAPSHOT}),
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    evidence = json.loads(result.stdout)
    assert evidence["version"] == "1.63.0"
    for mode in ("deliver", "reject"):
        row = evidence[mode]
        assert row["before"]["document"] == DOCUMENT
        assert row["before"]["pending"]["websocket"] == "pending"
        assert row["beforeState"] == 0
        assert row["returnedUndefined"] is True and row["nativeCalls"] == 0
        assert row["originalEvent"] is True
    assert evidence["deliver"]["after"]["document"] == {**DOCUMENT, "boundary_ready": "true"}
    assert evidence["deliver"]["after"]["pending"]["websocket"] == "fulfilled"
    assert evidence["deliver"]["afterState"] == 3 and evidence["deliver"]["terminalEvents"] == 1
    assert evidence["deliver"]["ready"] is True
    assert evidence["deliver"]["settlementAtSnapshot"] is True
    assert evidence["reject"]["after"]["document"] == DOCUMENT
    assert evidence["reject"]["after"]["pending"]["websocket"] == "pending"
    assert evidence["reject"]["afterState"] == 0 and evidence["reject"]["terminalEvents"] == 0
    assert evidence["reject"]["ready"] is False
    assert evidence["reject"]["settlementAtSnapshot"] is False
    assert "execution context" not in result.stdout


def readiness_probe() -> Any:
    tree = ast.parse((ROOT / "scripts/isolation/browser_acceptance.py").read_text())
    block = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        and any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "boundary_readiness"
            for statement in node.body
            for child in ast.walk(statement)
        )
    )
    assert (
        ast.unparse(block.body[0]) == "await boundary_readiness(page.wait_for_function("
        "'globalThis.boundaryReady === true', timeout=10000))"
    )
    assert sum(isinstance(node, ast.Await) for line in block.body for node in ast.walk(line)) == 1
    assert (
        isinstance(block.handlers[0].body[-1], ast.Raise) and block.handlers[0].body[-1].exc is None
    )
    function = ast.parse("async def probe():\n    pass\n")
    entry = cast(ast.AsyncFunctionDef, function.body[0])
    entry.body = [copy.deepcopy(block)]
    return compile(ast.fix_missing_locations(function), "owned-readiness-probe", "exec")


@pytest.mark.parametrize(
    "primary", [None, TimeoutError("private readiness timeout"), Error("private driver failure")]
)
@pytest.mark.parametrize("secondary", ["", "evaluate", "cancel", "serialize", "output"])
def test_failure_snapshot_never_changes_readiness_or_primary(
    primary: BaseException | None, secondary: str
) -> None:
    calls: list[str] = []
    messages: list[str] = []

    class Page:
        async def wait_for_function(self, expression: str, *, timeout: int) -> None:
            assert expression == "globalThis.boundaryReady === true" and timeout == 10000
            calls.append("readiness")
            if primary is not None:
                raise primary

        async def evaluate(self, expression: str) -> object:
            assert expression == BOUNDARY_FAILURE_SNAPSHOT
            calls.append("snapshot")
            if secondary == "evaluate":
                raise RuntimeError("private evaluation")
            if secondary == "cancel":
                raise asyncio.CancelledError()
            return {"pending": {"websocket": "pending"}, "document": DOCUMENT}

    def format_evidence(value: object) -> tuple[str, str]:
        calls.append("format")
        if secondary == "serialize":
            raise ValueError("private serialization")
        return boundary_failure_evidence(value)

    def emit(value: str) -> None:
        if secondary == "output":
            raise OSError("private output")
        messages.append(value)

    namespace: dict[str, Any] = {
        "page": Page(),
        "boundary_readiness": boundary_readiness,
        "BOUNDARY_FAILURE_SNAPSHOT": BOUNDARY_FAILURE_SNAPSHOT,
        "asyncio": asyncio,
        "Error": Error,
        "boundary_failure_evidence": format_evidence,
        "trace_stage": emit,
    }
    exec(readiness_probe(), namespace)
    if primary is None:
        asyncio.run(namespace["probe"]())
        assert calls == ["readiness"] and messages == []
    else:
        with pytest.raises(type(primary)) as caught:
            asyncio.run(namespace["probe"]())
        assert caught.value is primary
        assert "private" not in "".join(messages)
        if secondary == "":
            assert calls == ["readiness", "snapshot", "format"]
            assert json.loads(messages[-1]) == {"boundary_document_evidence": OBSERVED}


def test_snapshot_uses_original_one_second_budget_and_cancels_owned_wait() -> None:
    primary = TimeoutError("authored readiness failure")
    budgets: list[int] = []
    cancelled: list[bool] = []

    class Page:
        async def wait_for_function(self, *args: object, **kwargs: object) -> None:
            raise primary

        async def evaluate(self, expression: str) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

    async def bounded(awaitable: Any, *, timeout: int) -> Any:
        budgets.append(timeout)
        return await asyncio.wait_for(awaitable, timeout=0.01)

    namespace: dict[str, Any] = {
        "page": Page(),
        "boundary_readiness": boundary_readiness,
        "BOUNDARY_FAILURE_SNAPSHOT": BOUNDARY_FAILURE_SNAPSHOT,
        "asyncio": SimpleNamespace(wait_for=bounded),
        "Error": Error,
        "boundary_failure_evidence": boundary_failure_evidence,
        "trace_stage": lambda _: None,
    }
    exec(readiness_probe(), namespace)
    with pytest.raises(TimeoutError) as caught:
        asyncio.run(namespace["probe"]())
    assert caught.value is primary and budgets == [1] and cancelled == [True]


def test_other_browser_behavior_and_every_success_await_remain_unchanged() -> None:
    source = ast.parse((ROOT / "scripts/isolation/browser_acceptance.py").read_text())
    main = next(
        node
        for node in source.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "main"
    )
    block = next(
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Try)
        and any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "boundary_readiness"
            for statement in node.body
            for child in ast.walk(statement)
        )
    )
    # Only the existing failure-only handler is excluded; the complete successful
    # main path and every other failure path are the reviewed ninth baseline.
    block.handlers = []
    assert (
        hashlib.sha256(ast.dump(main, include_attributes=False).encode()).hexdigest()
        == "5302a2b0ecebfae9d71c42ef519044daae2204cfc5402ea3f6d811792dbf8b2b"
    )
    helpers = ast.Module(
        body=[
            node
            for node in source.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name in {"refuse_websocket", "boundary_readiness"}
        ],
        type_ignores=[],
    )
    assert (
        hashlib.sha256(ast.dump(helpers, include_attributes=False).encode()).hexdigest()
        == "91bef1403f04e460e0d23aea69d50c3d1db95f4c7a42797e72d7db4d63dbdba5"
    )


def test_exact_acquired_fixture_bytes_and_every_historical_digest_fence_are_preserved() -> None:
    from emailmonitor.extraction.fixture import BROWSER_ACQUISITION_DIGEST

    assert hashlib.sha256(PAGE).hexdigest() == BROWSER_ACQUISITION_DIGEST
    assert BROWSER_ACQUISITION_DIGEST == (
        "7c26b49fe73a02899f77c88ebea70abb1f256399b66ed9c3b41eab12b587f9e3"
    )
    assert hashlib.sha256(BOUNDARY_PAGE).hexdigest() == (
        "c4ff7c9c1a29bfdc82c61a0049c2b1c2f12034081455db8198df481795712782"
    )
    assert hashlib.sha256(
        (ROOT / "scripts/isolation/run_browser_acceptance.py").read_bytes()
    ).hexdigest() == ("8c6e96db13d27be37c443f918a62416185c0f7cd589e9d0aa471aa00809b5fd5")
    for version in (
        "0005_article_observations",
        "0007_progress",
        "0011_lifecycle",
        "0012_xml_pipeline",
        "0013_provider_journey",
    ):
        source = (ROOT / "services/backend/migrations/versions" / (version + ".sql")).read_text()
        assert source.count(BROWSER_ACQUISITION_DIGEST) == 1
    assert BOUNDARY_FAILURE_SNAPSHOT == (
        "() => ({pending: globalThis.boundaryPending, document: (" + MARKER_SNAPSHOT + ")()})"
    )

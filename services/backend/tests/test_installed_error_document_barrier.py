"""Authored event ordering only; no browser/network or hosted acceptance claim."""

import asyncio
import itertools
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from installed_operator_redirects import (
    ERROR_DOCUMENT,
    ErrorDocumentObserver,
    LoginRedirects,
    observe_error_documents,
)
from playwright._impl._driver import compute_driver_executable
from test_installed_operator_harness import API, ISSUER, arm_login, bound_redirects


def observations(
    coordinator: LoginRedirects, original: object, target: str
) -> dict[str, Callable[[], None]]:
    sequence = coordinator.redirects
    return {
        "failure": lambda: coordinator.observe_failure(
            target=target,
            method="GET",
            main_frame=True,
            redirected_from=original,
            failure="net::ERR_CONNECTION_REFUSED",
        ),
        "cdp_commit": lambda: coordinator.observe_commit(
            frame="main",
            loader=f"loader-{sequence}",
            url=ERROR_DOCUMENT,
            target=target,
        ),
        "cdp_dcl": lambda: coordinator.observe_lifecycle(
            frame="main",
            loader=f"loader-{sequence}",
            name="DOMContentLoaded",
        ),
        "public_commit": lambda: coordinator.observe_public_commit(
            sequence=sequence,
            main_frame=True,
            url=ERROR_DOCUMENT,
        ),
        "public_dcl": lambda: coordinator.observe_public_loaded(sequence=sequence),
    }


ORDERS = [
    order
    for order in itertools.permutations(
        ("failure", "cdp_commit", "cdp_dcl", "public_commit", "public_dcl")
    )
    if order.index("cdp_commit") < order.index("cdp_dcl")
    and order.index("public_commit") < order.index("public_dcl")
]


@pytest.mark.parametrize("order", ORDERS)
def test_all_five_observations_are_required_in_either_stream_order(order: tuple[str, ...]) -> None:
    async def exercise() -> None:
        coordinator = bound_redirects()
        coordinator.begin()
        original = object()
        target = arm_login(coordinator, original)["location"]
        waiting = asyncio.create_task(coordinator.next_target())
        actions = observations(coordinator, original, target)
        for index, name in enumerate(order):
            assert not waiting.done()
            actions[name]()
            await asyncio.sleep(0)
            assert waiting.done() == (index == 4)
        assert await waiting == target

    asyncio.run(exercise())


@pytest.mark.parametrize("missing", tuple(ORDERS[0]))
def test_either_missing_stream_or_request_cannot_release(missing: str) -> None:
    async def exercise() -> None:
        coordinator = bound_redirects()
        coordinator.begin()
        original = object()
        target = arm_login(coordinator, original)["location"]
        for name, action in observations(coordinator, original, target).items():
            if name != missing:
                action()
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await coordinator.next_target()
        assert coordinator.navigations == 0
        with pytest.raises(RuntimeError):
            coordinator.receipt()

    asyncio.run(exercise())


@pytest.mark.parametrize("stream", ["cdp", "public"])
def test_lifecycle_before_its_commit_is_not_reused(stream: str) -> None:
    async def exercise() -> None:
        coordinator = bound_redirects()
        coordinator.begin()
        original = object()
        target = arm_login(coordinator, original)["location"]
        actions = observations(coordinator, original, target)
        actions[stream + "_dcl"]()
        for name, action in actions.items():
            if name != stream + "_dcl":
                action()
        waiting = asyncio.create_task(coordinator.next_target())
        await asyncio.sleep(0)
        assert not waiting.done()
        actions[stream + "_dcl"]()
        assert await waiting == target

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "field,value",
    [
        ("frame", "other"),
        ("loader", ""),
        ("loader", "l" * 129),
        ("url", API),
        ("target", ISSUER + "/authorize?unowned"),
    ],
)
def test_wrong_cdp_commit_identity_latches(field: str, value: str) -> None:
    coordinator = bound_redirects()
    coordinator.begin()
    target = arm_login(coordinator, object())["location"]
    values = {"frame": "main", "loader": "loader", "url": ERROR_DOCUMENT, "target": target}
    values[field] = value
    with pytest.raises(RuntimeError):
        coordinator.observe_commit(**values)
    assert coordinator.failed


@pytest.mark.parametrize(
    "event", ["cdp_commit", "cdp_dcl", "public_commit", "public_dcl", "failure"]
)
def test_duplicate_observations_latch(event: str) -> None:
    coordinator = bound_redirects()
    coordinator.begin()
    original = object()
    target = arm_login(coordinator, original)["location"]
    actions = observations(coordinator, original, target)
    for action in actions.values():
        action()
    with pytest.raises(RuntimeError):
        actions[event]()
    assert coordinator.failed


@pytest.mark.parametrize(
    "field,value", [("sequence", 0), ("sequence", 2), ("main_frame", False), ("url", API)]
)
def test_public_commit_is_owned_main_frame_sequence(field: str, value: object) -> None:
    coordinator = bound_redirects()
    coordinator.begin()
    arm_login(coordinator, object())
    values: dict[str, Any] = {"sequence": 1, "main_frame": True, "url": ERROR_DOCUMENT}
    values[field] = value
    with pytest.raises(RuntimeError):
        coordinator.observe_public_commit(**values)
    assert coordinator.failed


@pytest.mark.parametrize("event", ["commit", "lifecycle", "public"])
def test_old_loader_or_sequence_cannot_satisfy_next_hop(event: str) -> None:
    async def exercise() -> None:
        coordinator = bound_redirects()
        coordinator.begin()
        original = object()
        target = arm_login(coordinator, original)["location"]
        for action in observations(coordinator, original, target).values():
            action()
        assert await coordinator.next_target() == target
        callback = API + "/auth/complete?state=" + "s" * 43 + "&code=" + "c" * 32
        coordinator.arm(
            object(),
            source=target,
            method="GET",
            main_frame=True,
            redirected_from=None,
            status=303,
            headers={"location": callback},
        )
        with pytest.raises(RuntimeError):
            if event == "commit":
                coordinator.observe_commit(
                    frame="main", loader="loader-1", url=ERROR_DOCUMENT, target=callback
                )
            elif event == "lifecycle":
                coordinator.observe_lifecycle(
                    frame="main", loader="loader-1", name="DOMContentLoaded"
                )
            else:
                coordinator.observe_public_loaded(sequence=1)
        assert coordinator.failed and coordinator.navigations == 1

    asyncio.run(exercise())


def test_unrelated_lifecycle_and_prearm_events_never_release() -> None:
    coordinator = bound_redirects()
    coordinator.observe_commit(frame="main", loader="initial", url=API, target="")
    coordinator.begin()
    arm_login(coordinator, object())
    coordinator.observe_lifecycle(frame="other", loader="unrelated", name="DOMContentLoaded")
    coordinator.observe_lifecycle(frame="main", loader="loader-1", name="load")
    assert not coordinator.failed and coordinator.navigations == 0


class Events:
    def __init__(self) -> None:
        self.listeners: dict[str, list[Callable[..., None]]] = {}
        self.removed: list[str] = []
        self.fail_remove = False
        self.main_frame = SimpleNamespace(url=ERROR_DOCUMENT)

    def on(self, name: str, callback: Callable[..., None]) -> None:
        self.listeners.setdefault(name, []).append(callback)

    def remove_listener(self, name: str, callback: Callable[..., None]) -> None:
        self.removed.append(name)
        self.listeners[name].remove(callback)
        if self.fail_remove:
            raise RuntimeError("authored removal failure")

    def emit(self, name: str, *values: Any) -> None:
        for callback in list(self.listeners.get(name, [])):
            callback(*values)


class Session(Events):
    def __init__(self, failure: str = "") -> None:
        super().__init__()
        self.failure = failure
        self.commands: list[str] = []
        self.detaches = 0

    async def send(self, name: str, parameters: Any = None) -> dict[str, Any]:
        assert set(self.listeners) == {"Page.frameNavigated", "Page.lifecycleEvent"}
        self.commands.append(name)
        if self.failure == name:
            raise RuntimeError("authored setup failure")
        return {"frameTree": {"frame": {"id": "main"}}}

    async def detach(self) -> None:
        self.detaches += 1
        if self.failure == "detach":
            raise RuntimeError("authored detach failure")


class Context:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def new_cdp_session(self, page: Any) -> Session:
        return self.session


def observer_scope(session: Session, page: Events, coordinator: LoginRedirects) -> Any:
    return observe_error_documents(Context(session), page, coordinator, lambda error: None)  # type: ignore[arg-type]


def arm_observer(
    observer: ErrorDocumentObserver, coordinator: LoginRedirects, original: object
) -> str:
    from test_installed_operator_harness import login_headers

    headers = login_headers()
    observer.arm(
        original,
        source=API + "/api/v1/auth/start",
        method="GET",
        main_frame=True,
        redirected_from=None,
        status=303,
        headers=headers,
    )
    return headers["location"]


def test_real_listener_adapter_waits_for_both_streams_and_removes_only_owned() -> None:
    async def exercise() -> None:
        coordinator, session, page = LoginRedirects(API, ISSUER), Session(), Events()

        def foreign() -> None:
            pass

        page.on("domcontentloaded", foreign)
        async with observer_scope(session, page, coordinator) as observer:
            coordinator.begin()
            original = object()
            target = arm_observer(observer, coordinator, original)
            old_callback = page.listeners["framenavigated"][0]
            observations(coordinator, original, target)["failure"]()
            page.emit("framenavigated", page.main_frame)
            page.emit("domcontentloaded")
            waiting = asyncio.create_task(observer.next_target())
            await asyncio.sleep(0)
            assert not waiting.done()
            session.emit(
                "Page.frameNavigated",
                {
                    "frame": {
                        "id": "main",
                        "loaderId": "loader-1",
                        "url": ERROR_DOCUMENT,
                        "unreachableUrl": target,
                    }
                },
            )
            session.emit(
                "Page.lifecycleEvent",
                {"frameId": "main", "loaderId": "loader-1", "name": "DOMContentLoaded"},
            )
            assert await waiting == target
            assert page.listeners["domcontentloaded"] == [foreign]
            assert not page.listeners["framenavigated"]
            old_callback(page.main_frame)
            assert coordinator.failed
        assert session.commands == [
            "Page.enable",
            "Page.getFrameTree",
            "Page.setLifecycleEventsEnabled",
        ]
        assert session.detaches == 1
        assert not any(session.listeners.values())

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "failure", ["Page.enable", "Page.getFrameTree", "Page.setLifecycleEventsEnabled"]
)
def test_partial_observer_setup_detaches_and_removes_listeners(failure: str) -> None:
    async def exercise() -> None:
        coordinator, session, page = LoginRedirects(API, ISSUER), Session(failure), Events()
        with pytest.raises(RuntimeError, match="authored setup failure"):
            async with observer_scope(session, page, coordinator):
                pytest.fail("partial observer entered")
        assert coordinator.failed and session.detaches == 1
        assert not any(session.listeners.values())

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["page_remove", "session_remove", "detach"])
@pytest.mark.parametrize("primary", [False, True])
def test_cleanup_attempts_are_independent_and_preserve_primary(failure: str, primary: bool) -> None:
    async def exercise() -> None:
        coordinator, session, page = LoginRedirects(API, ISSUER), Session(failure), Events()
        marker = ValueError("authored primary")
        with pytest.raises(ValueError if primary else RuntimeError) as captured:
            async with observer_scope(session, page, coordinator) as observer:
                coordinator.begin()
                arm_observer(observer, coordinator, object())
                page.fail_remove = failure == "page_remove"
                session.fail_remove = failure == "session_remove"
                if primary:
                    raise marker
        if primary:
            assert captured.value is marker
            assert marker.__notes__ == ["Owned observer cleanup also failed"]
        assert coordinator.failed and session.detaches == 1
        assert page.removed == ["framenavigated", "domcontentloaded"]
        assert session.removed == ["Page.frameNavigated", "Page.lifecycleEvent"]
        assert not any(page.listeners.values()) and not any(session.listeners.values())
        await observer.close()
        assert session.detaches == 1
        with pytest.raises(RuntimeError):
            coordinator.receipt()

    asyncio.run(exercise())


def test_expiry_closes_pending_observer_without_success() -> None:
    async def exercise() -> None:
        coordinator, session, page = LoginRedirects(API, ISSUER), Session(), Events()
        with pytest.raises(TimeoutError):
            async with observer_scope(session, page, coordinator) as observer:
                coordinator.begin()
                arm_observer(observer, coordinator, object())
                async with asyncio.timeout(0.01):
                    await observer.next_target()
        assert coordinator.failed and coordinator.navigations == 0 and session.detaches == 1
        assert not any(page.listeners.values()) and not any(session.listeners.values())

    asyncio.run(exercise())


def test_pinned_playwright_prior_error_commit_can_interrupt_fresh_goto(tmp_path: Path) -> None:
    """Exercise actual pinned gotoImpl, with authored events and no browser/network."""
    node, cli = compute_driver_executable()
    bundle = Path(cli).parent / "lib" / "coreBundle.js"
    script = tmp_path / "authored-lifecycle.cjs"
    script.write_text(r"""
const fs = require('fs'), path = require('path'), Module = require('module');
const {EventEmitter} = require('events');
const file = process.argv[2];
const owned = new Module(file, module);
owned.filename = file;
owned.paths = Module._nodeModulePaths(path.dirname(file));
owned._compile(fs.readFileSync(file, 'utf8') + '\nmodule.exports.__ownedFrame = Frame;\n', file);
const Frame = owned.exports.__ownedFrame;
const target = 'https://127.0.0.1:4444/auth/complete';
const event = id => ({url:target, newDocument:{documentId:id,
  request:{_finalRequest:()=>({response:async()=>({status:200})})}}});
async function probe(late) {
  const frame = new EventEmitter();
  frame._firedLifecycleEvents = new Set(['domcontentloaded']);
  frame._page = {extraHTTPHeaders:()=>[], delegate:{navigateFrame:async()=>{
    if(late) frame.emit(Frame.Events.InternalNavigation,event('prior-error'));
    frame.emit(Frame.Events.InternalNavigation,event('callback'));
    return {newDocumentId:'callback'};
  }}};
  if(!late) frame.emit(Frame.Events.InternalNavigation,event('prior-error'));
  try {
    const response = await Frame.prototype.gotoImpl.call(frame,
      {log(){},race:p=>p}, target, {waitUntil:'domcontentloaded'});
    return {status:response.status};
  } catch(error) {
    return {error_class:error.name,
      document_mismatch:error.message ===
        `Navigation to "${target}" is interrupted by another navigation to "${target}"`};
  }
}
(async()=>process.stdout.write(JSON.stringify({version:owned.exports.getPlaywrightVersion(),
  late:await probe(true), settled:await probe(false)})))();
""")
    result = subprocess.run(
        [node, str(script), str(bundle)], check=True, capture_output=True, text=True, timeout=5
    )
    assert json.loads(result.stdout) == {
        "version": "1.63.0",
        "late": {"error_class": "Error", "document_mismatch": True},
        "settled": {"status": 200},
    }


def test_successful_observer_cleanup_is_idempotent_and_four_loaders_are_bounded() -> None:
    from test_installed_operator_harness import synthetic_login

    async def exercise() -> None:
        for _ in range(2):
            coordinator, session, page = LoginRedirects(API, ISSUER), Session(), Events()
            async with observer_scope(session, page, coordinator) as observer:
                await synthetic_login(coordinator)
                await synthetic_login(coordinator)
            await observer.close()
            assert session.detaches == 1 and len(coordinator._loaders) == 4
            assert not any(session.listeners.values())
            assert coordinator.receipt()["explicit_redirect_navigations"] == 4

    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["session_remove", "detach"])
def test_completed_login_receipt_is_refused_if_observer_cleanup_fails(failure: str) -> None:
    from test_installed_operator_harness import synthetic_login

    async def exercise() -> None:
        coordinator, session, page = LoginRedirects(API, ISSUER), Session(failure), Events()
        with pytest.raises(RuntimeError, match="Owned observer cleanup failed"):
            async with observer_scope(session, page, coordinator):
                await synthetic_login(coordinator)
                await synthetic_login(coordinator)
                session.fail_remove = failure == "session_remove"
        assert coordinator.failed and session.detaches == 1
        with pytest.raises(RuntimeError):
            coordinator.receipt()

    asyncio.run(exercise())


@pytest.mark.parametrize("partial", ["Page.frameNavigated", "Page.lifecycleEvent"])
def test_partially_registered_observer_listener_is_owned_and_rolled_back(partial: str) -> None:
    class PartialSession(Session):
        def on(self, name: str, callback: Callable[..., None]) -> None:
            super().on(name, callback)
            if name == partial:
                raise RuntimeError("authored partial registration")

    async def exercise() -> None:
        coordinator, session, page = LoginRedirects(API, ISSUER), PartialSession(), Events()
        with pytest.raises(RuntimeError, match="authored partial registration"):
            async with observer_scope(session, page, coordinator):
                pytest.fail("partial registration entered")
        assert coordinator.failed and session.detaches == 1
        assert not any(session.listeners.values())

    asyncio.run(exercise())


@pytest.mark.parametrize("partial", ["framenavigated", "domcontentloaded"])
def test_partially_registered_hop_listener_cannot_authorize_navigation(partial: str) -> None:
    class PartialPage(Events):
        def on(self, name: str, callback: Callable[..., None]) -> None:
            super().on(name, callback)
            if name == partial:
                raise RuntimeError("authored partial hop registration")

    async def exercise() -> None:
        coordinator, session, page = LoginRedirects(API, ISSUER), Session(), PartialPage()
        with pytest.raises(RuntimeError, match="authored partial hop registration"):
            async with observer_scope(session, page, coordinator) as observer:
                coordinator.begin()
                arm_observer(observer, coordinator, object())
        assert coordinator.failed and coordinator.navigations == 0 and session.detaches == 1
        assert not any(page.listeners.values()) and not any(session.listeners.values())

    asyncio.run(exercise())


def test_observer_setup_and_detach_are_finite_without_changing_login_budget() -> None:
    root = Path(__file__).resolve().parents[3]
    guest = (root / "scripts/isolation/installed_operator_browser.py").read_text()
    login = guest.split("async def login()", 1)[1].split('checkpoint("assets_session")', 1)[0]
    assert login.count("asyncio.timeout(10)") == 1
    assert login.count("await page.goto(") == 2
    assert login.count("await observer.next_target()") == 2
    assert "while " not in login and "for " not in login
    helper = (root / "scripts/isolation/installed_operator_redirects.py").read_text()
    assert "async with asyncio.timeout(10):" in helper
    assert "async with asyncio.timeout(5):" in helper
    assert guest.index("await observers.aclose()") < guest.index("await context.close()")

"""Synthetic pre-cleanup failure evidence; no browser or CI guard is changed."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import operator_ui_acceptance as guest
import pytest
from operator_ui_protocol import BrowserFailureTrace, DiagnosticFrame
from playwright.async_api import Error, Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (RuntimeError("private"), "python_runtime"),
        (TimeoutError("private"), "python_timeout"),
        (PlaywrightTimeoutError("private"), "playwright_timeout"),
        (Error("private"), "playwright_error"),
        (AssertionError("private"), "assertion"),
        (ValueError("private"), "value_error"),
        (OSError("private"), "other"),
    ],
)
def test_exception_categories_never_use_messages(error: Exception, expected: str) -> None:
    assert guest.browser_exception_class(error) == expected


def test_only_owned_source_coordinate_and_closed_function_are_returned() -> None:
    namespace: dict[str, Any] = {}
    exec(
        compile(
            "def select_index():\n    raise RuntimeError('private')\n",
            "/app/operator_ui_acceptance.py",
            "exec",
        ),
        namespace,
    )
    with pytest.raises(RuntimeError) as caught:
        namespace["select_index"]()
    assert guest.browser_source(caught.value) == ("select_index", 2)
    with pytest.raises(RuntimeError) as external:
        raise RuntimeError("private")
    assert guest.browser_source(external.value) == ("other", None)


@pytest.mark.parametrize("cleanup_replaces", [False, True])
def test_capture_precedes_cleanup_and_preserves_original_exception(cleanup_replaces: bool) -> None:
    original = RuntimeError("private original")
    cleanup_error = ValueError("private cleanup")
    browser = SimpleNamespace(is_connected=lambda: True)
    page = SimpleNamespace(is_closed=lambda: False)
    receiver = cast(asyncio.Task[Any], SimpleNamespace(done=lambda: False))
    channel = cast(guest.Channel, SimpleNamespace(admitted=2))
    capture = guest.BrowserFailureCapture(receiver, channel)
    capture.browser, capture.page = browser, page
    cleanup_seen = False

    class Owner:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_: object) -> None:
            nonlocal cleanup_seen
            cleanup_seen = True
            assert capture.snapshot is not None
            browser.is_connected = lambda: False
            page.is_closed = lambda: True
            if cleanup_replaces:
                raise cleanup_error

    async def scenario() -> None:
        async with Owner(), guest.capture_browser_failure(capture):
            raise original

    with pytest.raises(ValueError if cleanup_replaces else RuntimeError) as caught:
        asyncio.run(scenario())
    assert cleanup_seen
    assert caught.value is (cleanup_error if cleanup_replaces else original)
    snapshot = capture.result(cast(Exception, caught.value))
    assert snapshot is not None
    assert snapshot.exception == "python_runtime"
    assert snapshot.browser_connected is True and snapshot.page_closed is False
    assert snapshot.receiver_done is False and snapshot.admitted == 2
    assert snapshot.cleanup_replaced is cleanup_replaces
    assert "private" not in snapshot.model_dump_json()


def test_cause_is_classified_without_its_value() -> None:
    receiver = cast(asyncio.Task[Any], SimpleNamespace(done=lambda: True))
    channel = cast(guest.Channel, SimpleNamespace(admitted=0))
    capture = guest.BrowserFailureCapture(receiver, channel)
    try:
        try:
            raise ValueError("private inner")
        except ValueError as inner:
            raise RuntimeError("private outer") from inner
    except RuntimeError as outer:
        capture.record(outer)
        trace = capture.result(outer)
    assert trace is not None and trace.cause == "value_error"
    assert trace.browser_connected is None and trace.page_closed is None
    assert "private" not in trace.model_dump_json()


def test_real_select_helper_records_failing_keyboard_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = RuntimeError("private synthetic failure")
    receiver = cast(asyncio.Task[Any], SimpleNamespace(done=lambda: False))
    channel = cast(guest.Channel, SimpleNamespace(admitted=0))
    capture = guest.BrowserFailureCapture(receiver, channel)
    keyboard = SimpleNamespace(press=AsyncMock(side_effect=original))
    page = cast(Page, SimpleNamespace(keyboard=keyboard))
    target = cast(Locator, object())
    monkeypatch.setattr(guest, "focus", AsyncMock())

    async def scenario() -> None:
        async with guest.capture_browser_failure(capture):
            await guest.select_index(page, target, 2)

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(scenario())
    assert caught.value is original
    keyboard.press.assert_awaited_once_with("Home")
    snapshot = capture.result(original)
    assert snapshot is not None and snapshot.source_function == "select_index"
    assert snapshot.source_line is not None
    source = Path(guest.__file__).read_text().splitlines()
    assert source[snapshot.source_line - 1].strip() == 'await page.keyboard.press("Home")'


def test_failed_capture_does_not_replace_original(monkeypatch: pytest.MonkeyPatch) -> None:
    original = RuntimeError("private original")
    receiver = cast(asyncio.Task[Any], SimpleNamespace(done=lambda: False))
    channel = cast(guest.Channel, SimpleNamespace(admitted=0))
    capture = guest.BrowserFailureCapture(receiver, channel)
    monkeypatch.setattr(
        capture, "record", lambda _: (_ for _ in ()).throw(ValueError("diagnostic"))
    )

    async def scenario() -> None:
        async with guest.capture_browser_failure(capture):
            raise original

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(scenario())
    assert caught.value is original and capture.result(original) is None


def test_no_snapshot_after_success() -> None:
    receiver = cast(asyncio.Task[Any], SimpleNamespace(done=lambda: False))
    channel = cast(guest.Channel, SimpleNamespace(admitted=0))
    capture = guest.BrowserFailureCapture(receiver, channel)

    async def scenario() -> None:
        async with guest.capture_browser_failure(capture):
            pass

    asyncio.run(scenario())
    assert capture.snapshot is None


@pytest.mark.parametrize(
    "changes",
    [
        {"exception": "private"},
        {"cause": "private"},
        {"source_function": "private"},
        {"source_line": 10001},
        {"browser_connected": "true"},
        {"admitted": 17},
        {"cleanup_replaced": 1},
        {"private": "not allowed"},
    ],
)
def test_failure_trace_refuses_unlisted_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BrowserFailureTrace.model_validate(
            {
                "exception": "python_runtime",
                "cause": "none",
                "source_function": "main",
                "source_line": 1,
                "browser_connected": True,
                "page_closed": False,
                "receiver_done": False,
                "admitted": 0,
                "cleanup_replaced": False,
                **changes,
            }
        )


def test_failure_trace_cannot_be_attached_to_a_stage() -> None:
    trace = BrowserFailureTrace(
        exception="python_runtime",
        cause="none",
        source_function="main",
        source_line=1,
        browser_connected=True,
        page_closed=False,
        receiver_done=False,
        admitted=0,
        cleanup_replaced=False,
    )
    with pytest.raises(ValidationError):
        DiagnosticFrame(kind="stage", stage="sandbox", browser_failure_trace=trace)


def test_capture_exits_before_playwright_context_and_sandbox_is_unchanged() -> None:
    path = Path(__file__).resolve().parents[3] / "scripts/isolation/operator_ui_acceptance.py"
    module = ast.parse(path.read_text())
    main = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "main"
    )
    contexts = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.AsyncWith)
        and [ast.unparse(item.context_expr) for item in node.items]
        == ["async_playwright()", "capture_browser_failure(browser_failure_capture)"]
    ]
    assert len(contexts) == 1
    launch = next(
        node
        for node in ast.walk(contexts[0])
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "playwright.chromium.launch"
    )
    assert any(
        item.arg == "chromium_sandbox"
        and isinstance(item.value, ast.Constant)
        and item.value.value is True
        for item in launch.keywords
    )
    source = path.read_text()
    assert "page.set_default_timeout(10000)" in source
    assert 'page.goto("chrome://sandbox", wait_until="domcontentloaded")' in source
    assert 'if "--no-sandbox" in command["arguments"]' in source

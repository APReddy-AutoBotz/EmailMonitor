"""Closed failure-only marker diagnostics; no actual browser acceptance claim."""

import ast
import asyncio
import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from browser_acceptance import MARKER_SNAPSHOT, URL, marker_failure_message, marker_snapshot_summary
from playwright.async_api import Error, Frame, Page

ROOT = Path(__file__).resolve().parents[3]
OBSERVED = {
    "document_url": "fixture",
    "marker_count": 1,
    "marker_expected": True,
    "boundary_ready": "true",
    "boundary_state": "object",
}


@pytest.mark.parametrize("category", ["fixture", "error_document", "other"])
@pytest.mark.parametrize("count", [0, 1, 2])
def test_marker_snapshot_accepts_only_closed_observations(category: str, count: int) -> None:
    value = {
        **OBSERVED,
        "document_url": category,
        "marker_count": count,
        "marker_expected": count == 1,
    }
    assert marker_snapshot_summary(value) == {"status": "observed", **value}
    assert len(json.dumps(marker_snapshot_summary(value))) < 256


@pytest.mark.parametrize(
    "change",
    [
        {"document_url": "https://private.example/?secret=credential"},
        {"document_url": 1},
        {"marker_count": True},
        {"marker_count": -1},
        {"marker_count": 3},
        {"marker_count": 1.0},
        {"marker_count": 2, "marker_expected": True},
        {"marker_expected": "private marker text"},
        {"boundary_ready": "private source content"},
        {"boundary_ready": True},
        {"boundary_state": {"token": "secret"}},
        {"boundary_state": None},
        {"extra": "secret"},
    ],
)
def test_marker_snapshot_rejects_hostile_or_unbounded_values(change: dict[str, object]) -> None:
    assert marker_snapshot_summary({**OBSERVED, **change}) == {"status": "malformed"}


def test_marker_snapshot_refuses_missing_fields_and_non_builtin_types() -> None:
    class Mapping(dict[str, object]):
        pass

    class Count(int):
        pass

    class Category(str):
        pass

    for key in OBSERVED:
        value = {name: item for name, item in OBSERVED.items() if name != key}
        assert marker_snapshot_summary(value) == {"status": "malformed"}
    invalid_values: tuple[object, ...] = (
        None,
        [],
        Mapping(OBSERVED),
        {**OBSERVED, "marker_count": Count(1)},
        {**OBSERVED, "document_url": Category("fixture")},
    )
    for invalid in invalid_values:
        assert marker_snapshot_summary(invalid) == {"status": "malformed"}


def test_actual_snapshot_javascript_emits_only_categories_and_capped_counts() -> None:
    # Execute the exact authored expression in Node with inert DOM-shaped inputs.
    # No browser, URL navigation, network or downloaded dependency is involved.
    script = f"""
const observe = {MARKER_SNAPSHOT};
const rows = [];
for (const url of [{json.dumps(URL)}, 'chrome-error://chromewebdata/', 'private-url']) {{
 for (const count of [0, 1, 2, 5]) {{
  globalThis.document = {{URL:url, querySelectorAll: selector => {{
   if (selector !== '#marker') throw Error('unexpected selector');
   return Array.from({{length:count}}, () => ({{textContent:'synthetic marker revealed'}}));
  }}}};
  globalThis.boundaryReady = true;
  globalThis.boundaryState = {{private:'never emitted'}};
  rows.push(observe());
 }}
}}
globalThis.document = {{URL:'private-url', querySelectorAll: () => [{{textContent:'secret'}}]}};
globalThis.boundaryReady = 'secret';
globalThis.boundaryState = 'secret';
rows.push(observe());
process.stdout.write(JSON.stringify(rows));
"""
    result = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True, timeout=5
    )
    rows = json.loads(result.stdout)
    assert len(rows) == 13 and all(
        marker_snapshot_summary(row)["status"] == "observed" for row in rows
    )
    assert [row["marker_count"] for row in rows[:4]] == [0, 1, 2, 2]
    assert rows[1]["marker_expected"] is True and rows[2]["marker_expected"] is False
    assert rows[4]["document_url"] == "error_document" and rows[8]["document_url"] == "other"
    assert rows[-1]["boundary_ready"] == rows[-1]["boundary_state"] == "other"
    assert not rows[-1]["marker_expected"]
    assert "secret" not in result.stdout and "private" not in result.stdout


@pytest.mark.parametrize("failure", ["", "timeout", "error", "malformed"])
@pytest.mark.parametrize("same_frame", [True, False])
def test_marker_failure_snapshot_keeps_identity_and_errors_data_free(
    failure: str, same_frame: bool
) -> None:
    frame = cast(Frame, object())

    class FakePage:
        url = "private-url?token=secret"
        main_frame = frame if same_frame else object()

        def is_closed(self) -> bool:
            return False

        async def evaluate(self, expression: str) -> object:
            assert expression == MARKER_SNAPSHOT
            if failure == "timeout":
                raise TimeoutError("private timeout text")
            if failure == "error":
                raise RuntimeError("private driver text")
            return {"private": "secret"} if failure == "malformed" else OBSERVED

    raw = asyncio.run(marker_failure_message(cast(Page, FakePage()), frame))
    value = json.loads(raw.removeprefix("Marker failure snapshot: "))
    assert value["page_url"] == "other" and value["page_state"] == "open"
    assert value["same_main_frame"] is same_frame
    assert (
        value["document_snapshot"]["status"]
        == {"": "observed", "timeout": "timeout", "error": "unavailable", "malformed": "malformed"}[
            failure
        ]
    )
    assert "private" not in raw and "secret" not in raw and len(raw) < 512


def marker_probe() -> Any:
    """Compile the exact assertion/catch; successful behavior is unchanged."""
    source = (ROOT / "scripts/isolation/browser_acceptance.py").read_text()
    tree = ast.parse(source)
    block = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        and any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "inner_text"
            for child in ast.walk(ast.Module(body=node.body, type_ignores=[]))
        )
    )
    assert ast.unparse(block.body[0]) == (
        "if await page.locator('#marker').inner_text() != 'synthetic marker revealed':\n"
        "    raise RuntimeError('Approved synthetic browser interaction failed')"
    )
    assert sum(isinstance(node, ast.Await) for line in block.body for node in ast.walk(line)) == 1
    assert isinstance(block.handlers[0].body[-1], ast.Raise)
    assert block.handlers[0].body[-1].exc is None
    function = ast.parse("async def probe():\n    pass\n")
    entry = cast(ast.AsyncFunctionDef, function.body[0])
    entry.body = [copy.deepcopy(block)]
    return compile(ast.fix_missing_locations(function), "owned-marker-probe", "exec")


@pytest.mark.parametrize("failure", ["", "driver", "text"])
@pytest.mark.parametrize("diagnostic_failure", ["", "evaluate", "cancel", "output"])
def test_marker_diagnostic_never_changes_success_or_primary_failure(
    failure: str, diagnostic_failure: str
) -> None:
    original = Error("private driver error")
    observed: list[str] = []

    class Locator:
        async def inner_text(self) -> str:
            observed.append("marker")
            if failure == "driver":
                raise original
            return "wrong" if failure == "text" else "synthetic marker revealed"

    class FakePage:
        def locator(self, selector: str) -> Locator:
            assert selector == "#marker"
            return Locator()

    async def diagnostic(page: object, frame: object) -> str:
        assert page is fake and frame is expected_frame
        observed.append("diagnostic")
        if diagnostic_failure == "evaluate":
            raise RuntimeError("private snapshot failure")
        if diagnostic_failure == "cancel":
            raise asyncio.CancelledError()
        return "fixed diagnostic"

    def emit(value: str) -> None:
        assert value == "fixed diagnostic"
        observed.append("output")
        if diagnostic_failure == "output":
            raise OSError("private output failure")

    fake, expected_frame = FakePage(), object()
    namespace: dict[str, Any] = {
        "page": fake,
        "fixture_frame": expected_frame,
        "Error": Error,
        "marker_failure_message": diagnostic,
        "trace_stage": emit,
    }
    exec(marker_probe(), namespace)
    if failure == "driver":
        with pytest.raises(Error) as caught:
            asyncio.run(namespace["probe"]())
        assert caught.value is original
    elif failure == "text":
        with pytest.raises(RuntimeError, match="^Approved synthetic browser interaction failed$"):
            asyncio.run(namespace["probe"]())
    else:
        asyncio.run(namespace["probe"]())
        assert observed == ["marker"]
    if failure:
        assert observed == (
            ["marker", "diagnostic"]
            if diagnostic_failure in {"evaluate", "cancel"}
            else ["marker", "diagnostic", "output"]
        )


def test_marker_snapshot_uses_one_second_only_and_cancels_stalled_driver() -> None:
    import runpy

    namespace = runpy.run_path(str(ROOT / "scripts/isolation/browser_acceptance.py"))
    helper = namespace["marker_failure_message"]
    budgets: list[int] = []
    cancelled: list[bool] = []
    actual_wait = asyncio.wait_for

    async def bounded(awaitable: Any, *, timeout: int) -> Any:
        budgets.append(timeout)
        return await actual_wait(awaitable, timeout=0.01)

    helper.__globals__["asyncio"] = SimpleNamespace(wait_for=bounded)

    class FakePage:
        url = URL
        main_frame = object()

        def is_closed(self) -> bool:
            return False

        async def evaluate(self, expression: str) -> object:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)
            return None

    page = FakePage()
    result = asyncio.run(helper(page, page.main_frame))
    assert budgets == [1] and cancelled == [True]
    assert json.loads(result.removeprefix("Marker failure snapshot: "))["document_snapshot"] == {
        "status": "timeout"
    }

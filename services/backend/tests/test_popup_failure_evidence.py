"""Failure-only synthetic popup diagnostics; no real browser or CDP socket."""

import ast
import asyncio
import json
from pathlib import Path
from typing import Any, cast

import pytest
from browser_acceptance import (
    POPUP_URL,
    URL,
    popup_failure_message,
    popup_target_summary,
    wait_artifact_completion,
)
from playwright.async_api import CDPSession

SECRET = "SECRET-title-id-url-query-token"
PARENT = {"targetInfo": {"type": "page", "url": URL, "targetId": "owned", "title": SECRET}}


def observations() -> dict[str, int | bool]:
    return {
        "popup_closed": False,
        "download_cancelled": True,
        "popup_count": 0,
        "download_count": 1,
        "popup_route_seen": 1,
        "popup_abort_completed": 1,
        "context_page_events": 0,
        "context_pages": 1,
    }


def test_only_owned_children_become_fixed_categories() -> None:
    urls = [POPUP_URL, "about:blank", "", ":", "chrome-error://chromewebdata/", SECRET]
    targets = {
        "targetInfos": [
            {"type": "page", "openerId": "owned", "targetId": SECRET, "title": SECRET, "url": url}
            for url in urls
        ]
        + [
            {"type": "page", "openerId": SECRET, "url": SECRET},
            {"type": "worker", "openerId": "owned", "url": SECRET},
        ]
    }
    result = popup_target_summary(PARENT, targets)
    assert result == {
        "status": "observed",
        "children": 6,
        "classes": {
            "synthetic_popup": 1,
            "blank": 1,
            "initial": 2,
            "error_document": 1,
            "other": 1,
        },
    }
    encoded = json.dumps(result)
    assert SECRET not in encoded and "owned" not in encoded and "https:" not in encoded


@pytest.mark.parametrize(
    "parent,targets,status",
    [
        (None, {}, "malformed"),
        ({}, None, "malformed"),
        ({"targetInfo": []}, {"targetInfos": []}, "malformed"),
        (PARENT, {"targetInfos": SECRET}, "malformed"),
        (
            {"targetInfo": {"type": "page", "url": SECRET, "targetId": "owned"}},
            {"targetInfos": []},
            "parent_unverified",
        ),
        (
            {"targetInfo": {"type": "page", "url": URL, "targetId": 1}},
            {"targetInfos": []},
            "parent_unverified",
        ),
        (
            {"targetInfo": {"type": "page", "url": URL, "targetId": "x" * 129}},
            {"targetInfos": []},
            "parent_unverified",
        ),
        (PARENT, {"targetInfos": [{}] * 17}, "over_cap"),
        (PARENT, {"targetInfos": [SECRET]}, "malformed"),
        (PARENT, {"targetInfos": [{}]}, "malformed"),
        (PARENT, {"targetInfos": [{"type": 17}]}, "malformed"),
        (PARENT, {"targetInfos": [{"type": "x" * 65}]}, "malformed"),
        (PARENT, {"targetInfos": [{"type": "page", "openerId": []}]}, "malformed"),
        (PARENT, {"targetInfos": [{"type": "page", "openerId": ""}]}, "malformed"),
        (PARENT, {"targetInfos": [{"type": "page", "openerId": "x" * 129}]}, "malformed"),
        (PARENT, {"targetInfos": [{"type": "page", "openerId": "owned", "url": 1}]}, "malformed"),
        (
            PARENT,
            {"targetInfos": [{"type": "page", "openerId": "owned", "url": "x" * 4097}]},
            "malformed",
        ),
    ],
)
def test_target_input_is_bounded_and_never_echoed(
    parent: object, targets: object, status: str
) -> None:
    assert popup_target_summary(parent, targets) == {"status": status}


class Reader:
    def __init__(self, error: Exception | None = None, late: asyncio.Event | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.error = error
        self.late = late

    async def send(self, method: str, params: Any = None) -> dict[str, Any]:
        self.calls.append((method, params))
        if self.late:
            self.late.set()
        if self.error:
            raise self.error
        return PARENT if method == "Target.getTargetInfo" else {"targetInfos": []}


@pytest.mark.parametrize(
    "error,status",
    [(None, "observed"), (RuntimeError(SECRET), "unavailable"), (TimeoutError(SECRET), "timeout")],
)
def test_failure_snapshot_is_read_only_and_hides_exception_text(
    error: Exception | None, status: str
) -> None:
    reader = Reader(error)
    message = asyncio.run(popup_failure_message(cast(CDPSession, reader), **observations()))
    result = json.loads(message.split(": ", 1)[1])
    assert result["target_snapshot"]["status"] == status
    assert SECRET not in message and len(message) < 1024
    assert reader.calls[0] == ("Target.getTargetInfo", None)
    if error is None:
        assert reader.calls[1] == (
            "Target.getTargets",
            {"filter": [{"type": "page", "exclude": False}, {"exclude": True}]},
        )
    assert all(
        method in {"Target.getTargetInfo", "Target.getTargets"} for method, _ in reader.calls
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"popup_count": SECRET},
        {"popup_count": True},
        {"context_pages": -1},
        {"popup_closed": SECRET},
        {"unexpected": SECRET},
    ],
)
def test_invalid_observations_cannot_disclose_values(patch: dict[str, object]) -> None:
    values: dict[str, object] = {**observations(), **patch}
    message = asyncio.run(popup_failure_message(cast(CDPSession, Reader()), **values))
    assert json.loads(message.split(": ", 1)[1])["observations"] == "invalid"
    assert SECRET not in message


def test_observation_counts_are_capped() -> None:
    values = {**observations(), "context_pages": 10**50}
    result = json.loads(
        asyncio.run(popup_failure_message(cast(CDPSession, Reader()), **values)).split(": ", 1)[1]
    )
    assert result["context_pages"] == 16 and result["count_over_cap"] is True


def test_late_completion_cannot_rewrite_failure() -> None:
    async def exercise() -> None:
        popup, download = asyncio.Event(), asyncio.Event()
        download.set()
        try:
            await wait_artifact_completion(popup, download, timeout=0.001)
        except TimeoutError as original:
            message = await popup_failure_message(
                cast(CDPSession, Reader(late=popup)),
                **{**observations(), "popup_closed": popup.is_set()},
            )
            assert popup.is_set()
            assert json.loads(message.split(": ", 1)[1])["popup_closed"] is False
            raise RuntimeError(message) from original
        raise AssertionError("Original failure disappeared")

    with pytest.raises(RuntimeError, match="Popup/download completion missing"):
        asyncio.run(exercise())


def test_one_budget_covers_both_reads_and_source_always_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import browser_acceptance

    original = asyncio.wait_for
    budgets: list[float] = []

    async def bounded(awaitable: Any, timeout: float) -> Any:
        budgets.append(timeout)
        return await original(awaitable, timeout=0.01)

    class NeverFinishes(Reader):
        async def send(self, method: str, params: Any = None) -> dict[str, Any]:
            if method == "Target.getTargets":
                await asyncio.Event().wait()
            return await super().send(method, params)

    monkeypatch.setattr(asyncio, "wait_for", bounded)
    message = asyncio.run(
        popup_failure_message(cast(CDPSession, NeverFinishes()), **observations())
    )
    assert budgets == [1]
    assert json.loads(message.split(": ", 1)[1])["target_snapshot"] == {"status": "timeout"}
    source = Path(browser_acceptance.__file__).read_text()
    tree = ast.parse(source)
    handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and "await popup_failure_message" in ast.unparse(node)
    ]
    assert len(handlers) == 1 and isinstance(handlers[0].body[-1], ast.Raise)
    assert "timeout: float = 3" in source and "timeout <= 3" in source
    assert source.index("page = await context.new_page()") < source.index(
        'context.on("page", context_page)'
    )


def test_valid_parent_row_without_opener_is_not_a_child() -> None:
    assert popup_target_summary(PARENT, {"targetInfos": [PARENT["targetInfo"]]}) == {
        "status": "observed",
        "children": 0,
        "classes": {
            "synthetic_popup": 0,
            "blank": 0,
            "initial": 0,
            "error_document": 0,
            "other": 0,
        },
    }


def test_unverified_parent_prevents_target_listing() -> None:
    class Unowned(Reader):
        async def send(self, method: str, params: Any = None) -> dict[str, Any]:
            self.calls.append((method, params))
            assert method == "Target.getTargetInfo"
            return {"targetInfo": {"type": "page", "url": SECRET, "targetId": SECRET}}

    reader = Unowned()
    message = asyncio.run(popup_failure_message(cast(CDPSession, reader), **observations()))
    assert reader.calls == [("Target.getTargetInfo", None)]
    assert json.loads(message.split(": ", 1)[1])["target_snapshot"] == {
        "status": "parent_unverified"
    }
    assert SECRET not in message

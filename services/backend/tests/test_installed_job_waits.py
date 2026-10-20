"""Authored Channel overlap and actual terminal-wait wiring, never browser evidence."""

import ast
import asyncio
from pathlib import Path
from typing import Any

import pytest
from installed_operator_redirects import installed_relay_reason
from test_operator_ui_protocol import _owned_channel


async def turns() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


def test_overlapping_refresh_waves_exhaust_original_channel_with_stream_held() -> None:
    async def exercise() -> None:
        channel = _owned_channel()
        tasks = [asyncio.create_task(channel.request({"kind": "request", "authored": "stream"}))]
        try:
            await turns()
            # Two global refreshes invalidate seven resource hooks each. Keeping
            # their relay calls pending models real work despite browser abort.
            for wave in range(2):
                tasks.extend(
                    asyncio.create_task(
                        channel.request({"kind": "request", "wave": wave, "resource": item})
                    )
                    for item in range(7)
                )
                await turns()
            assert channel.admitted == 15 and len(channel.pending) == 8
            tasks.append(
                asyncio.create_task(
                    channel.request({"kind": "request", "authored": "third-wave-first"})
                )
            )
            await turns()
            assert channel.admitted == 16 and channel.waiting == 8
            with pytest.raises(RuntimeError) as caught:
                await channel.request({"kind": "request", "authored": "third-wave-second"})
            assert type(caught.value) is RuntimeError
            assert installed_relay_reason(caught.value) == "installed_relay_admission_capacity"
            assert channel.admitted == 16 and channel.identifier == 8
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert not channel.pending and channel.admitted == channel.waiting == 0
        assert channel.capacity._value == 8

    asyncio.run(exercise())


def test_completed_waves_keep_original_capacity_without_dropping_continuous_stream() -> None:
    async def exercise() -> None:
        channel = _owned_channel()
        stream = asyncio.create_task(channel.request({"kind": "request", "authored": "stream"}))
        tasks = [stream]
        peak = 0
        try:
            await turns()
            stream_id = next(iter(channel.pending))
            for wave in range(3):
                current = [
                    asyncio.create_task(
                        channel.request({"kind": "request", "wave": wave, "resource": item})
                    )
                    for item in range(7)
                ]
                tasks.extend(current)
                await turns()
                peak = max(peak, channel.admitted)
                assert not stream.done() and channel.admitted == 8 and channel.waiting == 0
                for identifier, future in list(channel.pending.items()):
                    if identifier != stream_id:
                        future.set_result(
                            {"kind": "reply", "identifier": identifier, "status": 200}
                        )
                assert all(reply["status"] == 200 for reply in await asyncio.gather(*current))
                assert channel.admitted == 1 and list(channel.pending) == [stream_id]
            assert peak == 8 and not stream.done()
            channel.pending[stream_id].set_result(
                {"kind": "reply", "identifier": stream_id, "status": 200}
            )
            assert (await stream)["status"] == 200
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert not channel.pending and channel.admitted == channel.waiting == 0
        assert channel.capacity._value == 8

    asyncio.run(exercise())


def job_wait(seconds: int, text: str) -> Any:
    """Compile the exact installed guest block; any refresh/click fails this test."""
    root = Path(__file__).resolve().parents[3]
    source = (root / "scripts/isolation/installed_operator_browser.py").read_text()
    block = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncWith)
        and ast.unparse(node.items[0].context_expr) == f"asyncio.timeout({seconds})"
        and text in ast.unparse(node)
        and not any(isinstance(child, ast.While) for child in ast.walk(node))
    )
    assert len(block.body) == 1
    assert sum(isinstance(node, ast.Await) for node in ast.walk(block)) == 1
    function = ast.AsyncFunctionDef(
        name="wait",
        args=ast.arguments(
            posonlyargs=[], args=[ast.arg(arg="page")], kwonlyargs=[], kw_defaults=[], defaults=[]
        ),
        body=[block],
        decorator_list=[],
        type_params=[],
    )
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace: dict[str, Any] = {"asyncio": asyncio}
    exec(compile(module, "owned-job-wait", "exec"), namespace)
    return namespace["wait"]


@pytest.mark.parametrize("seconds,text", [(55, "completed partial"), (30, "completed")])
def test_job_wait_observes_exact_real_terminal_ui_with_original_whole_budget(
    seconds: int, text: str
) -> None:
    async def exercise() -> None:
        observed = asyncio.Event()
        calls: list[dict[str, Any]] = []

        class Locator:
            async def wait_for(self, **options: Any) -> None:
                calls.append(options)
                await observed.wait()

        class Page:
            def get_by_text(self, value: str, *, exact: bool) -> Locator:
                assert value == text and exact is True
                return Locator()

        task = asyncio.create_task(job_wait(seconds, text)(Page()))
        await turns()
        assert not task.done() and calls == [{"state": "visible", "timeout": seconds * 1000}]
        observed.set()
        await task

    asyncio.run(exercise())


def test_job_wait_source_retains_initial_fetch_real_replay_and_terminal_assertions() -> None:
    root = Path(__file__).resolve().parents[3]
    views = (root / "apps/web/src/views.tsx").read_text()
    workspace = views.split("function JobWorkspace", 1)[1].split("export type ContactFilters", 1)[0]
    assert "const progress = useResource<Progress>" in workspace
    assert "c.revision + pulse" in workspace
    assert "c.scope.events(id," in workspace and "setPulse(p => p + 1)" in workspace
    assert "cursor = checkpoint" in workspace and "controller.signal, cursor" in workspace
    assert "progress.data?.state ?? current.state" in workspace
    guest = (root / "scripts/isolation/installed_operator_browser.py").read_text()
    assert guest.count('name="Refresh current view", exact=True') == 1  # Existing export loop only.
    assert '"action": "wait_jobs"' in guest
    assert '"1 of 1 discovered article units terminal"' in guest
    assert 'name="no contact", exact=True' in guest
    assert 'name="Actual article outcomes and failures"' in guest


@pytest.mark.parametrize("seconds,text", [(55, "completed partial"), (30, "completed")])
def test_failed_terminal_observation_propagates_without_refresh_or_retry(
    seconds: int, text: str
) -> None:
    async def exercise() -> None:
        failure = TimeoutError("authored missing terminal observation")
        calls = 0

        class Locator:
            async def wait_for(self, **options: Any) -> None:
                nonlocal calls
                calls += 1
                raise failure

        class Page:
            def get_by_text(self, value: str, *, exact: bool) -> Locator:
                assert value == text and exact
                return Locator()

        with pytest.raises(TimeoutError) as caught:
            await job_wait(seconds, text)(Page())
        assert caught.value is failure and calls == 1

    asyncio.run(exercise())

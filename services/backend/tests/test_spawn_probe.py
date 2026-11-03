"""Harness startup does not consume or extend the isolated action deadline."""

import multiprocessing
from types import SimpleNamespace
from typing import Any

import pytest
import spawn_probe


@pytest.mark.parametrize(
    "ready,exitcode,alive",
    [(True, 0, False), (False, None, True), (True, None, True), (True, 1, False)],
)
def test_bounded_probe_cleanup(
    monkeypatch: pytest.MonkeyPatch, ready: bool, exitcode: int | None, alive: bool
) -> None:
    calls: list[object] = []

    def wait(*, timeout: int) -> bool:
        calls.append(("ready", timeout))
        return ready

    child = SimpleNamespace(
        start=lambda: calls.append("start"),
        join=lambda *, timeout: calls.append(("join", timeout)),
        exitcode=exitcode,
        is_alive=lambda: alive,
        kill=lambda: calls.append("kill"),
        close=lambda: calls.append("close"),
    )

    def process(**kwargs: Any) -> object:
        assert kwargs["target"] is spawn_probe._entered
        assert kwargs["args"][1] == ("synthetic",)
        return child

    context = SimpleNamespace(Event=lambda: SimpleNamespace(wait=wait), Process=process)
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: context)
    if ready and exitcode == 0:
        spawn_probe.run_spawn_probe(lambda value: None, "synthetic")
    else:
        with pytest.raises(AssertionError, match="action" if ready else "startup"):
            spawn_probe.run_spawn_probe(lambda value: None, "synthetic")
    expected: list[object] = ["start", ("ready", 30)]
    if ready:
        expected.append(("join", 10))
    if alive:
        expected.extend(["kill", ("join", 5)])
    assert calls == [*expected, "close"]


def test_ready_precedes_unchanged_probe() -> None:
    calls: list[str] = []
    spawn_probe._entered(
        lambda value: calls.append(value),
        ("probe",),
        SimpleNamespace(set=lambda: calls.append("ready")),
    )
    assert calls == ["ready", "probe"]

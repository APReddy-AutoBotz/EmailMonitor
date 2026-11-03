"""Bound interpreter startup separately from isolated composition assertions."""

import multiprocessing
from collections.abc import Callable
from typing import Any


def _entered(target: Callable[..., None], args: tuple[object, ...], ready: Any) -> None:
    ready.set()
    target(*args)


def run_spawn_probe(target: Callable[..., None], *args: object) -> None:
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    child = context.Process(target=_entered, args=(target, args, ready))
    child.start()
    try:
        assert ready.wait(timeout=30), "isolated probe startup exceeded 30 seconds"
        child.join(timeout=10)
        assert child.exitcode == 0, "isolated probe action failed or exceeded 10 seconds"
    finally:
        if child.is_alive():
            child.kill()
            child.join(timeout=5)
        child.close()

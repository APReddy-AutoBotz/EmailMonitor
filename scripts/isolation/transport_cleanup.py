"""Failure-safe cleanup of the one owned held-response acceptance fixture."""

import asyncio
import time
from collections.abc import Iterator
from concurrent.futures import CancelledError, Future
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from transport_topology import Topology


def failure_note(stage: str, error: BaseException) -> str:
    """Fixed bounded diagnostics only; never copy exception messages or guest data."""
    category = "BaseException"
    for kind in (
        asyncio.CancelledError,
        CancelledError,
        TimeoutError,
        AssertionError,
        OSError,
        RuntimeError,
        KeyboardInterrupt,
        SystemExit,
    ):
        if isinstance(error, kind):
            category = kind.__name__
            break
    return "held_response_cleanup:" + stage + ":" + category


def finish_held_response(
    topology: "Topology", pending: Future[bytes], primary: BaseException | None
) -> None:
    failures: list[tuple[BaseException, str]] = []
    stage = "fixture_lookup"
    try:
        # Only this fixture's Event is released. Gateway authority and channel
        # health are separate; a poisoned gateway never selects another pipe.
        fixture = topology.processes["fixture-a"]
        stage = "fixture_poisoned"
        if fixture.poisoned:
            raise RuntimeError("Held fixture control channel is poisoned")
        try:
            deadline = time.monotonic() + 5
            stage = "release_send"
            fixture.send({"kind": "release"}, deadline)
            stage = "release_receive"
            reply = fixture.receive(deadline)
            stage = "release_acknowledgement"
            assert reply == {"kind": "released"}, "Held fixture release acknowledgement differs"
        except BaseException:
            # An interrupted/uncertain exchange or unexpected frame can never
            # be retried or reused, even if the underlying method did not poison.
            fixture.poisoned = True
            raise
    except BaseException as error:
        failures.append((error, failure_note(stage, error)))
    try:
        # Always collect once, including after failed release; existing worker
        # transport deadlines still apply if the fixture cannot be contacted.
        stage = "future_result"
        body = pending.result(timeout=20)
        stage = "future_body"
        assert b"synthetic marker" in body, "Held fixture response marker missing"
    except BaseException as error:
        failures.append((error, failure_note(stage, error)))
    if primary is not None:
        for _, note in failures:
            primary.add_note(note)
    elif failures:
        cleanup_error, _ = failures[0]
        for _, note in failures:
            cleanup_error.add_note(note)
        raise cleanup_error


@contextmanager
def held_response_cleanup(topology: "Topology", pending: Future[bytes]) -> Iterator[None]:
    """Release/collect in finally while still inside the owning executor scope."""
    primary: BaseException | None = None
    try:
        yield
    except BaseException as error:
        primary = error
        raise
    finally:
        finish_held_response(topology, pending, primary)

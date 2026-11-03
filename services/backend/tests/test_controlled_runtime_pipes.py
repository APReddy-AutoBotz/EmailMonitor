"""Binary capability pipe ownership and stderr cap, entirely local anonymous pipes."""

import os
import threading
import time
from pathlib import Path

import pytest
from emailmonitor.runtime.controlled_entrypoint import require_confinement
from emailmonitor.runtime.controlled_pipes import FramedPipes


def pair() -> tuple[FramedPipes, FramedPipes]:
    read_a, write_b = os.pipe()
    read_b, write_a = os.pipe()
    return FramedPipes(read_a, write_a), FramedPipes(read_b, write_b)


def test_duplex_pipes_transfer_bounded_large_frame_without_stdout_logs() -> None:
    left, right = pair()
    value = {"payload": "x" * 100000}
    errors: list[BaseException] = []

    def send() -> None:
        try:
            left.send(value, time.monotonic() + 2)
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=send)
    thread.start()
    try:
        assert right.receive(time.monotonic() + 2) == value
        thread.join(2)
        assert not thread.is_alive() and not errors
        right.send({"ok": True}, time.monotonic() + 2)
        assert left.receive(time.monotonic() + 2) == {"ok": True}
    finally:
        left.close()
        right.close()
        thread.join(2)


def test_stderr_eof_closes_owned_duplicate_before_forgetting_it() -> None:
    read, write = os.pipe()
    left, right = pair()
    left.errors = read
    os.close(write)
    try:
        left._error()
        assert left.errors is None
        with pytest.raises(OSError):
            os.fstat(read)
    finally:
        left.close()
        right.close()


def test_stderr_flood_poisoned_without_logging_payload() -> None:
    read, write = os.pipe()
    left, right = pair()
    left.errors = read
    try:
        os.write(write, b"x" * 4097)
        with pytest.raises(RuntimeError, match="Controlled pipe failed"):
            left.receive(time.monotonic() + 1)
        assert left.poisoned
    finally:
        os.close(write)
        left.close()
        right.close()


@pytest.mark.parametrize("field", ["uid", "caps", "privs", "seccomp", "socket"])
def test_entrypoint_refuses_missing_kernel_confinement(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    status = "CapEff:\t00000000\nNoNewPrivs:\t1\nSeccomp:\t2\n"
    if field == "caps":
        status = status.replace("00000000", "00000001")
    elif field == "privs":
        status = status.replace("NoNewPrivs:\t1", "NoNewPrivs:\t0")
    elif field == "seccomp":
        status = status.replace("Seccomp:\t2", "Seccomp:\t0")
    monkeypatch.setattr(os, "geteuid", lambda: 0 if field == "uid" else 65532)
    monkeypatch.setattr(Path, "read_text", lambda self: status)
    monkeypatch.setattr(Path, "exists", lambda self: field == "socket")
    with pytest.raises(ValueError, match="confinement"):
        require_confinement()


def test_pipe_eof_and_deadline_fail_closed() -> None:
    left, right = pair()
    right.close()
    try:
        with pytest.raises(RuntimeError):
            left.receive(time.monotonic() + 1)
        assert left.poisoned
    finally:
        left.close()

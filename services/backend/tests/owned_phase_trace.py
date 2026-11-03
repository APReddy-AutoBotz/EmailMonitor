"""Bounded, value-free diagnostics for owned synthetic test processes only."""

import _thread
import builtins
import json
import os
import resource
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

PHASES = frozenset(
    {
        "launch",
        "child_started",
        "imports_ready",
        "worker_ready",
        "dependencies_ready",
        "patches_ready",
        "app_ready",
        "worker_construct_started",
        "handshake_ready",
        "work_started",
        "first_poll_done",
        "ack_seen",
        "cleanup_started",
        "cleanup_complete",
        "child_failed",
        "child_complete",
        "join_returned",
        "timeout",
        "timeout_observed",
        "returned",
    }
)


class PhaseTrace:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.count = 0

    def mark(self, phase: str) -> None:
        if phase not in PHASES:
            raise ValueError("Fixed diagnostic phase required")
        if self.count >= 16:
            return
        self.count += 1
        record = {
            "phase": phase,
            "monotonic_ns": time.monotonic_ns(),
            "cpu_ns": time.process_time_ns(),
            "pid": os.getpid(),
            "pgid": os.getpgrp(),
            "maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
        try:
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
            )
            try:
                os.write(descriptor, (json.dumps(record) + "\n").encode())
            finally:
                os.close(descriptor)
        except OSError:
            # Missing diagnostics cannot turn a refused/failed operation into success.
            pass


def resources() -> dict[str, object]:
    result: dict[str, object] = {}
    for name in ("cpu.stat", "cpu.max", "memory.current", "memory.events"):
        try:
            with (Path("/sys/fs/cgroup") / name).open() as source:
                value = source.read(4097)
            result[name] = value if len(value) <= 4096 else "unavailable"
        except OSError:
            result[name] = "unavailable"
    return result


def receipt(path: Path, value: dict[str, Any]) -> None:
    try:
        path.write_text(json.dumps(value, sort_keys=True) + "\n")
        path.chmod(0o600)
    except OSError:
        pass


class ImportProfile:
    """Temporary, test-owned import timing; no arguments or imported values recorded."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.original = builtins.__import__
        self.rows: dict[str, dict[str, int]] = {}
        self.dropped = 0
        self.thread = _thread.get_ident()
        self.stack: list[list[int]] = []
        self.initial_hooks = {
            "trace_active": sys.gettrace() is not None,
            "profile_active": sys.getprofile() is not None,
            "builtin_importer": getattr(self.original, "__module__", None) == "builtins",
            "meta_path_count": len(sys.meta_path),
        }

    def __enter__(self) -> "ImportProfile":
        builtins.__import__ = self.imported
        return self

    def __exit__(self, *_: object) -> None:
        builtins.__import__ = self.original
        self.flush()

    def imported(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if _thread.get_ident() != self.thread:
            return self.original(name, *args, **kwargs)
        roots = {
            "celery",
            "kombu",
            "amqp",
            "emailmonitor",
            "sqlalchemy",
            "pydantic",
            "pydantic_core",
            "pytest",
            "_pytest",
            "cryptography",
            "pg8000",
            "test_worker_callback_wake",
        }
        label = (
            name
            if (
                len(name) <= 160
                and name.split(".")[0] in roots
                and all(part.isidentifier() for part in name.split("."))
            )
            else "other"
        )
        if label not in {"other", "test_worker_callback_wake"} and not label.startswith(
            "emailmonitor."
        ):
            label = label.split(".")[0]
        if label not in self.rows and len(self.rows) >= 256:
            label = "other"
            self.dropped += 1
        row = self.rows.setdefault(
            label,
            {
                "calls": 0,
                "cold_calls": 0,
                "wall_ns": 0,
                "cpu_ns": 0,
                "self_wall_ns": 0,
                "self_cpu_ns": 0,
            },
        )
        cold = name not in sys.modules
        wall, cpu = time.monotonic_ns(), time.process_time_ns()
        self.stack.append([0, 0])
        try:
            return self.original(name, *args, **kwargs)
        finally:
            elapsed_wall = time.monotonic_ns() - wall
            elapsed_cpu = time.process_time_ns() - cpu
            nested_wall, nested_cpu = self.stack.pop()
            if self.stack:
                self.stack[-1][0] += elapsed_wall
                self.stack[-1][1] += elapsed_cpu
            row["calls"] += 1
            row["cold_calls"] += int(cold)
            row["wall_ns"] += elapsed_wall
            row["cpu_ns"] += elapsed_cpu
            row["self_wall_ns"] += max(0, elapsed_wall - nested_wall)
            row["self_cpu_ns"] += max(0, elapsed_cpu - nested_cpu)

    def flush(self) -> None:
        # Inclusive totals must not be summed across nested imports.
        receipt(
            self.path,
            {
                "inclusive_imports": self.rows,
                "overflow_calls": self.dropped,
                "initial_hooks": self.initial_hooks,
            },
        )


def callback_entry(path: str, with_wake: bool, diagnostics: bool, outcome: str) -> None:
    trace = PhaseTrace(Path(path))
    trace.mark("child_started")
    try:
        with ImportProfile(Path(path).with_name("callback-imports.json")) as profile:
            from test_worker_callback_wake import _real_solo_delivery

            trace.mark("imports_ready")
            profile.flush()

            def mark(phase: str) -> None:
                trace.mark(phase)
                if phase in {"app_ready", "worker_ready", "cleanup_complete"}:
                    profile.flush()

            _real_solo_delivery(with_wake, diagnostics, outcome, mark=mark)
            trace.mark("child_complete")
    except BaseException:
        trace.mark("child_failed")
        raise


def quiet_mark(_: str) -> None:
    pass


Mark = Callable[[str], None]

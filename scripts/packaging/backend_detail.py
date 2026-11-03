"""Fixed, value-free backend observations; never an acceptance receipt."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

KEY = "EM_OWNED_BACKEND_DETAIL"
RESTORE = (
    "services/backend/tests/test_restore_tenant.py::"
    "test_actual_restore_replays_current_privacy_before_runtime_and_rebuilds_broker"
)
BROKER = (
    "services/backend/tests/test_service_reuse_broker.py::"
    "test_reused_observation_survives_worker_crash_and_original_redelivery"
)
SERVICE = (
    "services/backend/tests/test_service_reuse_tenant.py::"
    "test_service_worker_reads_only_its_target_and_never_acquires_fresh_bytes"
)
ROUTES = ("html", "pdf", "article_xml", "provider")
CASES = (
    RESTORE,
    *(f"{BROKER}[{route}]" for route in ROUTES),
    *(f"{SERVICE}[{route}]" for route in ROUTES),
)
STATES = frozenset("NIPFS")  # not reached, incomplete, passed, failed, skipped


def owned_path(progress: str | None, detail: str | None) -> Path | None:
    if not progress or not detail:
        return None
    progress_file, detail_file = Path(progress), Path(detail)
    if (
        progress_file.is_absolute()
        and progress_file.name == "progress.json"
        and detail_file.name == "detail.json"
        and detail_file.parent == progress_file.parent
        and progress_file.parent.name.startswith("em-backend-outcome-")
    ):
        return detail_file
    return None


class Detail:
    """Observe pytest phase durations; never alter its clocks or decisions.

    Module ordinals follow first appearance in the exact selected collection.
    Totals sum reported setup/call/teardown durations, not end-to-end wall time;
    teardown counts include skips. A partial receipt contains only flushed data.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.modules: dict[str, int] = {}
        self.rows: list[list[int]] = []  # numeric module ordinal, milliseconds, teardowns
        self.cases = ["N"] * len(CASES)
        self.phases: dict[int, set[str]] = {}
        self.current_module: int | None = None
        self.terminal = False
        self.enabled = True

    def save(self) -> None:
        if not self.enabled:
            return
        try:
            data = {"modules": self.rows, "cases": "".join(self.cases), "terminal": self.terminal}
            temporary = self.path.with_suffix(".new")
            temporary.write_text(json.dumps(data, separators=(",", ":")), encoding="ascii")
            temporary.replace(self.path)
        except Exception:
            self.enabled = False

    def pytest_collection_finish(self, session: Any) -> None:
        try:
            for item in session.items:
                module = item.nodeid.partition("::")[0]
                if module not in self.modules:
                    self.modules[module] = len(self.modules) + 1
                    self.rows.append([len(self.modules), 0, 0])
            if len(self.rows) > 1000:
                self.enabled = False
            self.save()
        except Exception:
            self.enabled = False

    def pytest_runtest_logstart(self, nodeid: str, location: object) -> None:
        if not self.enabled:
            return
        module = self.modules.get(nodeid.partition("::")[0])
        if module is None:
            self.enabled = False
            return
        if module != self.current_module:
            self.save()  # Flush completed modules, including before interruption.
            self.current_module = module
        if nodeid in CASES:
            index = CASES.index(nodeid)
            self.cases[index] = "I"
            self.phases[index] = set()
            self.save()

    def pytest_runtest_logreport(self, report: Any) -> None:
        if not self.enabled:
            return
        try:
            module = self.modules.get(report.nodeid.partition("::")[0])
            duration = report.duration
            if (
                module is None
                or type(duration) not in (int, float)
                or not math.isfinite(duration)
                or not 0 <= duration < 1_000_000
            ):
                self.enabled = False
                return
            row = self.rows[module - 1]
            row[1] += round(duration * 1000)
            if report.when == "teardown":
                row[2] += 1
            if report.nodeid in CASES:
                index = CASES.index(report.nodeid)
                if report.outcome == "failed":
                    self.cases[index] = "F"
                elif report.outcome == "skipped" or hasattr(report, "wasxfail"):
                    if self.cases[index] != "F":
                        self.cases[index] = "S"
                elif report.outcome == "passed":
                    self.phases.setdefault(index, set()).add(report.when)
                    if self.cases[index] == "I" and self.phases[index] == {
                        "setup",
                        "call",
                        "teardown",
                    }:
                        self.cases[index] = "P"
                else:
                    self.enabled = False
                    return
                if report.outcome != "passed" or report.when == "teardown":
                    self.save()
        except Exception:
            self.enabled = False

    def pytest_sessionfinish(self, session: Any, exitstatus: object) -> None:
        self.terminal = True
        self.save()


def label(path: Path) -> str:
    """Read only bounded numeric and fixed-category data from the owned file."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Bounded backend detail required")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate backend detail field")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="ascii"), object_pairs_hook=unique)
    if (
        not isinstance(value, dict)
        or set(value) != {"modules", "cases", "terminal"}
        or type(value["terminal"]) is not bool
        or not isinstance(value["cases"], str)
        or len(value["cases"]) != len(CASES)
        or not set(value["cases"]) <= STATES
        or not isinstance(value["modules"], list)
        or len(value["modules"]) > 1000
    ):
        raise ValueError("Closed backend detail required")
    rows = value["modules"]
    for ordinal, row in enumerate(rows, 1):
        if (
            not isinstance(row, list)
            or len(row) != 3
            or any(type(item) is not int for item in row)
            or row[0] != ordinal
            or not 0 <= row[1] < 1_000_000_000
            or not 0 <= row[2] < 1_000_000
        ):
            raise ValueError("Bounded backend module required")
    # Times cover only reports flushed before interruption, not unsampled work.
    top = sorted((row for row in rows if row[2]), key=lambda row: (-row[1], row[0]))[:3]
    modules = "".join(f"-m{row[0]}s{row[1] // 1000}n{row[2]}" for row in top)
    cases = value["cases"]
    return (
        ("terminal" if value["terminal"] else "partial")
        + modules
        + f"-restore{cases[0]}-broker{cases[1:5]}-service{cases[5:9]}"
    )

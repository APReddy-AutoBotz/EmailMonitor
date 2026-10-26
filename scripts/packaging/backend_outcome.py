"""Value-free future acceptance outcomes; never a substitute for partition proof."""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

KEY = "EM_OWNED_BACKEND_PROGRESS"
FIELDS = ("active", "completed", "failed", "total")
CATEGORIES = {
    "normal",
    "test_failure",
    "consumer_exit",
    "consumer_signal",
    "consumer_deadline",
    "wrapper_deadline",
    "wrapper_signal",
    "wrapper_failure",
}


class Progress:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.values = dict.fromkeys(FIELDS, 0)

    def save(self) -> None:
        if self.path is not None:
            # Only the parent-owned temporary directory is supplied by the wrapper.
            temporary = self.path.with_suffix(".new")
            temporary.write_text(json.dumps(self.values), encoding="ascii")
            temporary.replace(self.path)

    def pytest_collection_finish(self, session: Any) -> None:
        self.values["total"] = len(session.items)
        self.save()

    def pytest_runtest_logstart(self, nodeid: str, location: object) -> None:
        self.values["active"] += 1
        self.save()

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.outcome == "failed" and not self.values["failed"]:
            self.values["failed"] = self.values["active"]
        if report.when == "teardown":
            self.values["completed"] += 1
        if report.outcome == "failed" or self.values["completed"] == self.values["total"]:
            self.save()


def read_progress(path: Path) -> dict[str, int]:
    if not path.exists():
        return dict.fromkeys(FIELDS, 0)
    if path.stat().st_size > 256:
        raise ValueError("Bounded numeric progress required")
    value = json.loads(path.read_text(encoding="ascii"))
    if (
        not isinstance(value, dict)
        or set(value) != set(FIELDS)
        or any(type(value[key]) is not int or not 0 <= value[key] < 1_000_000 for key in FIELDS)
    ):
        raise ValueError("Bounded numeric progress required")
    return value


def reported(action: Callable[[Mapping[str, str]], None], environment: Mapping[str, str]) -> None:
    if environment.get("EM_BACKEND_OUTCOME_REPORT") != "true":
        action(environment)
        return
    with tempfile.TemporaryDirectory(prefix="em-backend-outcome-") as directory:
        path = Path(directory) / "progress.json"
        category, code, primary = "normal", 0, None
        try:
            action({**environment, KEY: str(path)})
        except BaseException as error:
            primary = error
            category = getattr(error, "outcome_category", "wrapper_failure")
            code = getattr(error, "consumer_code", 0)
            if isinstance(error, subprocess.TimeoutExpired):
                category = "consumer_deadline"
            raise
        finally:
            try:
                counts = read_progress(path)
                if category == "consumer_exit" and counts["failed"]:
                    category = "test_failure"
                if category not in CATEGORIES or type(code) is not int or not -255 <= code <= 255:
                    raise ValueError("Closed outcome required")
                label = category + "-exit_" + str(code)
                label += "".join("-" + key + "_" + str(counts[key]) for key in FIELDS)
                with Path(environment["GITHUB_OUTPUT"]).open("a", encoding="ascii") as output:
                    output.write("backend_outcome=" + label + "\n")
            except Exception:
                if primary is None:
                    raise
                primary.add_note("Fixed backend outcome reporting unavailable")

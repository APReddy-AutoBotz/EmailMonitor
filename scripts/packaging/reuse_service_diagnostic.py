"""Run fixed guarded reuse cases with value-free evidence, not a partition receipt."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend_detail import CASES, Detail, label

ARGUMENTS = (
    "-c",
    "services/backend/pyproject.toml",
    "--rootdir=.",
    "-o",
    "addopts=",
    "-p",
    "anyio.pytest_plugin",
    "-q",
    "--tb=no",
    "services/backend/tests/test_service_reuse_broker.py",
    "services/backend/tests/test_service_reuse_tenant.py",
)


def emit_report(path: Path) -> None:
    try:
        value = label(path)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="ascii") as output:
            output.write("reuse_diagnostic=" + value + "\n")
    except Exception:
        # Missing diagnostic metadata cannot turn failure into success.
        pass


class IncrementalDetail(Detail):
    """Flush fixed case outcomes as they occur, including before a deadline."""

    def pytest_runtest_logstart(self, nodeid: str, location: object) -> None:
        super().pytest_runtest_logstart(nodeid, location)
        if nodeid in CASES[1:]:
            emit_report(self.path)

    def pytest_runtest_logreport(self, report: Any) -> None:
        super().pytest_runtest_logreport(report)
        try:
            if report.nodeid in CASES[1:] and (
                report.when == "teardown" or report.outcome in {"failed", "skipped"}
            ):
                emit_report(self.path)
        except Exception:
            pass  # A malformed diagnostic event cannot alter pytest's outcome.

    def pytest_sessionfinish(self, session: Any, exitstatus: object) -> None:
        super().pytest_sessionfinish(session, exitstatus)
        emit_report(self.path)


def run(execute: Callable[..., object] | None = None) -> object:
    # The same pytest plugin profile as the full backend; no guard is substituted.
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    if execute is None:
        import pytest

        execute = pytest.main
    with tempfile.TemporaryDirectory(prefix="em-reuse-diagnostic-") as directory:
        path = Path(directory) / "detail.json"
        detail = IncrementalDetail(path)
        try:
            return execute(list(ARGUMENTS), plugins=[detail])
        finally:
            emit_report(path)


if __name__ == "__main__":
    raise SystemExit(run())

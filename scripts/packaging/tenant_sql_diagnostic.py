"""Bounded synthetic SQL timing; diagnostic only, never an acceptance receipt."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend_detail import Detail, label

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
    "services/backend/tests/test_staged_reuse_sql_tenant.py",
    "services/backend/tests/test_tenant_foundation.py",
    "services/backend/tests/test_tooltip_execution_tenant.py",
)


class SqlDetail(Detail):
    """Export numeric phase sums and case dispositions, never identifiers."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.total = 0
        self.active = 0
        self.case_phases: dict[str, set[str]] = {}
        self.failed: set[str] = set()
        self.skipped: set[str] = set()
        self.completed: set[str] = set()

    def emit(self) -> None:
        try:
            if not self.enabled:
                return
            passed = sum(
                phases == {"setup", "call", "teardown"}
                and node not in self.failed
                and node not in self.skipped
                for node, phases in self.case_phases.items()
            )
            counts = (
                self.total,
                self.active,
                len(self.completed),
                passed,
                len(self.failed),
                len(self.skipped - self.failed),
            )
            if any(type(value) is not int or not 0 <= value < 1_000_000 for value in counts):
                return
            detail = label(self.path)
            suffix = "".join(
                f"-{name}{value}"
                for name, value in zip(
                    ("total", "active", "completed", "passed", "failed", "skipped"),
                    counts,
                    strict=True,
                )
            )
            with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="ascii") as output:
                output.write("tenant_sql_diagnostic=" + detail + suffix + "\n")
        except Exception:
            pass  # Diagnostic errors cannot replace the underlying test outcome.

    def pytest_collection_finish(self, session: Any) -> None:
        super().pytest_collection_finish(session)
        try:
            self.total = len(session.items)
            self.emit()
        except Exception:
            pass

    def pytest_runtest_logstart(self, nodeid: str, location: object) -> None:
        super().pytest_runtest_logstart(nodeid, location)
        try:
            self.active += 1
            self.case_phases.setdefault(nodeid, set())
            self.emit()
        except Exception:
            pass

    def pytest_runtest_logreport(self, report: Any) -> None:
        super().pytest_runtest_logreport(report)
        try:
            node = report.nodeid
            if report.outcome == "failed":
                self.failed.add(node)
            elif report.outcome == "skipped" or hasattr(report, "wasxfail"):
                self.skipped.add(node)
            elif report.outcome == "passed":
                self.case_phases.setdefault(node, set()).add(report.when)
            if report.when == "teardown":
                self.completed.add(node)
            if report.when == "teardown" or report.outcome in {"failed", "skipped"}:
                self.save()
                self.emit()
        except Exception:
            pass

    def pytest_sessionfinish(self, session: Any, exitstatus: object) -> None:
        super().pytest_sessionfinish(session, exitstatus)
        self.emit()


def run(execute: Callable[..., object] | None = None) -> object:
    # Refuse targets outside the exact existing genuine-CI disposable contract.
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    import pytest
    from test_service_authority_tenant import require_service_sql_ci

    try:
        require_service_sql_ci(dict(os.environ))
    except (pytest.skip.Exception, RuntimeError):
        print("tenant_sql_diagnostic_guard_refused")
        return 1
    if execute is None:
        execute = pytest.main
    with tempfile.TemporaryDirectory(prefix="em-tenant-sql-diagnostic-") as directory:
        detail = SqlDetail(Path(directory) / "detail.json")
        try:
            return execute(list(ARGUMENTS), plugins=[detail])
        finally:
            detail.emit()


if __name__ == "__main__":
    raise SystemExit(run())

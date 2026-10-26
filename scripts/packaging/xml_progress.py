"""Numeric-only progress for the fixed installed XML pytest consumer."""

import os
import sys
from pathlib import Path
from typing import Any

from backend_outcome import KEY, Progress


class XmlProgress(Progress):
    first_failure = False

    def pytest_runtest_logstart(self, nodeid: str, location: object) -> None:
        module = sys.modules.get("guest_outcome")
        if module is not None:
            module.reset_case_trace()
        super().pytest_runtest_logstart(nodeid, location)

    def pytest_runtest_logreport(self, report: Any) -> None:
        super().pytest_runtest_logreport(report)
        if report.outcome != "failed" or self.first_failure:
            return
        self.first_failure = True
        if os.environ.get("EM_XML_CASE_OUTCOME_REPORT") != "true":
            return
        try:
            if report.when not in {"setup", "call", "teardown"}:
                raise ValueError("Closed pytest phase required")
            ordinal = self.values["active"]
            if type(ordinal) is not int or not 1 <= ordinal < 1_000_000:
                raise ValueError("Bounded case ordinal required")
            module = sys.modules.get("guest_outcome")
            host, phase = module.case_categories() if module else ("unavailable", "unavailable")
            label = f"case_{ordinal}-{report.when}-host_{host}-phase_{phase}"
            with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="ascii") as output:
                output.write("xml_failure=" + label + "\n")
        except Exception:
            # The original failing pytest report and exit remain authoritative.
            # Absent metadata is explicitly unavailable, never a success label.
            pass


def pytest_configure(config: Any) -> None:
    path = os.environ.get(KEY)
    if path:
        config.pluginmanager.register(XmlProgress(Path(path)), "owned-xml-progress")

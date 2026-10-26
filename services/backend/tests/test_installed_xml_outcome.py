"""Owned shell fixtures test diagnostic propagation, not installed acceptance."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from xml_progress import XmlProgress

ROOT = Path(__file__).resolve().parents[3]
MARKERS = (
    "INSTALLED_CONTROLLED_XML_KEYWORD_REVIEW_EXPORT",
    "INSTALLED_CONTROLLED_XML_DIRECT_URL_REVIEW_EXPORT",
    "INSTALLED_CONTROLLED_XML_POST_OBSERVATION_CRASH_RECOVERY",
    "INSTALLED_CONTROLLED_XML_DELEGATION_REVOKED_DURING_RESPONSE",
    "INSTALLED_AUTHORED_PDF_DIRECT_URL_REVIEW_EXPORT",
    "INSTALLED_AUTHORED_PDF_POST_OBSERVATION_CRASH_RECOVERY",
)
STAGES = ("keyword", "direct_url", "crash_recovery", "revocation", "pdf", "pdf_recovery")


@pytest.mark.parametrize("missing", [None, *range(6)])
@pytest.mark.parametrize("code", [0, 1, 143])
def test_fixed_shell_checks_preserve_exit_and_stage(
    tmp_path: Path, missing: int | None, code: int
) -> None:
    executable = tmp_path / "uv"
    markers = [marker for index, marker in enumerate(MARKERS) if index != missing]
    executable.write_text(
        f"#!{sys.executable}\nimport sys\nprint({chr(10).join(markers)!r})\nsys.exit({code})\n"
    )
    executable.chmod(0o700)
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "scripts/packaging/check_xml_installed.sh"],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(output),
            "EM_BACKEND_OUTCOME_REPORT": "true",
        },
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == (code or int(missing is not None))
    stage = "pytest" if code else "complete" if missing is None else STAGES[missing]
    lines = output.read_text().splitlines()
    assert lines[-1] == "xml_check=" + stage
    assert all(
        line.removeprefix("xml_check=") in {*STAGES, "pytest", "no_skips_warnings", "complete"}
        for line in lines
    )


def test_xml_reporting_retains_guard_and_budgets() -> None:
    from run_xml_integration import CONSUMER_SECONDS, WRAPPER_SECONDS

    assert CONSUMER_SECONDS["installed"] == 900
    assert WRAPPER_SECONDS["installed"] == 1200
    workflow = (ROOT / ".github/workflows/service-runtime.yml").read_text()
    assert "steps.installed-xml-test.outputs.backend_outcome" in workflow
    assert "steps.installed-xml-test.outputs.xml_check" in workflow
    assert 'EM_REQUIRE_XML_INTEGRATION: "synthetic-test-only"' in workflow


def test_check_stage_rejects_arbitrary_values(tmp_path: Path) -> None:
    source = (ROOT / "scripts/packaging/check_xml_installed.sh").read_text()
    function = source[source.index("check_stage() {") : source.index("\ncheck_stage pytest")]
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", "-c", function + '\ncheck_stage "$1"', "owned", "private\nxml_check=complete"],
        env={**os.environ, "EM_BACKEND_OUTCOME_REPORT": "true", "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 1
    assert result.stdout == result.stderr == b""
    assert not output.exists()


@pytest.mark.parametrize("when", ["setup", "call", "teardown"])
def test_first_failed_case_survives_later_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    import guest_outcome as guest
    from operator_ui_protocol import DiagnosticFrame

    output = tmp_path / "output"
    monkeypatch.setenv("EM_XML_CASE_OUTCOME_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    progress = XmlProgress()
    progress.pytest_runtest_logstart("private", None)

    @guest.observed_guest
    def failed() -> None:
        guest.guest_stage("conversation")
        guest.guest_frame(DiagnosticFrame(kind="stage", stage="evidence_review"))
        raise AssertionError("private payload")

    with pytest.raises(AssertionError, match="private payload"):
        failed()
    progress.pytest_runtest_logreport(SimpleNamespace(outcome="failed", when=when))
    expected = f"xml_failure=case_1-{when}-host_conversation-phase_evidence_review\n"
    assert output.read_text() == expected
    progress.pytest_runtest_logstart("later private", None)
    assert guest.case_categories() == ("unavailable", "unavailable")
    progress.pytest_runtest_logreport(SimpleNamespace(outcome="passed", when="call"))
    progress.pytest_runtest_logreport(SimpleNamespace(outcome="failed", when="teardown"))
    assert output.read_text() == expected


@pytest.mark.parametrize("invalid", ["phase", "host", "when", "output"])
def test_invalid_reporting_never_replaces_original_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    import guest_outcome as guest

    output = tmp_path / "output"
    monkeypatch.setenv("EM_XML_CASE_OUTCOME_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output / "missing" if invalid == "output" else output))
    progress = XmlProgress()
    progress.pytest_runtest_logstart("private", None)
    trace = guest.Trace()
    if invalid == "phase":
        trace.phase = "private\nxml_failure=complete"
    if invalid == "host":
        trace.stage = "private"
    monkeypatch.setattr(guest, "_case_trace", trace)
    report = SimpleNamespace(outcome="failed", when="private" if invalid == "when" else "call")
    progress.pytest_runtest_logreport(report)
    assert report.outcome == "failed"
    assert progress.first_failure
    assert not output.exists()


def test_actual_pytest_failure_and_later_success_keep_first_phase(tmp_path: Path) -> None:
    source = tmp_path / "test_owned.py"
    source.write_text(
        "from guest_outcome import observed_guest, guest_stage, guest_frame\n"
        "from operator_ui_protocol import DiagnosticFrame\n"
        "@observed_guest\ndef journey():\n"
        "    guest_stage('conversation')\n"
        "    guest_frame(DiagnosticFrame(kind='stage', stage='evidence_review'))\n"
        "    raise AssertionError('private payload')\n"
        "def test_one():\n    journey()\n"
        "def test_two():\n    pass\n"
    )
    output = tmp_path / "output"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "xml_progress", "-c", "/dev/null", str(source)],
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                str(ROOT / part) for part in ("scripts/packaging", "scripts/isolation")
            ),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "EM_OWNED_BACKEND_PROGRESS": str(tmp_path / "progress.json"),
            "EM_XML_CASE_OUTCOME_REPORT": "true",
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 1
    assert output.read_text() == (
        "xml_failure=case_1-call-host_conversation-phase_evidence_review\n"
    )

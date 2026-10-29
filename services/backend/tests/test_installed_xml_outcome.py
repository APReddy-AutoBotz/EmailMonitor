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
    assert "steps.installed-xml-test.outputs.xml_worker_failure" in workflow
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
    expected = (
        f"xml_failure=case_1-{when}-host_conversation-phase_evidence_review-export_unavailable\n"
    )
    assert output.read_text() == expected
    progress.pytest_runtest_logstart("later private", None)
    assert guest.case_categories() == ("unavailable", "unavailable")
    progress.pytest_runtest_logreport(SimpleNamespace(outcome="passed", when="call"))
    progress.pytest_runtest_logreport(SimpleNamespace(outcome="failed", when="teardown"))
    assert output.read_text() == expected


@pytest.mark.parametrize("stage", ["keyword_worker", "url_worker"])
def test_worker_failure_detail_is_closed_and_preserves_first_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    import guest_outcome as guest
    from operator_ui_protocol import DiagnosticFrame

    output = tmp_path / "output"
    monkeypatch.setenv("EM_XML_CASE_OUTCOME_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    progress = XmlProgress()
    progress.pytest_runtest_logstart("synthetic", None)
    original = TimeoutError("private synthetic value")

    @guest.observed_guest
    def failed() -> None:
        guest.guest_stage("conversation")
        guest.guest_frame(
            DiagnosticFrame(
                kind="failure",
                stage=stage,
                error="TimeoutError",
                reason="installed_login_deadline",
                installed_login_phase="callback_document",
                installed_callback_delivery="asset_verified",
            )
        )
        raise original

    with pytest.raises(TimeoutError) as caught:
        failed()
    assert caught.value is original
    progress.pytest_runtest_logreport(SimpleNamespace(outcome="failed", when="call"))
    assert output.read_text().splitlines() == [
        f"xml_failure=case_1-call-host_conversation-phase_{stage}-export_unavailable",
        "xml_worker_failure=error_TimeoutError-reason_installed_login_deadline-"
        "login_callback_document-callback_asset_verified",
    ]
    progress.pytest_runtest_logstart("later", None)
    progress.pytest_runtest_logreport(SimpleNamespace(outcome="failed", when="call"))
    assert len(output.read_text().splitlines()) == 2
    assert "private" not in output.read_text()


def test_invalid_worker_detail_does_not_replace_original_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import guest_outcome as guest

    output = tmp_path / "output"
    monkeypatch.setenv("EM_XML_CASE_OUTCOME_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    progress = XmlProgress()
    progress.pytest_runtest_logstart("synthetic", None)
    trace = guest.Trace()
    trace.stage, trace.phase, trace.error = "conversation", "keyword_worker", "private\ninjected"
    monkeypatch.setattr(guest, "_case_trace", trace)
    report = SimpleNamespace(outcome="failed", when="call")
    progress.pytest_runtest_logreport(report)
    assert report.outcome == "failed"
    assert not output.exists()


def test_owned_csv_snapshot_is_value_free_and_retains_first_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import guest_outcome as guest
    from operator_ui_protocol import DiagnosticFrame, InstalledExportStep

    output = tmp_path / "output"
    monkeypatch.setenv("EM_XML_CASE_OUTCOME_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    progress = XmlProgress()
    progress.pytest_runtest_logstart("private", None)

    @guest.observed_guest
    def failed() -> None:
        guest.guest_stage("conversation")
        guest.guest_frame(
            DiagnosticFrame(
                kind="failure",
                stage="export_preview",
                error="TimeoutError",
                installed_export_step=InstalledExportStep(phase="ready_wait", format="csv"),
            )
        )
        raise TimeoutError("private detail")

    with pytest.raises(TimeoutError):
        failed()
    guest.record_export_snapshot(
        {
            "publisher_started": True,
            "publisher_alive": False,
            "publisher_stop_requested": True,
            "publisher_failed": True,
            "publisher_completed_pass": True,
            "exports": [
                {
                    "format": "csv",
                    "state": "queued",
                    "attempts": 0,
                    "lease_present": False,
                    "lease_active": False,
                    "pending": True,
                    "confirmed": False,
                    "delivered": False,
                }
            ],
        }
    )
    progress.pytest_runtest_logreport(SimpleNamespace(outcome="failed", when="call"))
    expected = (
        "xml_failure=case_1-call-host_conversation-phase_export_preview-"
        "export_ready_wait.csv-snapshot_p10111.csv_queued.0.00100\n"
    )
    assert output.read_text() == expected
    progress.pytest_runtest_logstart("next private", None)
    progress.pytest_runtest_logreport(SimpleNamespace(outcome="failed", when="call"))
    assert output.read_text() == expected


@pytest.mark.parametrize("invalid", ["extra", "state", "boolean", "attempts", "duplicate"])
def test_owned_export_snapshot_rejects_untrusted_values(invalid: str) -> None:
    import guest_outcome as guest

    row: dict[str, object] = {
        "format": "csv",
        "state": "queued",
        "attempts": 0,
        "lease_present": False,
        "lease_active": False,
        "pending": True,
        "confirmed": False,
        "delivered": False,
    }
    fields: dict[str, object] = {
        "publisher_started": True,
        "publisher_alive": True,
        "publisher_stop_requested": False,
        "publisher_failed": False,
        "publisher_completed_pass": True,
        "exports": [row],
    }
    if invalid == "extra":
        row["secret"] = "must not escape"
    if invalid == "state":
        row["state"] = "secret"
    if invalid == "boolean":
        row["pending"] = "true"
    if invalid == "attempts":
        row["attempts"] = True
    if invalid == "duplicate":
        fields["exports"] = [row, row]
    guest.reset_case_trace()
    guest.record_export_snapshot(fields)
    assert guest.case_export_snapshot() == "unavailable"


def test_snapshot_revalidates_mutation_and_reports_sql_unavailability() -> None:
    import guest_outcome as guest

    fields = {
        "publisher_started": True,
        "publisher_alive": True,
        "publisher_stop_requested": False,
        "publisher_failed": False,
        "publisher_completed_pass": True,
        "exports": "unavailable",
    }
    guest.reset_case_trace()
    guest.record_export_snapshot(fields)
    assert guest.case_export_snapshot() == "p11001.sql_unavailable"
    assert guest._case_export_snapshot is not None
    guest._case_export_snapshot.exports = "private"  # type: ignore[assignment]
    assert guest.case_export_snapshot() == "unavailable"


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
        "xml_failure=case_1-call-host_conversation-phase_evidence_review-export_unavailable\n"
    )


@pytest.mark.parametrize("phase", ["preview_wait", "ready_wait", "download_wait"])
@pytest.mark.parametrize("format_name", [None, "csv", "xlsx"])
def test_existing_export_subphase_is_fixed_and_first_failure_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, format_name: str | None
) -> None:
    import guest_outcome as guest
    from operator_ui_protocol import DiagnosticFrame, InstalledExportStep

    output = tmp_path / "output"
    monkeypatch.setenv("EM_XML_CASE_OUTCOME_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    progress = XmlProgress()
    progress.pytest_runtest_logstart("owned", None)
    original = RuntimeError("synthetic failure")

    @guest.observed_guest
    def failed() -> None:
        guest.guest_stage("conversation")
        guest.guest_frame(
            DiagnosticFrame(
                kind="failure",
                stage="export_preview",
                error="RuntimeError",
                reason="unknown",
                installed_export_step=InstalledExportStep.model_validate(
                    {"phase": phase, "format": format_name}
                ),
            )
        )
        raise original

    with pytest.raises(RuntimeError) as caught:
        failed()
    assert caught.value is original
    progress.pytest_runtest_logreport(SimpleNamespace(outcome="failed", when="call"))
    expected = (
        "xml_failure=case_1-call-host_conversation-phase_export_preview-"
        f"export_{phase}.{format_name or 'none'}"
        + ("-snapshot_unavailable" if phase == "ready_wait" and format_name == "csv" else "")
        + "\n"
    )
    assert output.read_text() == expected
    progress.pytest_runtest_logstart("later", None)
    progress.pytest_runtest_logreport(SimpleNamespace(outcome="failed", when="call"))
    assert output.read_text() == expected


@pytest.mark.parametrize("field", ["phase", "format"])
def test_mutated_export_step_cannot_emit_arbitrary_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    import guest_outcome as guest
    from operator_ui_protocol import InstalledExportStep

    output = tmp_path / "output"
    monkeypatch.setenv("EM_XML_CASE_OUTCOME_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    progress = XmlProgress()
    progress.pytest_runtest_logstart("owned", None)
    trace = guest.Trace()
    trace.phase = "export_preview"
    trace.export = InstalledExportStep.model_construct(phase="preview_wait", format="csv")
    setattr(trace.export, field, "unlisted\nxml_failure=complete")
    monkeypatch.setattr(guest, "_case_trace", trace)
    progress.pytest_runtest_logreport(SimpleNamespace(outcome="failed", when="call"))
    assert progress.first_failure and not output.exists()

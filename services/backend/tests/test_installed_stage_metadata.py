"""Controlled-fake metadata tests; these do not execute installed acceptance."""

import subprocess
import threading
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

import pytest
import test_installed_operator_acceptance as acceptance
from installed_operator_stage import InstalledStage, Stage, report_stage


def test_first_failure_survives_cleanup_stage(tmp_path: Path) -> None:
    stage = InstalledStage()
    stage.enter("api_readiness")
    stage.fail()
    stage.enter("resource_cleanup")
    stage.fail()
    output = tmp_path / "output"
    report_stage(stage, output)
    assert output.read_text() == "stage=api_readiness\n"


@pytest.mark.parametrize("value", ["private-data", "complete\nother=value", "", 1])
def test_unknown_or_injected_stage_refused(value: object, tmp_path: Path) -> None:
    stage = InstalledStage()
    with pytest.raises(ValueError):
        stage.enter(cast(Stage, value))
    stage.failure = cast(Stage, value)
    with pytest.raises(ValueError):
        report_stage(stage, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_original_exception_and_failure_semantics_preserved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original = AssertionError("private test value must never enter metadata")

    def failing(*args: object) -> None:
        stage = cast(InstalledStage, args[2])
        stage.enter("postconditions")
        raise original

    monkeypatch.setattr(acceptance, "installed_journey", failing)
    monkeypatch.setenv("EM_INSTALLED_STAGE_REPORT", "true")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    with pytest.raises(AssertionError) as caught:
        acceptance.test_required_installed_https_operator_journey(None, tmp_path)  # type: ignore[arg-type]
    assert caught.value is original
    assert output.read_text() == "stage=postconditions\n"


def test_reporting_failure_does_not_replace_primary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original = RuntimeError("original")

    def failing(*args: object) -> None:
        raise original

    monkeypatch.setattr(acceptance, "installed_journey", failing)
    monkeypatch.setenv("EM_INSTALLED_STAGE_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "absent" / "output"))
    with pytest.raises(RuntimeError) as caught:
        acceptance.test_required_installed_https_operator_journey(None, tmp_path)  # type: ignore[arg-type]
    assert caught.value is original
    assert original.__notes__ == ["Fixed installed stage reporting failed"]


def test_success_metadata_and_default_no_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def success(*args: object) -> None:
        cast(InstalledStage, args[2]).enter("complete")

    monkeypatch.setattr(acceptance, "installed_journey", success)
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.delenv("EM_INSTALLED_STAGE_REPORT", raising=False)
    acceptance.test_required_installed_https_operator_journey(None, tmp_path)  # type: ignore[arg-type]
    assert not output.exists()
    monkeypatch.setenv("EM_INSTALLED_STAGE_REPORT", "true")
    acceptance.test_required_installed_https_operator_journey(None, tmp_path)  # type: ignore[arg-type]
    assert output.read_text() == "stage=complete\n"


@pytest.mark.parametrize("fails", [False, True])
def test_reuse_stage_reports_separately_and_preserves_original_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fails: bool
) -> None:
    original = TimeoutError("private sentinel")

    def journey(*args: object, **kwargs: object) -> None:
        assert kwargs == {"retained_reuse": True}
        stage = cast(InstalledStage, args[2])
        stage.enter("browser_execution_and_owned_cleanup" if fails else "complete")
        if fails:
            raise original

    monkeypatch.setattr(acceptance, "installed_journey", journey)
    monkeypatch.setenv("EM_INSTALLED_STAGE_REPORT", "true")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    if fails:
        with pytest.raises(TimeoutError) as caught:
            acceptance.test_required_installed_retained_reuse_journey(None, tmp_path)  # type: ignore[arg-type]
        assert caught.value is original
        assert output.read_text() == "reuse_stage=browser_execution_and_owned_cleanup\n"
    else:
        acceptance.test_required_installed_retained_reuse_journey(None, tmp_path)  # type: ignore[arg-type]
        assert output.read_text() == "reuse_stage=complete\n"


def test_reuse_reporting_error_does_not_replace_original(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original = RuntimeError("original")

    def failing(*args: object, **kwargs: object) -> None:
        raise original

    monkeypatch.setattr(acceptance, "installed_journey", failing)
    monkeypatch.setenv("EM_INSTALLED_STAGE_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "absent" / "output"))
    with pytest.raises(RuntimeError) as caught:
        acceptance.test_required_installed_retained_reuse_journey(None, tmp_path)  # type: ignore[arg-type]
    assert caught.value is original
    assert original.__notes__ == ["Fixed installed reuse stage reporting failed"]


@pytest.mark.parametrize("mode", ["queued", "invalid", "unavailable"])
def test_reuse_export_snapshot_is_fixed_and_failure_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    import test_installed_xml_acceptance as xml

    def states(*args: object) -> list[dict[str, object]]:
        if mode == "unavailable":
            raise RuntimeError("private sentinel")
        return [
            {
                "format": "csv" if mode == "queued" else "private sentinel",
                "state": "queued",
                "attempts": 0,
                "lease_present": False,
                "lease_active": False,
                "pending": True,
                "confirmed": False,
                "delivered": False,
            }
        ]

    monkeypatch.setattr(xml, "owned_export_states", states)
    output = tmp_path / "output"
    acceptance.report_reuse_export_failure(
        "private sentinel", uuid4(), uuid4(), None, threading.Event(), False, True, output
    )
    expected = {
        "queued": "p00001.csv_queued.0.00100",
        "invalid": "unavailable",
        "unavailable": "p00001.sql_unavailable",
    }[mode]
    assert output.read_text() == "reuse_export_snapshot=" + expected + "\n"
    assert "private sentinel" not in output.read_text()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (subprocess.TimeoutExpired("private command", 20), "deadline"),
        (RuntimeError("Bounded installed publication receipt missing"), "invalid_receipt"),
        (RuntimeError("private sentinel"), "other"),
    ],
)
def test_publisher_failure_is_closed_and_preserves_first(
    tmp_path: Path, error: Exception, expected: str
) -> None:
    output = tmp_path / "output"
    acceptance.report_publisher_failure(error, output)
    acceptance.report_publisher_failure(RuntimeError("private later failure"), output)
    assert output.read_text() == "installed_publisher_failure=" + expected + "\n"
    assert "private" not in output.read_text()


@pytest.mark.parametrize(
    ("status", "stdout", "stderr", "expected"),
    [
        (1, b"", b"", "exit_nonzero"),
        (0, b"a" * 1025, b"", "stdout_limit"),
        (0, b"", b"a" * 1025, "stderr_limit"),
    ],
)
def test_finite_failure_categories_preserve_exception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: int,
    stdout: bytes,
    stderr: bytes,
    expected: str,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess([], status, stdout, stderr),
    )
    with pytest.raises(RuntimeError, match="^Installed finite service command failed$") as caught:
        acceptance.finite(tmp_path, "publish-once", tmp_path / "private")
    assert vars(caught.value)["_em_finite_category"] == expected
    output = tmp_path / "output"
    acceptance.report_publisher_failure(caught.value, output)
    assert output.read_text() == "installed_publisher_failure=" + expected + "\n"


def test_output_key_is_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        report_stage(
            InstalledStage(),
            tmp_path / "output",
            cast(Literal["stage", "reuse_stage"], "other\ninjected"),
        )
    assert not (tmp_path / "output").exists()

"""Controlled-fake metadata tests; these do not execute installed acceptance."""

from pathlib import Path
from typing import cast

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

"""The browser wrapper reports only exit categories and preserves status."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/isolation/browser_result.sh"


@pytest.mark.parametrize(
    ("code", "category"),
    [
        (0, "exit_zero"),
        (1, "exit_1_to_127"),
        (127, "exit_1_to_127"),
        (128, "exit_128_to_255"),
        (255, "exit_128_to_255"),
    ],
)
def test_exact_child_status_and_fixed_category(tmp_path: Path, code: int, category: str) -> None:
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", str(SCRIPT), sys.executable, "-c", f"raise SystemExit({code})"],
        env={**os.environ, "GITHUB_OUTPUT": str(output)},
        check=False,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == code
    assert output.read_text() == f"browser_outcome={category}\n"
    assert result.stdout == result.stderr == b""


def test_signal_is_reported_honestly_as_high_status(tmp_path: Path) -> None:
    output = tmp_path / "output"
    result = subprocess.run(
        ["bash", str(SCRIPT), "bash", "-c", "kill -TERM $$"],
        env={**os.environ, "GITHUB_OUTPUT": str(output)},
        check=False,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 143
    assert output.read_text() == "browser_outcome=exit_128_to_255\n"


def test_missing_output_file_does_not_change_failure(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), sys.executable, "-c", "raise SystemExit(7)"],
        env={**os.environ, "GITHUB_OUTPUT": str(tmp_path / "missing" / "output")},
        check=False,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 7
    assert result.stderr == b""


def test_workflow_keeps_same_guarded_runner_and_reports_only_category() -> None:
    root = SCRIPT.parents[2]
    workflow = (root / ".github/workflows/browser-isolation.yml").read_text()
    assert (
        "bash scripts/isolation/browser_result.sh uv run --project services/backend "
        "python scripts/isolation/run_browser_acceptance.py" in workflow
    )
    assert "steps.browser-check.outputs.browser_outcome || 'unavailable'" in workflow
    assert "steps.browser-check.outputs.browser_phase || 'unavailable'" in workflow
    assert "steps.browser-check.outcome == 'failure'" in workflow
    assert "timeout-minutes: 20" in workflow


def test_child_output_is_forwarded_without_entering_metadata(tmp_path: Path) -> None:
    output = tmp_path / "output"
    command = (
        "import sys; print('fixture stdout'); "
        "print('fixture stderr', file=sys.stderr); raise SystemExit(9)"
    )
    result = subprocess.run(
        ["bash", str(SCRIPT), sys.executable, "-c", command],
        env={**os.environ, "GITHUB_OUTPUT": str(output)},
        check=False,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 9
    assert result.stdout == b"fixture stdout\n" and result.stderr == b"fixture stderr\n"
    assert output.read_text() == "browser_outcome=exit_1_to_127\n"


@pytest.mark.parametrize(
    "phase",
    [
        "guard",
        "image_build",
        "container_create",
        "configuration",
        "conversation",
        "verification",
        "cleanup",
    ],
)
def test_browser_failure_reports_only_fixed_phase_and_preserves_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    import run_browser_acceptance as runner

    output = tmp_path / "output"
    original = RuntimeError("synthetic private diagnostic")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(runner, "_phase", phase)

    def failure() -> None:
        raise original

    monkeypatch.setattr(runner, "main", failure)
    with pytest.raises(RuntimeError) as caught:
        runner.run()
    assert caught.value is original
    assert output.read_text() == f"browser_phase={phase}\n"


@pytest.mark.parametrize("unavailable", ["invalid", "output"])
def test_browser_phase_failure_cannot_mask_the_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unavailable: str
) -> None:
    import run_browser_acceptance as runner

    output = tmp_path / ("missing/output" if unavailable == "output" else "output")
    original = RuntimeError("synthetic")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(
        runner, "_phase", "private arbitrary" if unavailable == "invalid" else "guard"
    )

    def failure() -> None:
        raise original

    monkeypatch.setattr(runner, "main", failure)
    with pytest.raises(RuntimeError) as caught:
        runner.run()
    assert caught.value is original and not output.exists()


def test_browser_success_does_not_report_failure_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import run_browser_acceptance as runner

    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(runner, "main", lambda: None)
    runner.run()
    assert not output.exists()

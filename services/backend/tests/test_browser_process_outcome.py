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

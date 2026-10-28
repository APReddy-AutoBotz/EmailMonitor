"""Owned synthetic diagnostic checks, not hosted acceptance or a CI simulation."""

import json
import os
import signal
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from backend_outcome import KEY, read_progress, reported
from run_xml_integration import IntegrationRefused, interrupted


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.parametrize("xml_plugin", [False, True])
def test_actual_owned_pytest_counts_and_unchanged_exit(
    tmp_path: Path, fails: bool, xml_plugin: bool
) -> None:
    source = tmp_path / "test_owned.py"
    source.write_text(
        "def test_one():\n    assert " + str(not fails) + "\n\ndef test_two():\n    pass\n"
    )
    output = tmp_path / "output"
    script = """
import os, sys
from pathlib import Path
import pytest
from backend_outcome import KEY, Progress, reported
from run_xml_integration import IntegrationRefused

def action(env):
    args = ["-q", "-c", "/dev/null", "--confcutdir="+sys.argv[1], sys.argv[1]]
    if sys.argv[3] == "True":
        os.environ[KEY] = env[KEY]
        code = pytest.main(["-p", "xml_progress", *args])
    else:
        code = pytest.main(args, plugins=[Progress(Path(env[KEY]))])
    if code:
        error = IntegrationRefused("xml_integration_consumer_failed")
        error.outcome_category = "consumer_exit"
        error.consumer_code = int(code)
        raise error
try:
    reported(action, {"EM_BACKEND_OUTCOME_REPORT":"true", "GITHUB_OUTPUT":sys.argv[2]})
except IntegrationRefused as error:
    raise SystemExit(error.consumer_code)
"""
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), str(output), str(xml_plugin)],
        env={
            **os.environ,
            "PYTHONPATH": str(root / "scripts/packaging"),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        },
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == int(fails)
    category = "test_failure" if fails else "normal"
    assert output.read_text() == (
        f"backend_outcome={category}-exit_{int(fails)}-active_2-completed_2-failed_{int(fails)}-total_2\n"
    )


def test_actual_owned_child_deadline_preserves_exception(tmp_path: Path) -> None:
    output = tmp_path / "output"
    caught = []

    def action(environment: object) -> None:
        try:
            subprocess.run(
                [sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.05, check=True
            )
        except subprocess.TimeoutExpired as error:
            caught.append(error)
            raise

    with pytest.raises(subprocess.TimeoutExpired) as error:
        reported(action, {"EM_BACKEND_OUTCOME_REPORT": "true", "GITHUB_OUTPUT": str(output)})
    assert error.value is caught[0]
    assert output.read_text().startswith("backend_outcome=consumer_deadline-exit_0-")


@pytest.mark.parametrize(
    "kind,label", [(signal.SIGALRM, "wrapper_deadline"), (signal.SIGTERM, "wrapper_signal")]
)
def test_existing_signal_handler_reports_without_changing_refusal(
    tmp_path: Path, kind: int, label: str
) -> None:
    output = tmp_path / "output"
    with pytest.raises(IntegrationRefused, match="^xml_integration_interrupted$"):
        reported(
            lambda _: interrupted(kind, None),
            {"EM_BACKEND_OUTCOME_REPORT": "true", "GITHUB_OUTPUT": str(output)},
        )
    assert output.read_text().startswith(f"backend_outcome={label}-exit_{-kind}-")


@pytest.mark.parametrize(
    "value",
    [{"private": "payload"}, {"active": True, "completed": 0, "failed": 0, "total": 1}, "secret"],
)
def test_progress_accepts_only_bounded_numeric_schema(tmp_path: Path, value: object) -> None:
    path = tmp_path / "progress"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        read_progress(path)


def test_default_path_has_no_diagnostic_effect(tmp_path: Path) -> None:
    environment = {"GITHUB_OUTPUT": str(tmp_path / "output")}
    observed = []
    reported(lambda value: observed.append(value), environment)
    assert observed == [environment]
    assert KEY not in observed[0]
    assert not (tmp_path / "output").exists()


def test_actual_owned_signal_exit_and_temporary_cleanup(tmp_path: Path) -> None:
    output = tmp_path / "output"
    owned = []

    def action(environment: Mapping[str, str]) -> None:
        owned.append(Path(environment[KEY]).parent)
        result = subprocess.run(
            [sys.executable, "-c", "import os,signal; os.kill(os.getpid(), signal.SIGTERM)"],
            timeout=5,
        )
        assert result.returncode == -signal.SIGTERM
        error = IntegrationRefused("xml_integration_consumer_failed")
        error.outcome_category = "consumer_signal"
        error.consumer_code = result.returncode
        raise error

    with pytest.raises(IntegrationRefused, match="^xml_integration_consumer_failed$"):
        reported(action, {"EM_BACKEND_OUTCOME_REPORT": "true", "GITHUB_OUTPUT": str(output)})
    assert output.read_text().startswith("backend_outcome=consumer_signal-exit_-15-")
    assert len(owned) == 1 and not owned[0].exists()


def test_wrapper_timing_reports_preparation_and_consumer_without_consumer_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend_outcome as outcome

    ticks = iter([10.0, 16.9, 40.2])
    monkeypatch.setattr(outcome, "_monotonic", lambda: next(ticks))
    output = tmp_path / "output"
    original = IntegrationRefused("synthetic timeout")
    original.outcome_category = "wrapper_deadline"
    original.consumer_code = -signal.SIGALRM

    def action(environment: Mapping[str, str]) -> None:
        assert KEY in environment
        outcome.wrapper_consumer_started()
        outcome.wrapper_work_finished()
        raise original

    with pytest.raises(IntegrationRefused) as caught:
        reported(action, {"EM_BACKEND_OUTCOME_REPORT": "true", "GITHUB_OUTPUT": str(output)})
    assert caught.value is original
    assert output.read_text() == (
        "backend_outcome=wrapper_deadline-exit_-14-active_0-completed_0-failed_0-total_0"
        "-setup_s_6-work_s_23-work_stage_consumer\n"
    )
    assert outcome._wrapper_timing.get() is None


def test_wrapper_timing_records_failure_before_consumer_and_never_replaces_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backend_outcome as outcome

    ticks = iter([10.0, 12.0])
    monkeypatch.setattr(outcome, "_monotonic", lambda: next(ticks))
    output = tmp_path / "output"
    original = RuntimeError("private synthetic failure")

    def action(_: Mapping[str, str]) -> None:
        outcome.wrapper_work_finished()
        raise original

    with pytest.raises(RuntimeError) as caught:
        reported(action, {"EM_BACKEND_OUTCOME_REPORT": "true", "GITHUB_OUTPUT": str(output)})
    assert caught.value is original
    assert output.read_text().endswith("-setup_s_2-work_s_0-work_stage_preparation\n")
    assert "private" not in output.read_text() and outcome._wrapper_timing.get() is None


@pytest.mark.parametrize("failure_at", [0, 1, 2])
def test_unavailable_wrapper_clock_never_changes_action_or_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_at: int
) -> None:
    import backend_outcome as outcome

    calls = 0

    def clock() -> float:
        nonlocal calls
        point = calls
        calls += 1
        if point == failure_at:
            raise OSError("synthetic clock unavailable")
        return float(point + 1)

    monkeypatch.setattr(outcome, "_monotonic", clock)
    output = tmp_path / "output"
    executed: list[str] = []

    def action(_: Mapping[str, str]) -> None:
        executed.append("work")
        outcome.wrapper_consumer_started()
        outcome.wrapper_work_finished()
        executed.append("cleanup")

    reported(action, {"EM_BACKEND_OUTCOME_REPORT": "true", "GITHUB_OUTPUT": str(output)})
    assert executed == ["work", "cleanup"]
    assert (
        output.read_text()
        == "backend_outcome=normal-exit_0-active_0-completed_0-failed_0-total_0\n"
    )
    assert outcome._wrapper_timing.get() is None

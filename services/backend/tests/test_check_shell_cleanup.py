"""Controlled process doubles prove timeout ownership without starting a shell."""

import os
import signal
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import test_application_check_phases as phases


@pytest.mark.parametrize("already_gone", [False, True])
def test_timeout_kills_only_new_session_and_preserves_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, already_gone: bool
) -> None:
    process = MagicMock()
    process.__enter__.return_value = process
    process.pid = 12345
    original = subprocess.TimeoutExpired(["authored-shell"], 10)
    process.communicate.side_effect = [original, ("", "")]
    launch = MagicMock(return_value=process)
    killed = []

    def killpg(pid: int, sig: signal.Signals) -> None:
        killed.append((pid, sig))
        if already_gone:
            raise ProcessLookupError()

    monkeypatch.setattr(subprocess, "Popen", launch)
    monkeypatch.setattr(os, "killpg", killpg)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        phases.run_owned_shell(["authored-shell"], cwd=tmp_path, env={}, timeout=10)
    assert caught.value is original
    assert launch.call_args.kwargs["start_new_session"] is True
    assert killed == [(12345, signal.SIGKILL)]
    assert [call.kwargs for call in process.communicate.call_args_list] == [
        {"timeout": 10},
        {"timeout": 2},
    ]


def test_normal_exit_preserves_status_and_output_without_group_signal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = MagicMock()
    process.__enter__.return_value = process
    process.communicate.return_value = ("authored stdout", "authored stderr")
    process.returncode = 9
    monkeypatch.setattr(subprocess, "Popen", MagicMock(return_value=process))
    monkeypatch.setattr(os, "killpg", lambda *args: pytest.fail("No signal on exit"))
    result = phases.run_owned_shell(["authored-shell"], cwd=tmp_path, env={}, timeout=10)
    assert (result.returncode, result.stdout, result.stderr) == (
        9,
        "authored stdout",
        "authored stderr",
    )


@pytest.mark.parametrize("failure", ["signal", "reap"])
def test_cleanup_refusal_preserves_original_timeout_and_records_uncertainty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    process = MagicMock()
    process.pid = 12345
    original = subprocess.TimeoutExpired(["authored-shell"], 10)
    process.communicate.side_effect = [
        original,
        subprocess.TimeoutExpired(["authored-reap"], 2) if failure == "reap" else ("", ""),
    ]
    monkeypatch.setattr(subprocess, "Popen", MagicMock(return_value=process))
    signals: list[tuple[int, signal.Signals]] = []

    def signal_owned(pid: int, sig: signal.Signals) -> None:
        signals.append((pid, sig))
        if failure == "signal":
            raise PermissionError("private detail")

    monkeypatch.setattr(os, "killpg", signal_owned)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        phases.run_owned_shell(["authored-shell"], cwd=tmp_path, env={}, timeout=10)
    assert caught.value is original
    assert signals == [(12345, signal.SIGKILL)]
    assert len(original.__notes__) == 1
    assert "cleanup is uncertain" in original.__notes__[0]
    assert "private detail" not in original.__notes__[0]

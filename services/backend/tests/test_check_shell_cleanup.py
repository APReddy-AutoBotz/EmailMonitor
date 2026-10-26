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

"""Pure failure visibility regression; no Docker command is executed."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from run_parser_acceptance import docker


def test_parser_docker_failure_diagnostics_are_bounded_and_remain_failure() -> None:
    error = subprocess.CalledProcessError(
        1, ["docker", "build"], output="o" * 10000, stderr="e" * 10000
    )
    with (
        patch("run_parser_acceptance.subprocess.run", side_effect=error),
        pytest.raises(RuntimeError) as raised,
    ):
        docker("build")
    evidence = json.loads(str(raised.value).split(": ", 1)[1])
    assert evidence == {
        "operation": "build",
        "returncode": 1,
        "stdout": "o" * 4096,
        "stderr": "e" * 4096,
    }


@pytest.mark.parametrize("stage", ["build", "parser", "oom", "complete"])
def test_parser_stage_receipt_preserves_original_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stage: str
) -> None:
    import run_parser_acceptance as parser

    output = tmp_path / "output"
    monkeypatch.setenv("EM_PARSER_STAGE_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    failure = RuntimeError("synthetic failure")
    calls: list[str] = []

    def build(*_: object, **__: object) -> None:
        calls.append("build")
        if stage == "build":
            raise failure

    def run(*_: object, **kwargs: object) -> dict[str, object]:
        current = "oom" if kwargs.get("expected_oom") else "parser"
        calls.append(current)
        if stage == current:
            raise failure
        return {"oom_killed": True, "exit_code": 137}

    monkeypatch.setattr(parser, "docker", build)
    monkeypatch.setattr(parser, "run", run)
    if stage == "complete":
        parser.execute(tmp_path)
    else:
        with pytest.raises(RuntimeError) as caught:
            parser.execute(tmp_path)
        assert caught.value is failure
    expected = {
        "build": ["build"],
        "parser": ["build", "parser"],
        "oom": ["build", "parser", "oom"],
        "complete": ["build", "parser", "oom"],
    }
    assert calls == expected[stage]
    assert output.read_text() == "parser_stage=" + stage + "\n"


def test_parser_stage_report_rejects_unknown_values_and_reporting_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import run_parser_acceptance as parser

    output = tmp_path / "output"
    monkeypatch.setenv("EM_PARSER_STAGE_REPORT", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    parser.report_stage("untrusted value")
    assert not output.exists()
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path))
    parser.report_stage("build")  # A reporting error cannot replace the primary result.


def test_browser_artifact_completion_requires_both_actual_callbacks() -> None:
    import asyncio

    from browser_acceptance import wait_artifact_completion

    async def cases() -> None:
        popup, download = asyncio.Event(), asyncio.Event()
        asyncio.get_running_loop().call_soon(popup.set)
        asyncio.get_running_loop().call_soon(download.set)
        await wait_artifact_completion(popup, download)
        assert popup.is_set() and download.is_set()
        with pytest.raises(TimeoutError):
            await wait_artifact_completion(asyncio.Event(), asyncio.Event(), 0.001)
        with pytest.raises(ValueError):
            await wait_artifact_completion(popup, download, 4)

    asyncio.run(cases())

"""Pure failure visibility regression; no Docker command is executed."""

import json
import subprocess
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

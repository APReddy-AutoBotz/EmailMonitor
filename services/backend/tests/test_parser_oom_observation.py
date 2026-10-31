"""Pure bounded daemon-state observation tests; never run containers."""

import json
import subprocess
import time
from typing import Any

import pytest
import run_parser_acceptance as parser


@pytest.mark.parametrize("late", [True, False])
def test_separate_oom_event_is_observed_without_inference(
    monkeypatch: pytest.MonkeyPatch, late: bool
) -> None:
    calls = []
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(time, "sleep", lambda seconds: calls.append(seconds))

    def inspect(*args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert args == ("inspect", "a" * 64) and kwargs == {"timeout": 2}
        return subprocess.CompletedProcess(
            args, 0, json.dumps([{"State": {"Running": False, "OOMKilled": late, "ExitCode": 137}}])
        )

    monkeypatch.setattr(parser, "docker", inspect)
    result = parser.settled_oom("a" * 64, {"Running": False, "OOMKilled": False, "ExitCode": 137})
    assert result["OOMKilled"] is late
    assert len(calls) == (1 if late else 10)


@pytest.mark.parametrize(
    "state",
    [
        {"Running": False, "OOMKilled": True, "ExitCode": 137},
        {"Running": False, "OOMKilled": False, "ExitCode": 137},
        {"Running": False, "OOMKilled": True, "ExitCode": 1},
        {"Running": True, "OOMKilled": True, "ExitCode": 137},
    ],
)
def test_deadline_preserves_observed_fields(
    monkeypatch: pytest.MonkeyPatch, state: dict[str, object]
) -> None:
    times = iter((0.0, 3.0))
    monkeypatch.setattr(time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        parser, "docker", lambda *args, **kwargs: pytest.fail("No call after deadline")
    )
    assert parser.settled_oom("a" * 64, state) == state


@pytest.mark.parametrize(
    ("state", "accepted"),
    [
        ({"Running": False, "OOMKilled": True, "ExitCode": 137}, True),
        ({"Running": False, "OOMKilled": False, "ExitCode": 137}, False),
        ({"Running": False, "OOMKilled": True, "ExitCode": 1}, False),
        ({"Running": True, "OOMKilled": True, "ExitCode": 137}, False),
    ],
)
def test_memory_proof_requires_all_actual_state_fields_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, state: dict[str, object], accepted: bool
) -> None:
    identifier = "a" * 64
    host = {
        "NetworkMode": "none",
        "Privileged": False,
        "CapAdd": None,
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges"],
        "ReadonlyRootfs": True,
        "Binds": None,
        "Memory": 134217728,
        "MemorySwap": 134217728,
        "PidsLimit": 32,
        "NanoCpus": 500000000,
    }
    operations: list[str] = []

    def docker(*args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        operations.append(args[0])
        if args[0] == "create":
            return subprocess.CompletedProcess(args, 0, identifier, "")
        if args[0] == "inspect":
            return subprocess.CompletedProcess(
                args, 0, json.dumps([{"HostConfig": host, "State": state}]), ""
            )
        assert args == ("rm", "--force", identifier)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(parser, "docker", docker)
    monkeypatch.setattr(parser, "settled_oom", lambda _identifier, observed: observed)
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "", "")
    )
    if accepted:
        assert parser.run(["synthetic"], expected_oom=True) == {
            "oom_killed": True,
            "exit_code": 137,
        }
    else:
        with pytest.raises(RuntimeError, match="Actual memory enforcement not established"):
            parser.run(["synthetic"], expected_oom=True)
    assert operations == ["create", "inspect", "inspect", "rm"]

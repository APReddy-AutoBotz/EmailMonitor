"""Pure CI initialization contracts: all subprocess/time/state operations are replaced."""

import json
import subprocess
import time
from pathlib import Path

import initialize_ci_ipv6 as setup
import pytest


@pytest.fixture
def approved(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "RUNNER_OS": "Linux",
        "EM_REQUIRE_CONTROLLED_NETWORK": "true",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize(
    "key", ["GITHUB_ACTIONS", "RUNNER_ENVIRONMENT", "RUNNER_OS", "EM_REQUIRE_CONTROLLED_NETWORK"]
)
def test_unapproved_environment_refuses_before_read_or_command(
    approved: None, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    monkeypatch.delenv(key)

    def unexpected() -> dict[str, int]:
        pytest.fail("Initialization read before environment guard")

    monkeypatch.setattr(setup, "values", unexpected)
    with pytest.raises(RuntimeError, match="Approved disposable"):
        setup.initialize()


@pytest.mark.parametrize("initial", [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_only_exact_approved_settings_are_changed_and_values_recorded(
    approved: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    initial: tuple[int, int],
) -> None:
    before = dict(zip(setup.SETTINGS, initial, strict=True))
    replies = iter([before, dict.fromkeys(setup.SETTINGS, 1)])
    calls: list[list[str]] = []

    def command(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        assert kwargs["check"] is True and kwargs["timeout"] == 10
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(setup, "values", lambda: next(replies))
    monkeypatch.setattr(setup, "state_digest", lambda: "fixed-state-digest")
    monkeypatch.setattr(subprocess, "run", command)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    setup.initialize()
    assert calls == [
        ["sudo", "sysctl", "-w", setting + "=1"]
        for setting in setup.SETTINGS
        if before[setting] == 0
    ]
    evidence = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert evidence[0]["ipv6_initialization_before"] == before
    assert evidence[1]["ipv6_initialization_after"] == dict.fromkeys(setup.SETTINGS, 1)


def test_failed_value_verification_and_unsettled_state_refuse(
    approved: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(setup, "values", lambda: dict.fromkeys(setup.SETTINGS, 1))
    monkeypatch.setattr(time, "sleep", lambda _: None)
    clock = iter(range(100))
    monkeypatch.setattr(time, "monotonic", lambda: float(next(clock)))
    serial = iter(range(100))
    monkeypatch.setattr(setup, "state_digest", lambda: str(next(serial)))
    with pytest.raises(RuntimeError, match="did not settle"):
        setup.initialize()
    replies = iter([dict.fromkeys(setup.SETTINGS, 1), dict.fromkeys(setup.SETTINGS, 0)])
    monkeypatch.setattr(setup, "values", lambda: next(replies))
    with pytest.raises(RuntimeError, match="did not establish"):
        setup.initialize()


@pytest.mark.parametrize("invalid", ["2\n", "", "1\n0\n"])
def test_value_reader_has_fixed_paths_and_rejects_malformed_evidence(
    monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    def read(path: Path, **kwargs: object) -> str:
        assert str(path) in {
            "/proc/sys/net/ipv6/conf/all/forwarding",
            "/proc/sys/net/ipv6/conf/default/forwarding",
        }
        return invalid

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(RuntimeError, match="Unexpected existing"):
        setup.values()


def test_workflow_initializes_before_strict_acceptance_only() -> None:
    workflow = Path(".github/workflows/transport-isolation.yml").read_text()
    assert workflow.count("python scripts/isolation/initialize_ci_ipv6.py") == 1
    assert workflow.index("initialize_ci_ipv6.py") < workflow.index("test_transport_acceptance.py")
    assert "12 passed" in workflow and "[0-9]+ skipped|[0-9]+ warnings?" in workflow


def test_state_evidence_uses_only_bounded_read_only_ip_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def command(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        assert kwargs["check"] is True and kwargs["timeout"] == 5
        return subprocess.CompletedProcess(args, 0, "[]", "")

    monkeypatch.setattr(subprocess, "run", command)
    assert len(setup.state_digest()) == 64
    assert calls == [
        ["ip", "-j", "address", "show"],
        ["ip", "-j", "-4", "route", "show", "table", "all"],
        ["ip", "-j", "-6", "route", "show", "table", "all"],
        ["ip", "-j", "-4", "rule", "show"],
        ["ip", "-j", "-6", "rule", "show"],
    ]


def test_initialization_command_failure_stops_without_after_evidence(
    approved: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(setup, "values", lambda: dict.fromkeys(setup.SETTINGS, 0))
    monkeypatch.setattr(setup, "state_digest", lambda: "fixed-state-digest")
    calls: list[list[str]] = []

    def denied(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "run", denied)
    with pytest.raises(subprocess.CalledProcessError):
        setup.initialize()
    assert calls == [["sudo", "sysctl", "-w", setup.SETTINGS[0] + "=1"]]
    assert "ipv6_initialization_after" not in capsys.readouterr().out

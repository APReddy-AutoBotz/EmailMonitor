"""Synthetic fixed-output guest contract; does not start Docker or a browser."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import run_capture_pixel_regression as runner

from emailmonitor.fetching.safety import FetchDenied

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "scripts/isolation/seccomp-browser.json"


def guest() -> dict[str, Any]:
    return {
        "Image": "sha256:test",
        "Config": {
            "Labels": {runner.OWNER_LABEL: "owner"},
            "User": "1000:1000",
            "Cmd": runner.COMMAND,
            "Env": [],
            "Tty": False,
            "OpenStdin": False,
            "Volumes": None,
        },
        "HostConfig": {
            "NetworkMode": "none",
            "Privileged": False,
            "CapAdd": None,
            "CapDrop": ["ALL"],
            "ReadonlyRootfs": True,
            "Binds": None,
            "IpcMode": "private",
            "PidMode": "private",
            "Memory": 536870912,
            "MemorySwap": 536870912,
            "NanoCpus": 1000000000,
            "PidsLimit": 128,
            "ShmSize": 134217728,
            "PortBindings": {},
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=256m"},
            "LogConfig": {"Type": "none"},
            "SecurityOpt": ["no-new-privileges", "seccomp=" + PROFILE.read_text()],
        },
        "NetworkSettings": {"Networks": {"none": {}}, "Ports": {}},
        "Mounts": [],
        "State": {"Running": False, "OOMKilled": False, "ExitCode": 0},
    }


def test_guest_accepts_exact_profile_and_refuses_exfiltration_or_relaxation() -> None:
    valid = guest()
    runner.validate_guest(valid, "sha256:test", "owner", PROFILE)
    mutations = [
        ("Config", "User", "0:0"),
        ("Config", "Cmd", ["sh"]),
        ("Config", "Env", ["HTTP_PROXY=secret"]),
        ("HostConfig", "NetworkMode", "bridge"),
        ("HostConfig", "Binds", ["/:/host"]),
        ("HostConfig", "LogConfig", {"Type": "json-file"}),
        ("HostConfig", "ReadonlyRootfs", False),
        ("HostConfig", "CapDrop", []),
        ("HostConfig", "SecurityOpt", ["no-new-privileges"]),
        ("HostConfig", "Memory", 1073741824),
        ("HostConfig", "NanoCpus", 2000000000),
        ("HostConfig", "PidsLimit", 256),
    ]
    for section, field, value in mutations:
        changed = copy.deepcopy(valid)
        changed[section][field] = value
        with pytest.raises((RuntimeError, FetchDenied)):
            runner.validate_guest(changed, "sha256:test", "owner", PROFILE)


def test_source_workflow_is_branch_only_and_has_no_artifact_delivery() -> None:
    workflow = (ROOT / ".github/workflows/capture-pixel-regression.yml").read_text()
    assert "branches: [codex/capture-pixel-regression-20261102]" in workflow
    assert "pull_request:" not in workflow and "workflow_dispatch:" not in workflow
    assert "upload-artifact" not in workflow and "EM_OPERATOR_CAPTURE" not in workflow
    assert "a6da31194cb48228a7927d2313f5429d317593a4" in workflow
    assert "c384bd4b77ea0996d3536acb4b0394ddbf27c138" in workflow
    assert "git diff --quiet" in workflow
    dockerfile = (ROOT / "scripts/isolation/Dockerfile.capture-pixel").read_text()
    assert "sha256:96b39581c89131729a7ecb8d532314af54c7f9bcc7a61fe15c7a9e77602acf59" in dockerfile
    assert "test_operator_capture_pixels.py" in dockerfile


def test_failure_output_is_fixed_and_does_not_echo_exception(monkeypatch: Any, capsys: Any) -> None:
    def fail() -> None:
        raise RuntimeError("private synthetic marker")

    monkeypatch.setattr(runner, "run", fail)
    with pytest.raises(SystemExit) as stopped:
        runner.main()
    assert stopped.value.code == 1
    assert capsys.readouterr().out == "capture_pixel_result=failed\n"


def test_owned_resources_cleaned_and_guest_success_verified(monkeypatch: Any) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REF", runner.BRANCH)
    monkeypatch.setattr(runner.secrets, "token_hex", lambda _: "owner")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(runner, "quiet_docker", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(
        runner,
        "resource",
        lambda kind, name: (
            {"Id": "sha256:test", "Config": {"Labels": {runner.OWNER_LABEL: "owner"}}}
            if kind == "image"
            else guest()
        ),
    )
    removed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        runner, "remove_owned", lambda kind, name, owner: removed.append((kind, owner))
    )
    runner.run()
    assert [call[0] for call in calls] == ["build", "create", "start", "wait"]
    assert ("container", "owner") in removed and ("image", "owner") in removed
    create = calls[1]
    assert "--log-driver=none" in create and "--network=none" in create
    assert "--cap-drop=ALL" in create and "--read-only" in create
    assert json.loads(PROFILE.read_text())


def test_unapproved_environment_never_creates_resources(monkeypatch: Any) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(
        runner, "quiet_docker", lambda *args, **kwargs: pytest.fail("Docker called")
    )
    with pytest.raises(RuntimeError, match="capture_pixel_ci_refused"):
        runner.run()


def test_cleanup_uncertainty_is_reported_without_exception_details(
    monkeypatch: Any, capsys: Any
) -> None:
    def fail() -> None:
        raise RuntimeError("capture_pixel_cleanup_uncertain")

    monkeypatch.setattr(runner, "run", fail)
    with pytest.raises(SystemExit):
        runner.main()
    assert capsys.readouterr().out == "capture_pixel_result=cleanup_uncertain\n"


def test_cleanup_attempted_when_daemon_create_fails(monkeypatch: Any) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REF", runner.BRANCH)
    monkeypatch.setattr(runner.secrets, "token_hex", lambda _: "owner")

    def docker(*args: str, **kwargs: Any) -> None:
        if args[0] == "create":
            raise RuntimeError("sensitive Docker error")

    monkeypatch.setattr(runner, "quiet_docker", docker)
    monkeypatch.setattr(
        runner,
        "resource",
        lambda kind, name: {
            "Id": "sha256:test",
            "Config": {"Labels": {runner.OWNER_LABEL: "owner"}},
        },
    )
    removed: list[str] = []
    monkeypatch.setattr(runner, "remove_owned", lambda kind, name, owner: removed.append(kind))
    with pytest.raises(RuntimeError, match="^capture_pixel_cleanup_uncertain$"):
        runner.run()
    assert removed == ["container", "image"]

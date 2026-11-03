"""Synthetic fixed-output guest contract; does not start Docker or a browser."""

import copy
import hashlib
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
    assert runner.COMMAND == [
        "python",
        "-c",
        "from test_operator_capture_pixels import "
        "test_actual_sandboxed_chromium_redacts_temporarily_exposed_synthetic_values as run; run()",
    ]
    assert "branches: [codex/capture-pixel-regression-20261102]" in workflow
    assert "pull_request:" not in workflow and "workflow_dispatch:" not in workflow
    assert "upload-artifact" not in workflow and "EM_OPERATOR_CAPTURE" not in workflow
    assert "06c78c9f1271a02e6d6f52d43d9ad8d0b8e95ba4" in workflow
    assert "8f5bafd1f7ad1e5df8f311c0b37452b945035316" in workflow
    assert "git diff --quiet" in workflow
    lines = workflow.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "done <<'BLOBS'")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "BLOBS")
    pins = [line.strip() for line in lines[start + 1 : end]]
    for path in (
        "scripts/isolation/operator_capture.py",
        "scripts/isolation/test_operator_capture_pixels.py",
        "services/backend/tests/test_operator_capture.py",
    ):
        content = (ROOT / path).read_bytes()
        blob = b"blob " + str(len(content)).encode("ascii") + b"\0" + content
        digest = hashlib.sha1(blob, usedforsecurity=False).hexdigest()
        assert pins.count(f"{digest} {path}") == 1
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
    assert capsys.readouterr().out == (
        "capture_focus_result=failed\ncapture_focus_phase=admission\n"
    )


@pytest.mark.parametrize("phase", sorted(runner.FAILURE_PHASES))
def test_failure_phase_is_fixed_and_contains_no_error_detail(
    monkeypatch: Any, capsys: Any, phase: str
) -> None:
    def fail() -> None:
        runner.FAILURE_PHASE.set(phase)
        raise RuntimeError("private synthetic marker")

    monkeypatch.setattr(runner, "run", fail)
    with pytest.raises(SystemExit) as stopped:
        runner.main()
    assert stopped.value.code == 1
    assert capsys.readouterr().out == (
        f"capture_focus_result=failed\ncapture_focus_phase={phase}\n"
    )


def test_unknown_failure_phase_is_not_emitted(monkeypatch: Any, capsys: Any) -> None:
    def fail() -> None:
        runner.FAILURE_PHASE.set("private synthetic marker")
        raise RuntimeError("another private synthetic marker")

    monkeypatch.setattr(runner, "run", fail)
    with pytest.raises(SystemExit) as stopped:
        runner.main()
    assert stopped.value.code == 1
    assert capsys.readouterr().out == (
        "capture_focus_result=failed\ncapture_focus_phase=unavailable\n"
    )


def test_output_failure_cannot_chain_the_triggering_exception(monkeypatch: Any) -> None:
    def fail() -> None:
        raise RuntimeError("private synthetic marker")

    calls: list[str] = []

    def failed_output(value: str) -> None:
        calls.append(value)
        raise BrokenPipeError("output unavailable")

    monkeypatch.setattr(runner, "run", fail)
    monkeypatch.setattr(runner, "print", failed_output, raising=False)
    with pytest.raises(BrokenPipeError) as stopped:
        runner.main()
    assert calls == ["capture_focus_result=failed\ncapture_focus_phase=admission"]
    assert stopped.value.__context__ is None


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
    assert capsys.readouterr().out == "capture_focus_result=cleanup_uncertain\n"


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


def test_guest_failure_records_outcome_without_changing_cleanup_or_error(monkeypatch: Any) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REF", runner.BRANCH)
    monkeypatch.setattr(runner.secrets, "token_hex", lambda _: "owner")
    monkeypatch.setattr(runner, "quiet_docker", lambda *args, **kwargs: None)
    failing_guest = guest()
    failing_guest["State"]["ExitCode"] = 1
    monkeypatch.setattr(
        runner,
        "resource",
        lambda kind, name: (
            {"Id": "sha256:test", "Config": {"Labels": {runner.OWNER_LABEL: "owner"}}}
            if kind == "image"
            else failing_guest
        ),
    )
    removed: list[str] = []
    monkeypatch.setattr(runner, "remove_owned", lambda kind, name, owner: removed.append(kind))
    with pytest.raises(RuntimeError, match="^capture_pixel_test_refused$"):
        runner.run()
    assert runner.FAILURE_PHASE.get() == "guest_status"
    assert removed == ["container", "image"]


@pytest.mark.parametrize("failure", ["image_inspection", "guest_preflight", "wait"])
def test_actual_failure_stage_and_cleanup_are_preserved(monkeypatch: Any, failure: str) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REF", runner.BRANCH)
    monkeypatch.setattr(runner.secrets, "token_hex", lambda _: "owner")
    marker = RuntimeError("private synthetic marker")

    def docker(*args: str, **kwargs: Any) -> None:
        if failure == "wait" and args[0] == "wait":
            raise marker

    def inspect(kind: str, name: str) -> dict[str, Any]:
        if kind == "image":
            if failure == "image_inspection":
                raise marker
            return {"Id": "sha256:test", "Config": {"Labels": {runner.OWNER_LABEL: "owner"}}}
        if failure == "guest_preflight":
            raise marker
        return guest()

    monkeypatch.setattr(runner, "quiet_docker", docker)
    monkeypatch.setattr(runner, "resource", inspect)
    removed: list[str] = []
    monkeypatch.setattr(runner, "remove_owned", lambda kind, name, owner: removed.append(kind))
    with pytest.raises(RuntimeError) as error:
        runner.run()
    assert error.value is marker
    assert runner.FAILURE_PHASE.get() == failure
    assert removed == ["container", "image"]

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
    assert "b1979d1a21fc063fbe723f70695965b096a723f5" in workflow
    assert "e1852716619cdda465aaa838d0cc17f810e7c85a" in workflow
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


def test_diagnostic_emits_only_allowlisted_failure_categories(
    monkeypatch: Any, capsys: Any
) -> None:
    import capture_pixel_diagnostic as diagnostic

    assert diagnostic.category(ValueError("capture_state_focus")) == 24
    assert diagnostic.category(RuntimeError("Synthetic focus overlap unavailable")) == 27
    assert diagnostic.category(RuntimeError("private detail")) == diagnostic.UNKNOWN
    assert diagnostic.category(RuntimeError({"private": "detail"})) == diagnostic.UNKNOWN
    assert diagnostic.category(RuntimeError("Synthetic refusal phase refused"), "removed") == 61
    assert diagnostic.category(RuntimeError("Synthetic focus refusal missing"), "wrong_text") == 69
    assert diagnostic.category(RuntimeError("Synthetic refusal phase refused"), "private") == 37

    def fail() -> None:
        raise RuntimeError("capture_pixel_stage_27")

    monkeypatch.setattr(runner, "run", fail)
    with pytest.raises(SystemExit):
        runner.main()
    assert capsys.readouterr().out == "capture_pixel_result=stage_27\n"


def test_arbitrary_error_arguments_never_escape(monkeypatch: Any, capsys: Any) -> None:
    def fail() -> None:
        raise RuntimeError({"private": "detail"})

    monkeypatch.setattr(runner, "run", fail)
    with pytest.raises(SystemExit):
        runner.main()
    assert capsys.readouterr().out == "capture_pixel_result=failed\n"


def test_diagnostic_wrapper_preserves_failure_and_restores_target(monkeypatch: Any) -> None:
    import asyncio

    import capture_pixel_diagnostic as diagnostic

    async def fail() -> None:
        raise ValueError("capture_state_focus")

    monkeypatch.setattr(diagnostic.target, "exercise", fail)
    monkeypatch.setattr(
        diagnostic.target,
        "test_actual_sandboxed_chromium_redacts_temporarily_exposed_synthetic_values",
        lambda: asyncio.run(diagnostic.target.exercise()),
    )
    with pytest.raises(SystemExit) as stopped:
        diagnostic.run()
    assert stopped.value.code == 24
    assert diagnostic.target.exercise is fail

    async def success() -> None:
        return None

    monkeypatch.setattr(diagnostic.target, "exercise", success)
    diagnostic.run()
    assert diagnostic.target.exercise is success

    def false_success() -> None:
        raise SystemExit(0)

    monkeypatch.setattr(
        diagnostic.target,
        "test_actual_sandboxed_chromium_redacts_temporarily_exposed_synthetic_values",
        false_success,
    )
    with pytest.raises(SystemExit) as stopped:
        diagnostic.run()
    assert stopped.value.code == diagnostic.UNKNOWN
    assert diagnostic.target.exercise is success


@pytest.mark.parametrize(
    ("code", "reason"), [(27, "capture_pixel_stage_27"), (58, "capture_pixel_test_refused")]
)
def test_guest_exit_category_and_cleanup(monkeypatch: Any, code: int, reason: str) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REF", runner.BRANCH)
    monkeypatch.setattr(runner.secrets, "token_hex", lambda _: "owner")
    monkeypatch.setattr(runner, "quiet_docker", lambda *args, **kwargs: None)
    value = guest()
    value["State"]["ExitCode"] = code
    monkeypatch.setattr(
        runner,
        "resource",
        lambda kind, name: (
            {"Id": "sha256:test", "Config": {"Labels": {runner.OWNER_LABEL: "owner"}}}
            if kind == "image"
            else value
        ),
    )
    removed: list[str] = []
    monkeypatch.setattr(runner, "remove_owned", lambda kind, name, owner: removed.append(kind))
    with pytest.raises(RuntimeError, match="^" + reason + "$"):
        runner.run()
    assert removed == ["container", "image"]


@pytest.mark.parametrize(
    ("filename", "fault_expression", "expected"),
    [
        ("/app/test_operator_capture_pixels.py", "'removed'", 61),
        ("/tmp/other.py", "'removed'", 37),
        ("/app/test_operator_capture_pixels.py", "{'secret': 'value'}", 37),
    ],
)
def test_fault_attribution_uses_only_the_exact_synthetic_exercise_frame(
    monkeypatch: Any, capsys: Any, filename: str, fault_expression: str, expected: int
) -> None:
    import asyncio

    import capture_pixel_diagnostic as diagnostic

    namespace: dict[str, Any] = {}
    source = (
        "async def exercise():\n"
        f"    fault = {fault_expression}\n"
        "    private = 'synthetic private marker'\n"
        "    raise RuntimeError('Synthetic refusal phase refused')\n"
    )
    exec(compile(source, filename, "exec"), namespace)  # noqa: S102 - fixed synthetic source
    fake = namespace["exercise"]
    monkeypatch.setattr(diagnostic.target, "exercise", fake)
    monkeypatch.setattr(
        diagnostic.target,
        "test_actual_sandboxed_chromium_redacts_temporarily_exposed_synthetic_values",
        lambda: asyncio.run(diagnostic.target.exercise()),
    )
    with pytest.raises(SystemExit) as stopped:
        diagnostic.run()
    assert stopped.value.code == expected
    assert diagnostic.target.exercise is fake
    output = capsys.readouterr()
    assert output.out == "" and output.err == ""

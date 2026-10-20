"""Pure service packaging contracts; mocked Docker never establishes image acceptance."""

import ast
import copy
import json
import os
import platform
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
import run_service_acceptance as runner
import service_probe

from artifacts import PackagingRefused

OWNER = "a" * 32
IMAGE = "sha256:" + "b" * 64
ENVIRONMENT = [
    "PATH=/opt/emailmonitor/services/backend/.venv/bin:/usr/local/bin:/usr/bin:/bin",
    "LANG=C.UTF-8",
    "PYTHONPATH=/opt/emailmonitor/services/backend/src",
    "PYTHONDONTWRITEBYTECODE=1",
]


def record(probe: str | None = None) -> dict[str, Any]:
    return {
        "Id": IMAGE,
        "Image": IMAGE,
        "Config": {
            "Labels": {runner.LABEL: OWNER},
            "User": "65532:65532",
            "Env": ENVIRONMENT,
            "Entrypoint": runner.ENTRYPOINT if probe is None else ["python"],
            "Cmd": ["--help"] if probe is None else ["-c", probe],
            "WorkingDir": "/opt/emailmonitor",
            "Volumes": None,
            "OpenStdin": False,
            "Tty": False,
        },
        "HostConfig": {
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
            "PortBindings": {},
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=16m"},
            "Mounts": None,
            "Devices": [],
            "DeviceRequests": None,
            "PidMode": "",
            "IpcMode": "private",
            "PublishAllPorts": False,
            "Ulimits": [
                {"Name": "nofile", "Hard": 64, "Soft": 64},
                {"Name": "core", "Hard": 0, "Soft": 0},
            ],
        },
        "Mounts": [{"Type": "tmpfs", "Destination": "/tmp"}],
        "State": {
            "Status": "exited",
            "Running": False,
            "Paused": False,
            "Restarting": False,
            "ExitCode": 0,
            "OOMKilled": False,
            "Error": "",
        },
    }


def test_actual_recipe_is_pinned_locked_and_closed() -> None:
    recipe = (runner.ROOT / "scripts/packaging/ServiceRuntime.Dockerfile").read_bytes()
    runner.validate_dockerfile(recipe)
    for mutation in (
        recipe.replace(b"--locked", b""),
        recipe.replace(b"USER 65532:65532", b"USER root"),
        recipe + b"\nCOPY . /opt/unreviewed\n",
        recipe + b"\nVOLUME /var/run/docker.sock\n",
        recipe.replace(b"uv==0.12.23", b"uv"),
        recipe.replace(b"sha256:4766", b"sha256:0000"),
    ):
        with pytest.raises(PackagingRefused, match="recipe_refused"):
            runner.validate_dockerfile(mutation)


@pytest.mark.parametrize(
    "key",
    [
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
        "BUILDKIT_HOST",
        "BUILDX_BUILDER",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ],
)
def test_ci_refuses_overrides(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    clean = {"GITHUB_ACTIONS": "true", "EM_REQUIRE_SERVICE_PACKAGING": "synthetic-test-only"}
    runner.require_ci(clean)
    with pytest.raises(PackagingRefused, match="ci_context"):
        runner.require_ci({**clean, key: "untrusted"})


def test_ci_requires_its_own_explicit_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    for environment in (
        {},
        {"GITHUB_ACTIONS": "true"},
        {"GITHUB_ACTIONS": "true", "EM_REQUIRE_METADATA_PACKAGING": "synthetic-test-only"},
        {"GITHUB_ACTIONS": "true", "EM_REQUIRE_SERVICE_PACKAGING": "production"},
    ):
        with pytest.raises(PackagingRefused, match="ci_context"):
            runner.require_ci(environment)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("HostConfig", "NetworkMode", "host"),
        ("HostConfig", "Privileged", True),
        ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
        ("HostConfig", "CapDrop", []),
        ("HostConfig", "SecurityOpt", ["seccomp=unconfined"]),
        ("HostConfig", "ReadonlyRootfs", False),
        ("HostConfig", "Binds", ["/var/run/docker.sock:/var/run/docker.sock"]),
        ("HostConfig", "Mounts", [{"Type": "bind", "Source": "/"}]),
        ("HostConfig", "Memory", 0),
        ("HostConfig", "MemorySwap", -1),
        ("HostConfig", "PidsLimit", 0),
        ("HostConfig", "NanoCpus", 0),
        ("HostConfig", "Tmpfs", {"/tmp": "rw,exec"}),
        ("HostConfig", "PortBindings", {"8000/tcp": [{}]}),
        ("HostConfig", "Devices", [{"PathOnHost": "/dev/sda"}]),
        ("HostConfig", "DeviceRequests", [{"Capabilities": [["gpu"]]}]),
        ("HostConfig", "PidMode", "host"),
        ("HostConfig", "IpcMode", "host"),
        ("HostConfig", "PublishAllPorts", True),
        ("HostConfig", "Ulimits", []),
        ("Config", "User", "0:0"),
        ("Config", "Entrypoint", ["sh"]),
        ("Config", "Cmd", ["worker"]),
        ("Config", "Volumes", {"/data": {}}),
        ("Config", "OpenStdin", True),
        ("Config", "Tty", True),
        ("Config", "Env", [*ENVIRONMENT, "EMAILMONITOR_LIVE_SOURCES_ENABLED=true"]),
        ("Config", "Env", [*ENVIRONMENT, "PYTHONPATH=/host"]),
        ("Config", "WorkingDir", "/host"),
    ],
)
def test_container_profile_refuses_relaxation(section: str, key: str, value: Any) -> None:
    accepted = record()
    runner.validate_profile(accepted, IMAGE, None)
    changed = copy.deepcopy(accepted)
    changed[section][key] = value
    with pytest.raises(PackagingRefused):
        runner.validate_profile(changed, IMAGE, None)


def test_probe_command_and_image_are_exactly_bound() -> None:
    runner.validate_profile(record("fixed-probe"), IMAGE, "fixed-probe")
    for identifier, probe in ((IMAGE, "different-probe"), ("sha256:" + "c" * 64, "fixed-probe")):
        with pytest.raises(PackagingRefused):
            runner.validate_profile(record("fixed-probe"), identifier, probe)


@pytest.mark.parametrize("kind", ["image", "container"])
def test_daemon_errors_are_not_absence(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    owned = runner.OwnedServiceBuilds(OWNER)
    name = "owned-resource"
    result = subprocess.CompletedProcess([], 1, b"", f"Error: No such {kind}: {name}\n".encode())
    control = Mock(return_value=result)
    monkeypatch.setattr(runner, "bounded_process", control)
    assert owned.inspect(kind, name) is None
    for stderr in (b"permission denied", b"Cannot connect to Docker daemon", b""):
        control.return_value = subprocess.CompletedProcess([], 1, b"", stderr)
        with pytest.raises(PackagingRefused, match="inspect_failed"):
            owned.inspect(kind, name)


def test_ownership_required_before_any_remove(monkeypatch: pytest.MonkeyPatch) -> None:
    owned = runner.OwnedServiceBuilds(OWNER)
    owned.containers = ["foreign"]
    foreign = record()
    foreign["Config"]["Labels"][runner.LABEL] = "c" * 32
    monkeypatch.setattr(owned, "inspect", Mock(return_value=foreign))
    execute = Mock()
    monkeypatch.setattr(runner, "command", execute)
    with pytest.raises(PackagingRefused, match="cleanup_failed"):
        owned.close()
    execute.assert_not_called()


def test_cleanup_reverses_resources_and_reconciles_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = runner.OwnedServiceBuilds(OWNER)
    owned.containers = ["container-1", "container-2"]
    owned.images = ["image-1", "image-2"]
    resources = {
        (kind, name)
        for kind, names in (("container", owned.containers), ("image", owned.images))
        for name in names
    }
    calls: list[list[str]] = []

    def inspect(kind: str, name: str) -> dict[str, Any] | None:
        return record() if (kind, name) in resources else None

    def remove(arguments: list[str], **kwargs: object) -> bytes:
        calls.append(arguments)
        resources.remove((arguments[1], arguments[-1]))
        return b""

    monkeypatch.setattr(owned, "inspect", inspect)
    monkeypatch.setattr(runner, "command", remove)
    owned.close()
    assert [item[1::3] for item in calls] == [
        ["container", "container-2"],
        ["container", "container-1"],
        ["image", "image-2"],
        ["image", "image-1"],
    ]
    assert not resources


def test_cleanup_continues_after_failure_and_rejects_leftover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = runner.OwnedServiceBuilds(OWNER)
    owned.containers = ["remaining"]
    owned.images = ["image"]
    monkeypatch.setattr(owned, "inspect", Mock(return_value=record()))
    execute = Mock(return_value=b"")
    monkeypatch.setattr(runner, "command", execute)
    with pytest.raises(PackagingRefused, match="cleanup_failed"):
        owned.close()
    assert execute.call_count == 2


def test_build_registers_before_ambiguous_create(monkeypatch: pytest.MonkeyPatch) -> None:
    owned = runner.OwnedServiceBuilds(OWNER)
    monkeypatch.setattr(owned, "inspect", Mock(return_value=None))
    execute = Mock(side_effect=PackagingRefused("ambiguous"))
    monkeypatch.setattr(runner, "command", execute)
    with pytest.raises(PackagingRefused, match="ambiguous"):
        owned.build(Path("/owned-context"), 1)
    assert owned.images == [f"emailmonitor-service-prerequisite:{OWNER}-1"]
    arguments = execute.call_args.args[0]
    assert "--no-cache" in arguments and "--pull=false" in arguments
    assert "--platform=linux/amd64" in arguments
    assert runner.LABEL + "=" + OWNER in arguments


def test_smoke_registers_before_ambiguous_create(monkeypatch: pytest.MonkeyPatch) -> None:
    owned = runner.OwnedServiceBuilds(OWNER)
    owned.image_ids.add(IMAGE)
    monkeypatch.setattr(owned, "inspect", lambda kind, name: record() if kind == "image" else None)
    execute = Mock(side_effect=PackagingRefused("ambiguous"))
    monkeypatch.setattr(runner, "command", execute)
    with pytest.raises(PackagingRefused, match="ambiguous"):
        owned.smoke(IMAGE, 1)
    assert owned.containers == [f"em-service-{OWNER}-1-help"]
    arguments = execute.call_args.args[0]
    assert all(flag in arguments for flag in runner.PROFILE)
    assert "--pull=never" in arguments and arguments[-1] == IMAGE
    assert not any("socket" in argument or argument == "--privileged" for argument in arguments)


def test_default_entrypoint_is_exercised_without_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = runner.OwnedServiceBuilds(OWNER)
    owned.image_ids.add(IMAGE)
    seen: list[str] = []

    def inspect(kind: str, name: str) -> dict[str, Any] | None:
        return record() if kind == "image" or name in seen else None

    def execute(arguments: list[str], **kwargs: object) -> bytes:
        seen.append(arguments[arguments.index("--name") + 1])
        assert "--entrypoint=python" not in arguments
        assert arguments[-1] == IMAGE
        return b"c" * 64 + b"\n"

    monkeypatch.setattr(owned, "inspect", inspect)
    monkeypatch.setattr(runner, "command", execute)
    monkeypatch.setattr(
        runner,
        "bounded_process",
        Mock(return_value=subprocess.CompletedProcess([], 0, b"usage:", b"")),
    )
    assert owned.smoke(IMAGE, 1) == b"usage:"


def test_guest_model_refusals_never_launch_an_application_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = Mock(side_effect=AssertionError("Imported probe must stay single-process"))
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "fork", forbidden)
    service_probe.model_refusals()
    forbidden.assert_not_called()
    source = (runner.ROOT / "scripts/packaging/service_probe.py").read_text()
    assert "subprocess" not in source
    assert '"cli_help"' not in source and '"production_refusals"' not in source


def test_probe_source_is_host_supplied_and_has_no_install_side_effect() -> None:
    source = runner.probe_source()
    compile(source, "<fixed-service-probe>", "exec")
    assert "def collect_base_inventory(" in source
    assert "SERVICE_IMAGE_PROBE_REFUSED" in source
    recipe = (runner.ROOT / "scripts/packaging/ServiceRuntime.Dockerfile").read_text()
    assert "service_probe" not in recipe


def test_clean_head_rejects_untracked_or_modified_source(monkeypatch: pytest.MonkeyPatch) -> None:
    execute = Mock(return_value=b"")
    monkeypatch.setattr(runner, "command", execute)
    runner.require_clean_source()
    for output in (b" M source.py\n", b"?? unreviewed.py\n"):
        execute.return_value = output
        with pytest.raises(PackagingRefused, match="clean_source"):
            runner.require_clean_source()


def test_command_caps_both_streams_and_refuses_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    process = Mock(return_value=subprocess.CompletedProcess([], 0, b"fixed", b""))
    monkeypatch.setattr(runner, "bounded_process", process)
    assert runner.command(["fixed"], timeout=2, limit=17) == b"fixed"
    process.assert_called_once_with(["fixed"], 2, stdout_limit=17, stderr_limit=17)
    process.return_value = subprocess.CompletedProcess([], 1, b"private", b"private")
    with pytest.raises(PackagingRefused, match="^service_package_command_failed$"):
        runner.command(["fixed"])


def mock_orchestration(monkeypatch: pytest.MonkeyPatch, *, fail: str | None = None) -> list[str]:
    """Control-flow proof only: neither fake builds nor receipts certify Docker."""
    events: list[str] = []
    files = {"manifest.json": b"{}\n"}
    monkeypatch.setattr(runner, "require_ci", lambda environment: None)
    monkeypatch.setattr(runner, "require_clean_source", lambda: events.append("clean"))
    monkeypatch.setattr(runner, "probe_source", lambda: "fixed-probe")
    monkeypatch.setattr(runner, "collect_service", lambda *args: dict(files))
    monkeypatch.setattr(runner, "tracked_service_sources", lambda *args: {})
    monkeypatch.setattr(runner, "verify_service_archive", lambda *args: dict(files))
    monkeypatch.setattr(
        runner,
        "validate_smoke",
        lambda *args: {"image_content_sha256": "d" * 64, "base_inventory": {"fixed": True}},
    )

    def command(arguments: list[str], **kwargs: object) -> bytes:
        if arguments == ["uv", "--version"]:
            return b"uv 0.12.23\n"
        if arguments == ["pnpm", "--version"]:
            return b"11.25.0\n"
        if arguments == ["node", "--version"]:
            return b"v24.19.0\n"
        if arguments[:2] == ["uv", "export"]:
            assert "--locked" in arguments and "--no-dev" in arguments
            return b"pydantic==2.14.0\n"
        if arguments[0] == "git" and arguments[-1] == "HEAD^{tree}":
            return b"a" * 40 + b"\n"
        if arguments[:2] == ["pnpm", "--dir"] and arguments[-1] == "build":
            events.append("web")
            return b""
        raise AssertionError("Unexpected orchestration command")

    class Owned:
        def __init__(self, owner: str) -> None:
            assert len(owner) == 32

        def build(self, context: Path, ordinal: int) -> str:
            assert (context / "manifest.json").read_bytes() == files["manifest.json"]
            runner.validate_dockerfile((context / "Dockerfile").read_bytes())
            assert (context / ".dockerignore").read_text() == "migrations\n"
            events.append("build")
            if fail == "build":
                raise PackagingRefused("synthetic_build_failure")
            return IMAGE

        def smoke(self, image: str, ordinal: int, probe: str | None = None) -> bytes:
            events.append("help" if probe is None else "probe")
            if fail == "probe" and probe is not None:
                raise PackagingRefused("synthetic_probe_failure")
            return b"usage: api worker publish-once reconcile-once check\n"

        @contextmanager
        def probe_budget(self) -> Iterator[None]:
            yield

        def production_refusal(self, image: str, ordinal: int, command_name: str) -> None:
            events.append("refuse-" + command_name)
            if fail == "refuse-" + command_name:
                raise PackagingRefused("synthetic_refusal_failure")

        def close(self) -> None:
            events.append("cleanup")
            if fail == "cleanup":
                raise PackagingRefused("synthetic_cleanup_failure")

    monkeypatch.setattr(runner, "command", command)
    monkeypatch.setattr(runner, "OwnedServiceBuilds", Owned)
    return events


def test_orchestration_builds_real_web_before_each_collected_context(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events = mock_orchestration(monkeypatch)
    runner.main()
    assert events == [
        "clean",
        "web",
        "clean",
        "build",
        "help",
        "probe",
        *("refuse-" + name for name in runner.PRODUCTION_COMMANDS),
        "web",
        "clean",
        "build",
        "help",
        "probe",
        *("refuse-" + name for name in runner.PRODUCTION_COMMANDS),
        "cleanup",
    ]
    value = json.loads(capsys.readouterr().out)
    assert value["actual_web_builds"] == 2
    assert value["network_none_containers"] == 14
    assert value["production_refusals_per_image"] == 5
    assert all(receipt["production_refusals"] == 5 for receipt in value["receipts"])
    assert value["cleanup_verified"] is True
    assert value["production_ready"] is False
    assert value["working_extraction_service"] is False
    assert value["oci_archive_bit_reproducibility_verified"] is False
    assert len(value["receipts"]) == 2
    assert value["receipts"][0] == value["receipts"][1]


@pytest.mark.parametrize("failure", ["build", "probe", "cleanup"])
def test_failure_always_cleans_up_and_never_prints_success(
    failure: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events = mock_orchestration(monkeypatch, fail=failure)
    with pytest.raises(PackagingRefused, match=f"synthetic_{failure}_failure"):
        runner.main()
    assert events[-1] == "cleanup"
    assert capsys.readouterr().out == ""


def test_changed_second_artifact_is_not_reproducible(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events = mock_orchestration(monkeypatch)
    monkeypatch.setattr(
        runner,
        "validate_smoke",
        Mock(
            side_effect=[
                {"image_content_sha256": "d" * 64, "base_inventory": {}},
                {"image_content_sha256": "e" * 64, "base_inventory": {}},
            ]
        ),
    )
    with pytest.raises(PackagingRefused, match="reproducibility_refused"):
        runner.main()
    assert events[-1] == "cleanup"
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "output",
    [
        b"",
        b"[]",
        b"null",
        b'{"scope":"authored-source-service-reference"}',
        b'{"secret":"arbitrary unexpected output"}',
        b'{"scope":"old","scope":"authored-source-service-reference"}',
    ],
)
def test_guest_receipt_requires_closed_schema(output: bytes) -> None:
    with pytest.raises(PackagingRefused, match="^service_package_probe_output_refused$"):
        runner.validate_smoke(output, {"manifest.json": b"{}\n"}, {"pydantic": "2.14.0"})


@pytest.mark.parametrize("stage", sorted(runner.STAGES))
def test_failure_stage_is_bounded_and_first_failure_survives_cleanup(
    stage: str, capsys: pytest.CaptureFixture[str]
) -> None:
    diagnostics = runner.Diagnostics()
    diagnostics.mark(stage, 2)
    diagnostics.capture()
    diagnostics.mark("cleanup")
    diagnostics.cleanup = "verified"
    diagnostics.capture()
    diagnostics.report()
    output = capsys.readouterr()
    assert output.out == ""
    assert len(output.err.encode()) < 256
    assert json.loads(output.err) == {
        "service_packaging_failure": {
            "stage": stage,
            "build": 2,
            "cleanup": "verified",
            "guest_stage": "unknown",
            "container_outcome": "unknown",
        }
    }


@pytest.mark.parametrize(("stage", "ordinal"), [("private secret", 1), ("cleanup", 3)])
def test_invalid_diagnostic_stage_is_refused_without_echo(stage: str, ordinal: int) -> None:
    with pytest.raises(PackagingRefused, match="^service_package_diagnostic_refused$"):
        runner.Diagnostics().mark(stage, ordinal)


def test_failure_report_never_formats_arbitrary_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Poison:
        def __str__(self) -> str:
            raise AssertionError("Diagnostic attempted arbitrary formatting")

        def __bool__(self) -> bool:
            raise AssertionError("Diagnostic attempted arbitrary evaluation")

    diagnostics = runner.Diagnostics()
    for name in ("stage", "ordinal", "failure", "cleanup", "guest_stage", "container_outcome"):
        monkeypatch.setattr(diagnostics, name, Poison())
    diagnostics.report()
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {
        "service_packaging_failure": {
            "stage": "ci_context",
            "build": 0,
            "cleanup": "not_started",
            "guest_stage": "unknown",
            "container_outcome": "unknown",
        }
    }


@pytest.mark.parametrize(
    ("failure", "stage", "ordinal", "cleanup"),
    [
        ("build", "image_build", 1, "verified"),
        ("probe", "probe_execute", 1, "verified"),
        ("cleanup", "cleanup", 0, "failed"),
    ],
)
def test_orchestration_failure_emits_only_exact_closed_diagnostic(
    failure: str,
    stage: str,
    ordinal: int,
    cleanup: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_orchestration(monkeypatch, fail=failure)
    with pytest.raises(PackagingRefused):
        runner.main()
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {
        "service_packaging_failure": {
            "stage": stage,
            "build": ordinal,
            "cleanup": cleanup,
            "guest_stage": "unknown",
            "container_outcome": "unknown",
        }
    }


def test_primary_probe_failure_is_preserved_when_cleanup_also_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_orchestration(monkeypatch, fail="probe")
    monkeypatch.setattr(
        runner.OwnedServiceBuilds,
        "close",
        Mock(side_effect=PackagingRefused("private cleanup context")),
    )
    with pytest.raises(PackagingRefused):
        runner.main()
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {
        "service_packaging_failure": {
            "stage": "probe_execute",
            "build": 1,
            "cleanup": "failed",
            "guest_stage": "unknown",
            "container_outcome": "unknown",
        }
    }
    assert "private" not in output.err


def test_failure_before_resource_creation_has_no_cleanup_claim(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runner, "require_ci", Mock(side_effect=RuntimeError("private config")))
    with pytest.raises(RuntimeError):
        runner.main()
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["service_packaging_failure"] == {
        "stage": "ci_context",
        "build": 0,
        "cleanup": "not_started",
        "guest_stage": "unknown",
        "container_outcome": "unknown",
    }


@pytest.mark.parametrize("stage", sorted(service_probe.STAGES))
def test_guest_stage_is_exact_and_host_allowlist_matches(
    stage: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert service_probe.STAGES == runner.GUEST_STAGES
    diagnostics = service_probe.ProbeDiagnostics()
    diagnostics.mark(stage)
    diagnostics.report()
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == f"SERVICE_IMAGE_PROBE_REFUSED stage={stage}\n"
    assert runner.guest_failure_stage(output.err.encode()) == stage


@pytest.mark.parametrize(
    "stderr",
    [
        b"",
        b"SERVICE_IMAGE_PROBE_REFUSED\n",
        b"SERVICE_IMAGE_PROBE_REFUSED stage=private secret\n",
        b"prefix SERVICE_IMAGE_PROBE_REFUSED stage=imports\n",
        b"SERVICE_IMAGE_PROBE_REFUSED stage=imports\nprivate context\n",
        b"SERVICE_IMAGE_PROBE_REFUSED stage=imports\n" * 2,
        b"SERVICE_IMAGE_PROBE_REFUSED stage=imports\x00\n",
    ],
)
def test_guest_diagnostic_never_forwards_arbitrary_stderr(stderr: bytes) -> None:
    assert runner.guest_failure_stage(stderr) == "unknown"


def test_actual_guest_failure_reports_stage_without_exception_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(service_probe, "kernel_checks", lambda: [101, 101])
    monkeypatch.setattr(
        service_probe, "verify_layout", Mock(side_effect=RuntimeError("private layout content"))
    )
    with pytest.raises(RuntimeError):
        service_probe.main()
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "SERVICE_IMAGE_PROBE_REFUSED stage=layout\n"


def test_success_has_no_failure_diagnostic(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mock_orchestration(monkeypatch)
    runner.main()
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["cleanup_verified"] is True


@pytest.mark.parametrize("command_name", runner.PRODUCTION_COMMANDS)
def test_refusal_bootstrap_execs_actual_cli_without_application_parent(
    command_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins
    import io
    import sys

    events: list[object] = []

    @contextmanager
    def open_config(path: str, mode: str, *, encoding: str) -> Iterator[io.StringIO]:
        assert path == "/tmp/service-production-refusal.json"
        assert mode == "x" and encoding == "utf-8"
        stream = io.StringIO()
        yield stream
        events.append(("config_closed", stream.getvalue()))

    def replace(executable: str, arguments: list[str]) -> None:
        assert executable == sys.executable
        assert arguments == [
            sys.executable,
            "-B",
            "-m",
            "emailmonitor.runtime.entrypoint",
            command_name,
            "--config",
            "/tmp/service-production-refusal.json",
        ]
        events.append("exec")

    monkeypatch.setattr(builtins, "open", open_config)
    monkeypatch.setattr(os, "execv", replace)
    script = runner.refusal_source(command_name)
    imports = [node for node in ast.walk(ast.parse(script)) if isinstance(node, ast.Import)]
    assert [alias.name for node in imports for alias in node.names] == ["os", "sys"]
    exec(compile(script, "<fixed-refusal-bootstrap>", "exec"), {})
    assert events == [("config_closed", '{"environment":"production"}'), "exec"]


def test_refusal_command_is_closed_before_any_container_action() -> None:
    for value in ("worker; private", "--help", "", "production"):
        with pytest.raises(PackagingRefused, match="^service_package_refusal_command_refused$"):
            runner.refusal_source(value)


def test_production_refusal_requires_shared_budget_before_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = runner.OwnedServiceBuilds(OWNER)
    inspect = Mock()
    monkeypatch.setattr(owned, "inspect", inspect)
    with pytest.raises(PackagingRefused, match="probe_deadline_refused"):
        owned.production_refusal(IMAGE, 1, "worker")
    inspect.assert_not_called()


@pytest.mark.parametrize(
    ("changed", "returncode", "stdout", "stderr", "outcome"),
    [
        ({"OOMKilled": True}, 1, b"", b"service_runtime_failed\n", "oom_killed"),
        ({"Running": True}, 1, b"", b"service_runtime_failed\n", "not_stopped"),
        ({"Status": "created"}, 1, b"", b"service_runtime_failed\n", "not_stopped"),
        ({"Paused": True}, 1, b"", b"service_runtime_failed\n", "not_stopped"),
        ({"Restarting": True}, 1, b"", b"service_runtime_failed\n", "not_stopped"),
        ({"Error": "private detail"}, 1, b"", b"service_runtime_failed\n", "not_stopped"),
        ({"ExitCode": 0}, 1, b"", b"service_runtime_failed\n", "exit_mismatch"),
        ({"ExitCode": 137}, 137, b"", b"service_runtime_failed\n", "exit_mismatch"),
        ({"ExitCode": True}, 1, b"", b"service_runtime_failed\n", "exit_mismatch"),
        ({}, 0, b"", b"service_runtime_failed\n", "exit_mismatch"),
        ({}, 1, b"private content", b"service_runtime_failed\n", "output_mismatch"),
        ({}, 1, b"", b"service_runtime_failed\nprivate context", "output_mismatch"),
        ({}, 1, b"", b"", "output_mismatch"),
    ],
)
def test_refusal_marker_alone_cannot_establish_a_verified_exit(
    changed: dict[str, object],
    returncode: int,
    stdout: bytes,
    stderr: bytes,
    outcome: str,
) -> None:
    stopped = record()
    stopped["State"]["ExitCode"] = 1
    assert (
        runner.stopped_outcome(
            stopped, 1, 1, b"", b"service_runtime_failed\n", b"service_runtime_failed\n"
        )
        == "verified"
    )
    stopped["State"].update(changed)
    assert (
        runner.stopped_outcome(stopped, returncode, 1, stdout, stderr, b"service_runtime_failed\n")
        == outcome
    )


@pytest.mark.parametrize("remaining", [45.0, 3.0])
def test_refusal_execution_has_five_second_and_shared_budget_bounds(
    remaining: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    owned = runner.OwnedServiceBuilds(OWNER)
    owned.image_ids.add(IMAGE)
    script = runner.refusal_source("worker")
    created = False
    control = Mock(
        return_value=subprocess.CompletedProcess([], 1, b"", b"service_runtime_failed\n")
    )

    def inspect(kind: str, name: str) -> dict[str, Any] | None:
        if kind == "image":
            return record()
        if not created:
            return None
        stopped = record(script)
        stopped["State"]["ExitCode"] = 1
        return stopped

    def create(arguments: list[str], **kwargs: object) -> bytes:
        nonlocal created
        assert all(flag in arguments for flag in runner.PROFILE)
        assert arguments[-3:] == [IMAGE, "-c", script]
        assert kwargs["timeout"] == min(20.0, remaining)
        created = True
        return b"c" * 64 + b"\n"

    monkeypatch.setattr(owned, "inspect", inspect)
    monkeypatch.setattr(runner, "command", create)
    monkeypatch.setattr(runner, "bounded_process", control)
    with owned.probe_budget():
        clock[0] += 45 - remaining
        owned.production_refusal(IMAGE, 1, "worker")
    assert control.call_args.kwargs["timeout"] == min(5.0, remaining)
    assert owned.containers == [f"em-service-{OWNER}-1-refuse-worker"]
    assert owned.deadline is None


def test_expired_shared_budget_prevents_next_control_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    owned = runner.OwnedServiceBuilds(OWNER)
    control = Mock()
    monkeypatch.setattr(runner, "bounded_process", control)
    with pytest.raises(PackagingRefused, match="probe_deadline_refused"):
        with owned.probe_budget():
            assert owned.timeout(100) == 45
            clock[0] = 146
            owned.inspect("image", IMAGE)
    control.assert_not_called()
    assert owned.deadline is None
    assert owned.timeout(20) == 20  # Cleanup keeps its original independent budget.


def test_budget_rechecks_completion_and_clears_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    owned = runner.OwnedServiceBuilds(OWNER)
    with pytest.raises(PackagingRefused, match="probe_deadline_refused"):
        with owned.probe_budget():
            clock[0] = 145
    assert owned.deadline is None
    with pytest.raises(RuntimeError, match="original"):
        with owned.probe_budget():
            raise RuntimeError("original")
    assert owned.deadline is None


@pytest.mark.parametrize("command_name", runner.PRODUCTION_COMMANDS)
def test_partial_refusal_sequence_never_emits_success_or_continues(
    command_name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events = mock_orchestration(monkeypatch, fail="refuse-" + command_name)
    with pytest.raises(PackagingRefused, match="synthetic_refusal_failure"):
        runner.main()
    output = capsys.readouterr()
    assert output.out == ""
    assert events[-1] == "cleanup"
    assert events.count("build") == 1
    assert [event for event in events if event.startswith("refuse-")] == [
        "refuse-" + name
        for name in runner.PRODUCTION_COMMANDS[: runner.PRODUCTION_COMMANDS.index(command_name) + 1]
    ]
    assert json.loads(output.err)["service_packaging_failure"]["stage"] == "production_refusals"

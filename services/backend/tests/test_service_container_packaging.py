"""Pure service packaging contracts; mocked Docker never establishes image acceptance."""

import copy
import json
import platform
import subprocess
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
        "State": {"Running": False, "ExitCode": 0, "OOMKilled": False, "Error": ""},
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


def test_guest_cli_checks_environment_gate_and_fixed_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def execute(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(arguments)
        assert kwargs["timeout"] == 5
        if arguments[-1] == "--help":
            return subprocess.CompletedProcess(arguments, 0, b"usage: service", b"")
        config = Path(arguments[-1])
        assert config.parent.parent == Path("/tmp")
        assert json.loads(config.read_bytes()) == {"environment": "production"}
        return subprocess.CompletedProcess(arguments, 1, b"", b"service_runtime_failed\n")

    monkeypatch.setattr(subprocess, "run", execute)
    service_probe.cli_checks()
    assert len(calls) == 6
    assert not Path(calls[-1][-1]).exists()


def test_guest_production_refusal_must_have_no_arbitrary_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = [
        subprocess.CompletedProcess([], 0, b"usage: service", b""),
        subprocess.CompletedProcess([], 1, b"", b"unexpected private diagnostic"),
    ]
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=results))
    with pytest.raises(RuntimeError, match="production_refusal_missing"):
        service_probe.cli_checks()


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
        "web",
        "clean",
        "build",
        "help",
        "probe",
        "cleanup",
    ]
    value = json.loads(capsys.readouterr().out)
    assert value["actual_web_builds"] == 2
    assert value["network_none_containers"] == 4
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
    for name in ("stage", "ordinal", "failure", "cleanup", "guest_stage"):
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

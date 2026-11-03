"""Two owned service-artifact builds and network-none checks, never deployment."""

import json
import os
import platform
import re
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from base_inventory import validate_base_inventory
from run_xml_acceptance import (
    ProcessDiagnostics,
    ProcessFailure,
    StderrClass,
    StdoutPresence,
    bounded_process,
)
from service_artifacts import collect_service, tracked_service_sources, verify_service_archive

from artifacts import BASE, PLATFORM, PackagingRefused, archive, digest, materialize, read
from run_acceptance import require_tool_versions, runtime_versions, validate_container

ROOT = Path(__file__).resolve().parents[2]
LABEL = "io.emailmonitor.service-packaging-owner"
SCOPE = "authored-source-service-reference"
ENTRYPOINT = ["python", "-m", "emailmonitor.runtime.entrypoint"]
PROFILE = (
    "--network=none",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
    "--read-only",
    "--user=65532:65532",
    "--memory=128m",
    "--memory-swap=128m",
    "--cpus=0.5",
    "--pids-limit=32",
    "--ulimit=nofile=64:64",
    "--ulimit=core=0:0",
    "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
)
ENVIRONMENT_KEYS = {
    "PATH",
    "LANG",
    "GPG_KEY",
    "PYTHON_VERSION",
    "PYTHON_SHA256",
    "PYTHONPATH",
    "PYTHONDONTWRITEBYTECODE",
}
STAGES = frozenset(
    {
        "ci_context",
        "tool_versions",
        "clean_source",
        "source_tree",
        "runtime_export",
        "runtime_inventory",
        "recipe",
        "probe_source",
        "web_build",
        "source_inventory",
        "artifact_collect",
        "artifact_archive",
        "artifact_verify",
        "artifact_materialize",
        "image_build",
        "entrypoint_help",
        "probe_execute",
        "probe_receipt",
        "production_refusals",
        "reproducibility",
        "cleanup",
        "receipt",
    }
)
GUEST_STAGES = frozenset(
    {"kernel", "layout", "imports", "models", "content", "base_inventory", "receipt"}
)
PRODUCTION_COMMANDS = ("api", "worker", "publish-once", "reconcile-once", "check")
CONTAINER_OUTCOMES = frozenset(
    {"unknown", "oom_killed", "not_stopped", "exit_mismatch", "output_mismatch", "guest_refused"}
)
HOST_PHASES = frozenset(
    {
        "unknown",
        "image_identity",
        "image_inspect",
        "container_absence",
        "container_create",
        "created_identity",
        "created_inspect",
        "profile_validate",
        "start_attach",
        "stopped_inspect",
        "stopped_validate",
        "budget_complete",
    }
)
SHARED_BUDGET_STATES = frozenset({"unknown", "inactive", "remaining", "exhausted"})
PROCESS_FAILURES = frozenset(reason.value for reason in ProcessFailure)
STDOUT_PRESENCES = frozenset(presence.value for presence in StdoutPresence)
STDERR_CLASSES = frozenset(classification.value for classification in StderrClass)
CLEANUP_CONTAINER_STATES = frozenset(
    {"not_observed", "unknown", "missing", "created", "running", "exited", "other"}
)
CLEANUP_OOM_STATES = frozenset({"unknown", "no", "yes"})


@dataclass
class Diagnostics:
    """Only source-owned enums; no exception, subprocess output or config data."""

    stage: str = "ci_context"
    ordinal: int = 0
    failure: tuple[str, int] | None = None
    cleanup: str = "not_started"
    guest_stage: str = "unknown"
    container_outcome: str = "unknown"
    refusal_index: int = 0
    host_phase: str = "unknown"
    shared_budget_state: str = "inactive"
    process_failure: str = "unknown"
    stdout_presence: str = "unknown"
    stderr_class: str = "unknown"
    cleanup_container_state: str = "not_observed"
    cleanup_oom: str = "unknown"

    def mark(self, stage: str, ordinal: int = 0) -> None:
        if type(stage) is not str or stage not in STAGES or type(ordinal) is not int:
            raise PackagingRefused("service_package_diagnostic_refused")
        if ordinal not in (0, 1, 2):
            raise PackagingRefused("service_package_diagnostic_refused")
        self.stage, self.ordinal = stage, ordinal

    def capture(self) -> None:
        if self.failure is None:
            self.failure = self.stage, self.ordinal

    def report(self) -> None:
        failure = self.failure
        stage, ordinal = (
            failure if type(failure) is tuple and len(failure) == 2 else (self.stage, self.ordinal)
        )
        # Revalidate even internal state; the reporter never serializes arbitrary objects.
        if type(stage) is not str or stage not in STAGES:
            stage = "ci_context"
        if type(ordinal) is not int or ordinal not in (0, 1, 2):
            ordinal = 0
        cleanup = self.cleanup if type(self.cleanup) is str else "not_started"
        if cleanup not in {"not_started", "verified", "failed"}:
            cleanup = "not_started"
        guest = self.guest_stage if type(self.guest_stage) is str else "unknown"
        if guest not in GUEST_STAGES:
            guest = "unknown"
        outcome = self.container_outcome if type(self.container_outcome) is str else "unknown"
        if outcome not in CONTAINER_OUTCOMES:
            outcome = "unknown"
        refusal_index = self.refusal_index if type(self.refusal_index) is int else 0
        if refusal_index not in (0, 1, 2, 3, 4, 5):
            refusal_index = 0
        phase = self.host_phase if type(self.host_phase) is str else "unknown"
        if phase not in HOST_PHASES:
            phase = "unknown"
        budget = self.shared_budget_state if type(self.shared_budget_state) is str else "unknown"
        if budget not in SHARED_BUDGET_STATES:
            budget = "unknown"
        process = self.process_failure if type(self.process_failure) is str else "unknown"
        if process not in PROCESS_FAILURES:
            process = "unknown"
        stdout = self.stdout_presence if type(self.stdout_presence) is str else "unknown"
        if stdout not in STDOUT_PRESENCES:
            stdout = "unknown"
        stderr = self.stderr_class if type(self.stderr_class) is str else "unknown"
        if stderr not in STDERR_CLASSES:
            stderr = "unknown"
        container = (
            self.cleanup_container_state if type(self.cleanup_container_state) is str else "unknown"
        )
        if container not in CLEANUP_CONTAINER_STATES:
            container = "unknown"
        oom = self.cleanup_oom if type(self.cleanup_oom) is str else "unknown"
        if oom not in CLEANUP_OOM_STATES:
            oom = "unknown"
        sys.stderr.write(
            json.dumps(
                {
                    "service_packaging_failure": {
                        "stage": stage,
                        "build": ordinal,
                        "cleanup": cleanup,
                        "guest_stage": guest,
                        "container_outcome": outcome,
                        "refusal_index": refusal_index,
                        "host_phase": phase,
                        "shared_budget_state": budget,
                        "process_failure": process,
                        "stdout_presence": stdout,
                        "stderr_class": stderr,
                        "cleanup_container_state": container,
                        "cleanup_oom": oom,
                    }
                },
                sort_keys=True,
            )
            + "\n"
        )


def guest_failure_stage(stderr: bytes) -> str:
    if type(stderr) is not bytes:
        return "unknown"
    for stage in GUEST_STAGES:
        if stderr == f"SERVICE_IMAGE_PROBE_REFUSED stage={stage}\n".encode():
            return stage
    return "unknown"


def refusal_source(command_name: str) -> str:
    if type(command_name) is not str or command_name not in PRODUCTION_COMMANDS:
        raise PackagingRefused("service_package_refusal_command_refused")
    # exec replaces this lightweight bootstrap; no imported application parent
    # remains alive beside the actual CLI within the unchanged 128 MiB budget.
    return (
        "import os, sys\n"
        "path = '/tmp/service-production-refusal.json'\n"
        "with open(path, 'x', encoding='utf-8') as source:\n"
        ' source.write(\'{"environment":"production"}\')\n'
        "os.execv(sys.executable, [sys.executable, '-B', '-m', "
        f"'emailmonitor.runtime.entrypoint', {command_name!r}, '--config', path])\n"
    )


def stopped_outcome(
    record: dict[str, Any] | None,
    returncode: int,
    expected_exit: int,
    stdout: bytes,
    stderr: bytes,
    expected_stderr: bytes,
) -> str:
    state = record.get("State", {}) if record is not None else {}
    if state.get("OOMKilled") is True:
        return "oom_killed"
    if (
        state.get("Status") != "exited"
        or state.get("Running") is not False
        or state.get("Paused") is not False
        or state.get("Restarting") is not False
        or state.get("OOMKilled") is not False
        or state.get("Error") != ""
    ):
        return "not_stopped"
    if (
        type(returncode) is not int
        or returncode != expected_exit
        or type(state.get("ExitCode")) is not int
        or state["ExitCode"] != expected_exit
    ):
        return "exit_mismatch"
    if stderr != expected_stderr or (expected_exit == 1 and stdout):
        return "output_mismatch"
    return "verified"


def cleanup_observation(
    record: dict[str, Any] | None, container_id: str, image_id: str
) -> tuple[str, str]:
    """Only the already-owned, exact failed container's pre-removal state."""
    if record is None:
        return "missing", "unknown"
    if (
        type(record) is not dict
        or type(record.get("Id")) is not str
        or record["Id"] != container_id
        or type(record.get("Image")) is not str
        or record["Image"] != image_id
    ):
        return "unknown", "unknown"
    state = record.get("State")
    if (
        type(state) is not dict
        or type(state.get("Status")) is not str
        or any(
            type(state.get(key)) is not bool
            for key in ("Running", "Paused", "Restarting", "OOMKilled", "Dead")
        )
        or type(state.get("ExitCode")) is not int
        or not 0 <= state["ExitCode"] <= 255
        or type(state.get("Error")) is not str
        or state["Error"] != ""
    ):
        return "unknown", "unknown"
    status = state["Status"]
    other_flags = {
        "paused": (True, True, False, False),
        "restarting": (True, False, True, False),
        "removing": (False, False, False, False),
        "dead": (False, False, False, True),
    }
    if status in other_flags:
        flags = tuple(state[key] for key in ("Running", "Paused", "Restarting", "Dead"))
        if flags != other_flags[status] or state["OOMKilled"]:
            return "unknown", "unknown"
        return "other", "unknown"
    if status not in {"created", "running", "exited"}:
        return "unknown", "unknown"
    if (
        state["Running"] is not (status == "running")
        or state["Paused"]
        or state["Restarting"]
        or state["Dead"]
        or (status != "exited" and (state["OOMKilled"] or state["ExitCode"] != 0))
        or (state["OOMKilled"] and state["ExitCode"] == 0)
    ):
        return "unknown", "unknown"
    return status, "yes" if state["OOMKilled"] else "no"


def command(arguments: list[str], timeout: float = 30, limit: int = 131072) -> bytes:
    result = bounded_process(arguments, timeout, stdout_limit=limit, stderr_limit=limit)
    if result.returncode:
        raise PackagingRefused("service_package_command_failed")
    return result.stdout


def require_ci(environ: dict[str, str]) -> None:
    forbidden = {
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
    }
    if (
        environ.get("GITHUB_ACTIONS") != "true"
        or environ.get("EM_REQUIRE_SERVICE_PACKAGING") != "synthetic-test-only"
        or any(environ.get(key) for key in forbidden)
        or platform.system() != "Linux"
        or platform.machine() != "x86_64"
    ):
        raise PackagingRefused("service_package_ci_context_refused")


def validate_dockerfile(body: bytes) -> None:
    """Closed build recipe: no extra download, grant, config or secret instruction."""
    expected = [
        f"FROM --platform={PLATFORM} {BASE} AS dependencies",
        "WORKDIR /opt/emailmonitor/services/backend",
        "COPY services/backend/pyproject.toml services/backend/uv.lock ./",
        "RUN python -m pip install --no-cache-dir uv==0.12.23 && uv sync --locked --no-dev",
        f"FROM --platform={PLATFORM} {BASE}",
        "WORKDIR /opt/emailmonitor",
        "COPY --from=dependencies /opt/emailmonitor/services/backend/.venv "
        "./services/backend/.venv",
        "COPY services/backend/src ./services/backend/src",
        "COPY fixtures ./fixtures",
        "COPY contracts ./contracts",
        "COPY static-web ./static-web",
        "COPY manifest.json ./manifest.json",
        "COPY notices ./notices",
        'ENV PATH="/opt/emailmonitor/services/backend/.venv/bin:$PATH" '
        'PYTHONPATH="/opt/emailmonitor/services/backend/src" PYTHONDONTWRITEBYTECODE=1',
        "USER 65532:65532",
        'ENTRYPOINT ["python", "-m", "emailmonitor.runtime.entrypoint"]',
        'CMD ["--help"]',
    ]
    try:
        lines = [
            line.strip()
            for line in body.decode("utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except UnicodeError:
        raise PackagingRefused("service_package_recipe_refused") from None
    if lines != expected:
        raise PackagingRefused("service_package_recipe_refused")


def validate_environment(record: dict[str, Any]) -> None:
    values = record.get("Config", {}).get("Env")
    if not isinstance(values, list) or any(
        not isinstance(value, str) or "=" not in value for value in values
    ):
        raise PackagingRefused("service_package_environment_refused")
    environment = dict(value.split("=", 1) for value in values)
    if (
        len(environment) != len(values)
        or set(environment) - ENVIRONMENT_KEYS
        or environment.get("PYTHONPATH") != "/opt/emailmonitor/services/backend/src"
        or environment.get("PYTHONDONTWRITEBYTECODE") != "1"
        or not environment.get("PATH", "").startswith(
            "/opt/emailmonitor/services/backend/.venv/bin:"
        )
    ):
        raise PackagingRefused("service_package_environment_refused")


def validate_profile(record: dict[str, Any], image_id: str, probe: str | None) -> None:
    try:
        validate_container(record)
        validate_environment(record)
        host, config = record["HostConfig"], record["Config"]
        if (
            record.get("Image") != image_id
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id)
            or config.get("Entrypoint") != (ENTRYPOINT if probe is None else ["python"])
            or config.get("Cmd") != (["--help"] if probe is None else ["-c", probe])
            or config.get("WorkingDir") != "/opt/emailmonitor"
            or config.get("OpenStdin") is not False
            or config.get("Tty") is not False
            or config.get("Volumes")
            or host.get("Mounts")
            or host.get("Devices")
            or host.get("DeviceRequests")
            or host.get("PidMode") not in ("", None)
            or host.get("IpcMode") not in ("private", "")
            or host.get("NetworkMode") != "none"
            or host.get("PublishAllPorts") is not False
            or sorted(host.get("Ulimits", []), key=lambda item: item["Name"])
            != [
                {"Name": "core", "Hard": 0, "Soft": 0},
                {"Name": "nofile", "Hard": 64, "Soft": 64},
            ]
        ):
            raise PackagingRefused("service_package_profile_refused")
    except (KeyError, TypeError, ValueError):
        raise PackagingRefused("service_package_profile_refused") from None


class OwnedServiceBuilds:
    def __init__(self, owner: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{32}", owner):
            raise PackagingRefused("service_package_owner_refused")
        self.owner = owner
        self.images: list[str] = []
        self.containers: list[str] = []
        self.image_ids: set[str] = set()
        self.guest_stage = "unknown"
        self.container_outcome = "unknown"
        self.refusal_index = 0
        self.host_phase = "unknown"
        self.shared_budget_state = "inactive"
        self.process_diagnostics: ProcessDiagnostics | None = None
        self.failed_container: tuple[str, str, str] | None = None
        self.cleanup_container_state = "not_observed"
        self.cleanup_oom = "unknown"
        self.deadline: float | None = None

    def timeout(self, maximum: float) -> float:
        if self.deadline is None:
            return maximum
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise PackagingRefused("service_package_probe_deadline_refused")
        return min(maximum, remaining)

    @contextmanager
    def probe_budget(self) -> Iterator[None]:
        if self.deadline is not None:
            raise PackagingRefused("service_package_probe_deadline_refused")
        self.deadline = time.monotonic() + 45
        self.refusal_index = 0
        self.host_phase = "unknown"
        self.shared_budget_state = "remaining"
        try:
            yield
            self.refusal_index = 0
            self.host_phase = "budget_complete"
            self.timeout(1)  # Completion and all receipt checks must fit the shared budget.
        except BaseException:
            # Snapshot before finally clears the deadline; never replace the primary error.
            try:
                self.shared_budget_state = (
                    "exhausted" if time.monotonic() >= self.deadline else "remaining"
                )
            except Exception:
                self.shared_budget_state = "unknown"
            raise
        else:
            self.host_phase = "unknown"
            self.shared_budget_state = "inactive"
        finally:
            # Owned cleanup has its existing independent finite reconciliation bounds.
            self.deadline = None

    def inspect(self, kind: str, name: str) -> dict[str, Any] | None:
        if kind not in {"image", "container"}:
            raise PackagingRefused("service_package_resource_kind_refused")
        result = bounded_process(["docker", kind, "inspect", name], timeout=self.timeout(10))
        if result.returncode:
            expected = {
                f"Error: No such image: {name}",
                f"Error response from daemon: No such image: {name}",
                f"Error: No such container: {name}",
                f"Error: No such object: {name}",
                f"Error response from daemon: No such container: {name}",
            }
            if (
                result.returncode == 1
                and result.stdout.strip() in {b"", b"[]"}
                and result.stderr.decode("utf-8", "replace").strip() in expected
            ):
                return None
            raise PackagingRefused("service_package_inspect_failed")
        try:
            value = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise PackagingRefused("service_package_inspect_failed") from None
        if (
            result.stderr
            or not isinstance(value, list)
            or len(value) != 1
            or not isinstance(value[0], dict)
        ):
            raise PackagingRefused("service_package_inspect_failed")
        return value[0]

    def owned(self, kind: str, name: str) -> dict[str, Any] | None:
        record = self.inspect(kind, name)
        if (
            record is not None
            and (record.get("Config", {}).get("Labels") or {}).get(LABEL) != self.owner
        ):
            raise PackagingRefused("service_package_ownership_refused")
        return record

    def build(self, context: Path, ordinal: int) -> str:
        if ordinal not in (1, 2):
            raise PackagingRefused("service_package_ordinal_refused")
        name = f"emailmonitor-service-prerequisite:{self.owner}-{ordinal}"
        if self.inspect("image", name) is not None:
            raise PackagingRefused("service_package_resource_exists")
        self.images.append(name)  # Register before a possibly ambiguous Docker result.
        command(
            [
                "docker",
                "build",
                "--platform=" + PLATFORM,
                "--no-cache",
                "--pull=false",
                "--label",
                LABEL + "=" + self.owner,
                "--tag",
                name,
                str(context),
            ],
            timeout=300,
            limit=8 * 1024 * 1024,
        )
        record = self.owned("image", name)
        if record is None or not re.fullmatch(r"sha256:[a-f0-9]{64}", record.get("Id", "")):
            raise PackagingRefused("service_package_image_missing")
        config = record["Config"]
        if (
            config.get("User") != "65532:65532"
            or config.get("Entrypoint") != ENTRYPOINT
            or config.get("Cmd") != ["--help"]
            or config.get("WorkingDir") != "/opt/emailmonitor"
            or config.get("Volumes")
            or config.get("ExposedPorts")
            or config.get("Healthcheck")
            or config.get("OnBuild")
        ):
            raise PackagingRefused("service_package_image_config_refused")
        validate_environment(record)
        identifier: str = record["Id"]
        self.image_ids.add(identifier)
        return identifier

    def smoke(self, image_id: str, ordinal: int, probe: str | None = None) -> bytes:
        self.refusal_index = 0
        case = "help" if probe is None else "probe"
        return self._run(image_id, ordinal, probe, case, refusal=False)

    def production_refusal(self, image_id: str, ordinal: int, command_name: str) -> None:
        script = refusal_source(command_name)
        if self.deadline is None:
            raise PackagingRefused("service_package_probe_deadline_refused")
        self.refusal_index = PRODUCTION_COMMANDS.index(command_name) + 1
        self._run(image_id, ordinal, script, "refuse-" + command_name, refusal=True)
        self.refusal_index = 0

    def _run(
        self, image_id: str, ordinal: int, script: str | None, case: str, *, refusal: bool
    ) -> bytes:
        self.host_phase = "image_identity"
        if image_id not in self.image_ids or ordinal not in (1, 2):
            raise PackagingRefused("service_package_image_identity_refused")
        self.host_phase = "image_inspect"
        image = self.owned("image", image_id)
        if image is None or image.get("Id") != image_id:
            raise PackagingRefused("service_package_image_identity_refused")
        name = f"em-service-{self.owner}-{ordinal}-{case}"
        self.host_phase = "container_absence"
        if self.inspect("container", name) is not None:
            raise PackagingRefused("service_package_resource_exists")
        self.containers.append(name)
        self.host_phase = "container_create"
        created = command(
            [
                "docker",
                "create",
                "--pull=never",
                "--name",
                name,
                "--label",
                LABEL + "=" + self.owner,
                *PROFILE,
                *([] if script is None else ["--entrypoint=python"]),
                image_id,
                *([] if script is None else ["-c", script]),
            ],
            timeout=self.timeout(20),
        )
        self.host_phase = "created_identity"
        if not re.fullmatch(rb"[a-f0-9]{64}\n", created):
            raise PackagingRefused("service_package_container_identity_refused")
        self.host_phase = "created_inspect"
        record = self.owned("container", name)
        if record is None:
            raise PackagingRefused("service_package_container_missing")
        self.host_phase = "profile_validate"
        validate_profile(record, image_id, script)
        self.host_phase = "start_attach"
        self.failed_container = name, created.decode("ascii").strip(), image_id
        self.process_diagnostics = ProcessDiagnostics(capture_refusal_output=refusal)
        result = bounded_process(
            ["docker", "start", "--attach", name],
            timeout=self.timeout(5 if refusal else 45),
            stdout_limit=65536,
            stderr_limit=4096,
            diagnostics=self.process_diagnostics,
        )
        self.host_phase = "stopped_inspect"
        stopped = self.owned("container", name)
        self.host_phase = "stopped_validate"
        outcome = stopped_outcome(
            stopped,
            result.returncode,
            1 if refusal else 0,
            result.stdout,
            result.stderr,
            b"service_runtime_failed\n" if refusal else b"",
        )
        if outcome != "verified":
            self.container_outcome = outcome
            if case == "probe":
                self.guest_stage = guest_failure_stage(result.stderr)
                if self.guest_stage != "unknown" and outcome in {
                    "exit_mismatch",
                    "output_mismatch",
                }:
                    self.container_outcome = "guest_refused"
            raise PackagingRefused("service_package_smoke_failed")
        self.host_phase = "unknown"
        self.failed_container = None
        self.process_diagnostics = None
        return result.stdout

    def close(self) -> None:
        errors = []
        for kind, names in (("container", self.containers), ("image", self.images)):
            for name in reversed(names):
                try:
                    record = self.owned(kind, name)
                    if (
                        kind == "container"
                        and self.failed_container is not None
                        and name == self.failed_container[0]
                        and self.cleanup_container_state == "not_observed"
                    ):
                        self.cleanup_container_state, self.cleanup_oom = cleanup_observation(
                            record, self.failed_container[1], self.failed_container[2]
                        )
                    if record is not None:
                        command(["docker", kind, "rm", "--force", name], timeout=20)
                    if self.inspect(kind, name) is not None:
                        raise PackagingRefused("service_package_cleanup_incomplete")
                except Exception:
                    errors.append("service_package_cleanup_failed")
        if errors:
            raise PackagingRefused("service_package_cleanup_failed")


def probe_source() -> str:
    prefix = read(ROOT, "scripts/packaging/base_inventory.py")
    probe = read(ROOT, "scripts/packaging/service_probe.py")
    if len(prefix) > 32768 or len(probe) > 32768:
        raise PackagingRefused("service_package_probe_size_refused")
    return prefix.decode("utf-8") + "\n" + probe.decode("utf-8")


def validate_smoke(
    output: bytes, files: dict[str, bytes], runtime: dict[str, str]
) -> dict[str, Any]:
    try:
        value = json.loads(output)
        source_count = sum(name.startswith("services/backend/src/") for name in files)
        expected = {
            "scope": SCOPE,
            "production_ready": False,
            "working_extraction_service": False,
            "exact_source_closure": True,
            "source_file_count": source_count,
            "installed_import_closure": True,
            "production_environment_literal_refusals": 2,
            "interfaces": ["lo"],
            "kernel_restrictions": True,
            "read_only_root": True,
            "network_errno": [101, 101],
            "runtime_distributions": runtime,
            "manifest_sha256": digest(files["manifest.json"]),
        }
        if (
            type(value) is not dict
            or {key: value.get(key) for key in expected} != expected
            or any(type(value.get(key)) is not type(item) for key, item in expected.items())
            or set(value) != set(expected) | {"image_content_sha256", "base_inventory"}
            or not re.fullmatch(r"[a-f0-9]{64}", value["image_content_sha256"])
            or output != (json.dumps(value, sort_keys=True) + "\n").encode()
        ):
            raise ValueError
        validate_base_inventory(value["base_inventory"])
        return value
    except (KeyError, ValueError, TypeError, RuntimeError):
        raise PackagingRefused("service_package_probe_output_refused") from None


def require_clean_source() -> None:
    if command(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=normal"], timeout=10
    ).strip():
        raise PackagingRefused("service_package_clean_source_required")


def execute(diagnostics: Diagnostics) -> None:
    diagnostics.mark("ci_context")
    require_ci(dict(os.environ))
    diagnostics.mark("tool_versions")
    require_tool_versions(
        {
            name: command([name, "--version"]).decode("ascii").strip()
            for name in ("uv", "pnpm", "node")
        }
    )
    diagnostics.mark("clean_source")
    require_clean_source()
    diagnostics.mark("source_tree")
    tree_sha = (
        command(["git", "-C", str(ROOT), "rev-parse", "HEAD^{tree}"], timeout=10)
        .decode("ascii")
        .strip()
    )
    diagnostics.mark("runtime_export")
    exported = command(
        [
            "uv",
            "export",
            "--project",
            str(ROOT / "services/backend"),
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--no-hashes",
            "--no-header",
            "--no-annotate",
        ]
    ).decode("utf-8")
    diagnostics.mark("runtime_inventory")
    runtime = runtime_versions(exported)
    diagnostics.mark("recipe")
    dockerfile = read(ROOT, "scripts/packaging/ServiceRuntime.Dockerfile")
    validate_dockerfile(dockerfile)
    diagnostics.mark("probe_source")
    probe = probe_source()
    owned = OwnedServiceBuilds(uuid4().hex)
    receipts = []
    try:
        with tempfile.TemporaryDirectory(prefix="em-service-packaging-") as temporary:
            for ordinal in (1, 2):
                diagnostics.mark("web_build", ordinal)
                command(["pnpm", "--dir", str(ROOT / "apps/web"), "build"], timeout=180)
                diagnostics.mark("clean_source", ordinal)
                require_clean_source()
                diagnostics.mark("source_inventory", ordinal)
                sources = tracked_service_sources(ROOT, tree_sha)
                diagnostics.mark("artifact_collect", ordinal)
                files = collect_service(ROOT, tree_sha, runtime, sources)
                diagnostics.mark("artifact_archive", ordinal)
                bundle = archive(files)
                diagnostics.mark("artifact_verify", ordinal)
                if verify_service_archive(bundle, files["manifest.json"]) != files:
                    raise PackagingRefused("service_package_roundtrip_refused")
                context = Path(temporary) / str(ordinal)
                diagnostics.mark("artifact_materialize", ordinal)
                materialize(files, context)
                (context / "Dockerfile").write_bytes(dockerfile)
                # Migration inputs remain in the archive, never in a runtime layer.
                (context / ".dockerignore").write_text("migrations\n", encoding="utf-8")
                diagnostics.mark("image_build", ordinal)
                image_id = owned.build(context, ordinal)
                diagnostics.mark("entrypoint_help", ordinal)
                help_output = owned.smoke(image_id, ordinal)
                if (
                    len(help_output) > 8192
                    or not help_output.startswith(b"usage:")
                    or any(
                        name.encode() not in help_output
                        for name in ("api", "worker", "publish-once", "reconcile-once", "check")
                    )
                ):
                    raise PackagingRefused("service_package_help_refused")
                refused = 0
                with owned.probe_budget():
                    diagnostics.mark("probe_execute", ordinal)
                    output = owned.smoke(image_id, ordinal, probe)
                    diagnostics.mark("probe_receipt", ordinal)
                    smoke = validate_smoke(output, files, runtime)
                    diagnostics.mark("production_refusals", ordinal)
                    for command_name in PRODUCTION_COMMANDS:
                        owned.production_refusal(image_id, ordinal, command_name)
                        refused += 1
                receipts.append(
                    {
                        "archive_sha256": digest(bundle),
                        "manifest_sha256": digest(files["manifest.json"]),
                        "image_id": image_id,
                        "image_content_sha256": smoke["image_content_sha256"],
                        "base_inventory": smoke["base_inventory"],
                        "production_refusals": refused,
                    }
                )
            diagnostics.mark("reproducibility")
            if any(
                receipts[0][key] != receipts[1][key]
                for key in (
                    "archive_sha256",
                    "manifest_sha256",
                    "image_content_sha256",
                    "base_inventory",
                )
            ):
                raise PackagingRefused("service_package_reproducibility_refused")
    except BaseException:
        diagnostics.capture()
        diagnostics.guest_stage = getattr(owned, "guest_stage", "unknown")
        diagnostics.container_outcome = getattr(owned, "container_outcome", "unknown")
        diagnostics.refusal_index = getattr(owned, "refusal_index", 0)
        diagnostics.host_phase = getattr(owned, "host_phase", "unknown")
        diagnostics.shared_budget_state = getattr(owned, "shared_budget_state", "inactive")
        process_diagnostics = getattr(owned, "process_diagnostics", None)
        if (
            type(process_diagnostics) is ProcessDiagnostics
            and type(process_diagnostics.failure) is ProcessFailure
        ):
            diagnostics.process_failure = process_diagnostics.failure.value
            if type(process_diagnostics.stdout_presence) is StdoutPresence:
                diagnostics.stdout_presence = process_diagnostics.stdout_presence.value
            if type(process_diagnostics.stderr_class) is StderrClass:
                diagnostics.stderr_class = process_diagnostics.stderr_class.value
        raise
    finally:
        diagnostics.mark("cleanup")
        try:
            owned.close()
        except BaseException:
            diagnostics.cleanup = "failed"
            raise
        else:
            diagnostics.cleanup = "verified"
        finally:
            diagnostics.cleanup_container_state = getattr(
                owned, "cleanup_container_state", "not_observed"
            )
            diagnostics.cleanup_oom = getattr(owned, "cleanup_oom", "unknown")
    # No successful receipt, content, stderr or private config is emitted before cleanup.
    diagnostics.mark("receipt")
    print(
        json.dumps(
            {
                "scope": SCOPE,
                "source_tree": tree_sha,
                "declared_base_image": BASE,
                "declared_platform": PLATFORM,
                "two_uncached_builds": True,
                "actual_web_builds": 2,
                "artifacts_equal": True,
                "image_contents_equal": True,
                "base_inventory_equal": True,
                "network_none_containers": 14,
                "production_refusals_per_image": receipts[0]["production_refusals"],
                "cleanup_verified": True,
                "working_extraction_service": False,
                "production_ready": False,
                "oci_archive_bit_reproducibility_verified": False,
                "receipts": receipts,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def main() -> None:
    diagnostics = Diagnostics()
    try:
        execute(diagnostics)
    except Exception:
        diagnostics.capture()
        diagnostics.report()
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.stderr.write("SERVICE_PACKAGING_ACCEPTANCE_REFUSED\n")
        raise SystemExit(1) from None

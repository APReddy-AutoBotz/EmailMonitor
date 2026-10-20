"""Two owned service-artifact builds and network-none checks, never deployment."""

import json
import os
import platform
import re
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from base_inventory import validate_base_inventory
from run_xml_acceptance import bounded_process
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

    def inspect(self, kind: str, name: str) -> dict[str, Any] | None:
        if kind not in {"image", "container"}:
            raise PackagingRefused("service_package_resource_kind_refused")
        result = bounded_process(["docker", kind, "inspect", name], timeout=10)
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
        if image_id not in self.image_ids or ordinal not in (1, 2):
            raise PackagingRefused("service_package_image_identity_refused")
        image = self.owned("image", image_id)
        if image is None or image.get("Id") != image_id:
            raise PackagingRefused("service_package_image_identity_refused")
        case = "help" if probe is None else "probe"
        name = f"em-service-{self.owner}-{ordinal}-{case}"
        if self.inspect("container", name) is not None:
            raise PackagingRefused("service_package_resource_exists")
        self.containers.append(name)
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
                *([] if probe is None else ["--entrypoint=python"]),
                image_id,
                *([] if probe is None else ["-c", probe]),
            ],
            timeout=20,
        )
        if not re.fullmatch(rb"[a-f0-9]{64}\n", created):
            raise PackagingRefused("service_package_container_identity_refused")
        record = self.owned("container", name)
        if record is None:
            raise PackagingRefused("service_package_container_missing")
        validate_profile(record, image_id, probe)
        result = bounded_process(
            ["docker", "start", "--attach", name],
            timeout=45,
            stdout_limit=65536,
            stderr_limit=4096,
        )
        stopped = self.owned("container", name)
        state = stopped.get("State", {}) if stopped is not None else {}
        if (
            result.returncode
            or result.stderr
            or state.get("Running") is not False
            or state.get("ExitCode") != 0
            or state.get("OOMKilled") is not False
            or state.get("Error") not in (None, "")
        ):
            raise PackagingRefused("service_package_smoke_failed")
        return result.stdout

    def close(self) -> None:
        errors = []
        for kind, names in (("container", self.containers), ("image", self.images)):
            for name in reversed(names):
                try:
                    if self.owned(kind, name) is not None:
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
            "cli_help": True,
            "production_refusals": 5,
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


def main() -> None:
    require_ci(dict(os.environ))
    require_tool_versions(
        {
            name: command([name, "--version"]).decode("ascii").strip()
            for name in ("uv", "pnpm", "node")
        }
    )
    require_clean_source()
    tree_sha = (
        command(["git", "-C", str(ROOT), "rev-parse", "HEAD^{tree}"], timeout=10)
        .decode("ascii")
        .strip()
    )
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
    runtime = runtime_versions(exported)
    dockerfile = read(ROOT, "scripts/packaging/ServiceRuntime.Dockerfile")
    validate_dockerfile(dockerfile)
    probe = probe_source()
    owned = OwnedServiceBuilds(uuid4().hex)
    receipts = []
    try:
        with tempfile.TemporaryDirectory(prefix="em-service-packaging-") as temporary:
            for ordinal in (1, 2):
                command(["pnpm", "--dir", str(ROOT / "apps/web"), "build"], timeout=180)
                require_clean_source()
                files = collect_service(
                    ROOT, tree_sha, runtime, tracked_service_sources(ROOT, tree_sha)
                )
                bundle = archive(files)
                if verify_service_archive(bundle, files["manifest.json"]) != files:
                    raise PackagingRefused("service_package_roundtrip_refused")
                context = Path(temporary) / str(ordinal)
                materialize(files, context)
                (context / "Dockerfile").write_bytes(dockerfile)
                # Migration inputs remain in the archive, never in a runtime layer.
                (context / ".dockerignore").write_text("migrations\n", encoding="utf-8")
                image_id = owned.build(context, ordinal)
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
                smoke = validate_smoke(owned.smoke(image_id, ordinal, probe), files, runtime)
                receipts.append(
                    {
                        "archive_sha256": digest(bundle),
                        "manifest_sha256": digest(files["manifest.json"]),
                        "image_id": image_id,
                        "image_content_sha256": smoke["image_content_sha256"],
                        "base_inventory": smoke["base_inventory"],
                    }
                )
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
    finally:
        owned.close()
    # No successful receipt, content, stderr or private config is emitted before cleanup.
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
                "network_none_containers": 4,
                "production_refusals_per_image": 5,
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


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.stderr.write("SERVICE_PACKAGING_ACCEPTANCE_REFUSED\n")
        raise SystemExit(1) from None

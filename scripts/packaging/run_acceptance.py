"""Owned disposable CI builds; no deployment, registry push, listener or host changes."""

import json
import os
import platform
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from base_inventory import validate_base_inventory
from inventory_probe import inventory_probe
from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from artifacts import (
    BASE,
    PLATFORM,
    PackagingRefused,
    archive,
    collect,
    digest,
    materialize,
    verify_archive,
)

ROOT = Path(__file__).resolve().parents[2]
LABEL = "io.emailmonitor.metadata-prerequisite-owner"


def command(arguments: list[str], timeout: float = 180) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            arguments, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        raise PackagingRefused("package_command_failed") from None
    if result.returncode != 0 and arguments[:3] == ["docker", "start", "--attach"]:
        report_smoke_failure(result.returncode, result.stderr)
    if result.returncode != 0 or len(result.stdout) > 8 * 1024 * 1024:
        raise PackagingRefused("package_command_failed")
    return result


def report_smoke_failure(returncode: int, stderr: str) -> None:
    # Only a source-owned fixed reason may leave the disposable probe. Never emit
    # traceback text, arbitrary stderr, paths, source content or environment data.
    reasons = set(
        re.findall(
            r'raise RuntimeError\("(metadata_[a-z0-9_]+)"\)',
            (ROOT / "scripts/packaging/probe.py").read_text(),
        )
    )
    match = re.search(r"^RuntimeError: (metadata_[a-z0-9_]+)$", stderr, re.MULTILINE)
    reason = match.group(1) if match and match.group(1) in reasons else "unclassified_probe_failure"
    print(
        json.dumps(
            {"metadata_smoke_failure": {"returncode": returncode, "reason": reason}}, sort_keys=True
        ),
        flush=True,
    )


def runtime_versions(requirements: str) -> dict[str, str]:
    environment: dict[str, str] = {key: str(value) for key, value in default_environment().items()}
    environment.update(
        {
            "sys_platform": "linux",
            "platform_system": "Linux",
            "platform_machine": "x86_64",
            "python_version": "3.12",
            "python_full_version": "3.12.13",
            "implementation_name": "cpython",
            "implementation_version": "3.12.13",
            "extra": "",
            "platform_python_implementation": "CPython",
            "os_name": "posix",
        }
    )
    if len(requirements) > 65536 or len(requirements.splitlines()) > 128:
        raise PackagingRefused("package_export_refused")
    result = {}
    for line in requirements.splitlines():
        if not line.strip():
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            raise PackagingRefused("package_export_refused") from None
        if requirement.url or requirement.extras:
            raise PackagingRefused("package_export_refused")
        pins = list(requirement.specifier)
        if len(pins) != 1 or pins[0].operator != "==" or "*" in pins[0].version:
            raise PackagingRefused("package_export_refused")
        if requirement.marker is None or requirement.marker.evaluate(environment):
            name = str(canonicalize_name(requirement.name))
            if name in result:
                raise PackagingRefused("package_export_refused")
            result[name] = pins[0].version
    if not result or len(result) > 64:
        raise PackagingRefused("package_export_refused")
    return dict(sorted(result.items()))


def require_ci(environ: dict[str, str]) -> None:
    if (
        environ.get("GITHUB_ACTIONS") != "true"
        or environ.get("EM_REQUIRE_METADATA_PACKAGING") != "synthetic-test-only"
        or any(
            environ.get(key)
            for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")
        )
        or platform.system() != "Linux"
        or platform.machine() != "x86_64"
    ):
        raise PackagingRefused("package_ci_context_refused")


def require_tool_versions(versions: dict[str, str]) -> None:
    if (
        set(versions) != {"uv", "pnpm", "node"}
        or not re.fullmatch(r"uv 0\.12\.23(?: \([A-Za-z0-9 ._+-]{1,128}\))?", versions["uv"])
        or versions["pnpm"] != "11.25.0"
        or versions["node"] != "v24.19.0"
    ):
        raise PackagingRefused("package_tool_version_refused")


class OwnedBuilds:
    def __init__(self, owner: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{32}", owner):
            raise PackagingRefused("package_owner_refused")
        self.owner = owner
        self.images: list[str] = []
        self.containers: list[str] = []

    def inspect(self, kind: str, name: str) -> dict[str, Any] | None:
        if kind not in {"image", "container"}:
            raise PackagingRefused("package_resource_kind_refused")
        try:
            result = subprocess.run(
                ["docker", kind, "inspect", name],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise PackagingRefused("package_inspect_failed") from None
        if result.returncode:
            # A daemon/permission error is never interpreted as absence.
            expected = (
                f"Error: No such image: {name}",
                f"Error response from daemon: No such image: {name}",
                f"Error: No such container: {name}",
                f"Error: No such object: {name}",
                f"Error response from daemon: No such container: {name}",
            )
            if (
                result.returncode == 1
                and result.stdout.strip() in {"", "[]"}
                and result.stderr.strip() in expected
            ):
                return None
            raise PackagingRefused("package_inspect_failed")
        if len(result.stdout) > 131072:
            raise PackagingRefused("package_inspect_failed")
        value = json.loads(result.stdout)
        if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
            raise PackagingRefused("package_inspect_failed")
        return value[0]

    def owned(self, kind: str, name: str) -> dict[str, Any] | None:
        record = self.inspect(kind, name)
        if (
            record is not None
            and (record.get("Config", {}).get("Labels") or {}).get(LABEL) != self.owner
        ):
            raise PackagingRefused("package_resource_ownership_refused")
        return record

    def build(self, context: Path, ordinal: int) -> tuple[str, str]:
        if ordinal not in (1, 2):
            raise PackagingRefused("package_build_ordinal_refused")
        name = f"emailmonitor-metadata-prerequisite:{self.owner}-{ordinal}"
        if self.inspect("image", name) is not None:
            raise PackagingRefused("package_resource_exists")
        self.images.append(name)  # Register before the possibly ambiguous create/build result.
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
        )
        record = self.owned("image", name)
        if record is None or not re.fullmatch(r"sha256:[a-f0-9]{64}", record.get("Id", "")):
            raise PackagingRefused("package_built_image_missing")
        if record["Config"].get("User") != "65532:65532":
            raise PackagingRefused("package_image_user_refused")
        return name, record["Id"]

    def smoke(self, image: str, probe: str, ordinal: int) -> dict[str, Any]:
        if image not in self.images or self.owned("image", image) is None:
            raise PackagingRefused("package_smoke_image_refused")
        name = f"em-metadata-{self.owner}-{ordinal}"
        if self.inspect("container", name) is not None:
            raise PackagingRefused("package_resource_exists")
        self.containers.append(name)
        command(
            [
                "docker",
                "create",
                "--name",
                name,
                "--label",
                LABEL + "=" + self.owner,
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
                image,
                "python",
                "-c",
                probe,
            ],
            timeout=20,
        )
        record = self.owned("container", name)
        if record is None:
            raise PackagingRefused("package_container_missing")
        validate_container(record)
        result = command(["docker", "start", "--attach", name], timeout=30)
        state = self.owned("container", name)
        if (
            state is None
            or state["State"]["Running"] is not False
            or state["State"]["OOMKilled"] is not False
            or state["State"]["ExitCode"] != 0
            or result.stderr
        ):
            raise PackagingRefused("package_smoke_failed")
        if len(result.stdout) > 65536:
            raise PackagingRefused("package_smoke_output_refused")
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise PackagingRefused("package_smoke_output_refused")
        return value

    def close(self) -> None:
        errors = []
        for kind, names in (("container", self.containers), ("image", self.images)):
            for name in reversed(names):
                try:
                    if self.owned(kind, name) is not None:
                        command(["docker", kind, "rm", "--force", name], timeout=20)
                    if self.inspect(kind, name) is not None:
                        raise PackagingRefused("package_cleanup_incomplete")
                except Exception:
                    errors.append("package_cleanup_failed")
        if errors:
            raise PackagingRefused("package_cleanup_failed")


def validate_container(record: dict[str, Any]) -> None:
    config = record["HostConfig"]
    if (
        config["NetworkMode"] != "none"
        or config["Privileged"] is not False
        or config["CapAdd"]
        or config["CapDrop"] != ["ALL"]
        or config["SecurityOpt"] != ["no-new-privileges"]
        or config["ReadonlyRootfs"] is not True
        or config["Binds"]
        or config["Memory"] != 134217728
        or config["MemorySwap"] != 134217728
        or config["PidsLimit"] != 32
        or config["NanoCpus"] != 500000000
        or config["PortBindings"]
        or record["Config"]["User"] != "65532:65532"
        or config["Tmpfs"] != {"/tmp": "rw,noexec,nosuid,size=16m"}
        or any(
            mount.get("Type") != "tmpfs" or mount.get("Destination") != "/tmp"
            for mount in record["Mounts"]
        )
    ):
        raise PackagingRefused("package_isolation_refused")


def main() -> None:
    require_ci(dict(os.environ))
    versions = {
        name: command([name, "--version"]).stdout.strip() for name in ("uv", "pnpm", "node")
    }
    require_tool_versions(versions)
    print(json.dumps({"verified_build_tools": versions}, sort_keys=True), flush=True)
    command(["git", "diff", "--exit-code", "HEAD"], timeout=10)
    tree_sha = command(["git", "rev-parse", "HEAD^{tree}"], timeout=10).stdout.strip()
    exported = command(
        [
            "uv",
            "export",
            "--project",
            "services/backend",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--no-hashes",
            "--no-header",
            "--no-annotate",
        ]
    ).stdout
    runtime = runtime_versions(exported)
    probe = inventory_probe(ROOT, "metadata")
    dockerfile = (ROOT / "scripts/packaging/Metadata.Dockerfile").read_bytes()
    if dockerfile.count(BASE.encode()) != 2:
        raise PackagingRefused("package_base_refused")
    owned = OwnedBuilds(uuid4().hex)
    receipts = []
    try:
        with tempfile.TemporaryDirectory(prefix="em-metadata-prerequisite-") as temporary:
            for ordinal in (1, 2):
                command(["pnpm", "--dir", "apps/web", "build"])
                command(["git", "diff", "--exit-code", "HEAD"], timeout=10)
                files = collect(ROOT, tree_sha, runtime)
                bundle = archive(files)
                if verify_archive(bundle, tree_sha, runtime) != files:
                    raise PackagingRefused("package_archive_roundtrip_failed")
                context = Path(temporary) / str(ordinal)
                materialize(files, context)
                (context / "Dockerfile").write_bytes(dockerfile)
                # Explicit context has no Git, fixtures, tests, cache or credentials.
                (context / ".dockerignore").write_text("migrations\nstatic-web\ncontracts\n")
                image, identifier = owned.build(context, ordinal)
                smoke = owned.smoke(image, probe, ordinal)
                system = validate_base_inventory(smoke.get("base_inventory"))
                expected = {
                    "scope": "metadata-only-offline-prerequisite",
                    "working_extraction_service": False,
                    "production_ready": False,
                    "metadata_asgi": True,
                    "forged_tenant_404": True,
                    "fixture_code_absent": True,
                    "production_refusals": 8,
                    "interfaces": ["lo"],
                    "runtime_distributions": runtime,
                    "kernel_restrictions": True,
                    "network_errno": [101, 101],
                }
                if (
                    {key: smoke.get(key) for key in expected} != expected
                    or set(smoke) != set(expected) | {"image_content_sha256", "base_inventory"}
                    or not re.fullmatch(r"[a-f0-9]{64}", smoke["image_content_sha256"])
                ):
                    raise PackagingRefused("package_smoke_output_refused")
                receipts.append(
                    {
                        "archive_sha256": digest(bundle),
                        "manifest_sha256": digest(files["manifest.json"]),
                        "image_id": identifier,
                        "image_content_sha256": smoke["image_content_sha256"],
                        "base_inventory": system,
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
                raise PackagingRefused("package_reproducibility_refused")
    finally:
        owned.close()
        print(json.dumps({"metadata_owned_cleanup_verified": True}), flush=True)
    print(
        json.dumps(
            {
                "scope": "metadata-only-offline-prerequisite",
                "source_tree": tree_sha,
                "declared_base_image": BASE,
                "declared_platform": PLATFORM,
                "base_inventory_equal": True,
                "two_uncached_builds": True,
                "artifacts_equal": True,
                "image_contents_equal": True,
                "runtime_distribution_count": len(runtime),
                "network_none_smokes": 2,
                "production_refusals_per_smoke": 8,
                "cleanup_verified": True,
                "working_extraction_service": False,
                "production_ready": False,
                "oci_archive_bit_reproducibility_verified": False,
                "receipts": receipts,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

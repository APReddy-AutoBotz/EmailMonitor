"""Host-supplied fixed service image probe; no listener, grants or live credentials."""

import errno
import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import socket
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from base_inventory import collect_base_inventory

ROOT = Path("/opt/emailmonitor")
VENV = "services/backend/.venv"
SOURCE = "services/backend/src"
IMPORTS = (
    "emailmonitor.runtime.entrypoint",
    "emailmonitor.runtime.api_entrypoint",
    "emailmonitor.runtime.service_api",
    "emailmonitor.runtime.worker",
    "emailmonitor.runtime.service_publisher",
    "emailmonitor.runtime.database",
    "emailmonitor.extraction.fixture",
)
STAGES = frozenset(
    {"kernel", "layout", "imports", "models", "content", "base_inventory", "receipt"}
)


class ProbeDiagnostics:
    stage = "kernel"

    def mark(self, stage: str) -> None:
        if type(stage) is not str or stage not in STAGES:
            raise RuntimeError("service_image_diagnostic_refused")
        self.stage = stage

    def report(self) -> None:
        stage = self.stage if type(self.stage) is str and self.stage in STAGES else "kernel"
        sys.stderr.write(f"SERVICE_IMAGE_PROBE_REFUSED stage={stage}\n")


def regular_files(root: Path) -> set[str]:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("service_image_layout_refused")
    names: set[str] = set()
    for ordinal, path in enumerate(root.rglob("*"), 1):
        if ordinal > 512 or path.is_symlink():
            raise RuntimeError("service_image_layout_refused")
        if path.is_file():
            names.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise RuntimeError("service_image_layout_refused")
    return names


def verify_layout() -> tuple[dict[str, Any], dict[str, str]]:
    if (
        {path.name for path in ROOT.iterdir()}
        != {"services", "fixtures", "contracts", "static-web", "manifest.json", "notices"}
        or {path.name for path in (ROOT / "services").iterdir()} != {"backend"}
        or {path.name for path in (ROOT / "services/backend").iterdir()} != {".venv", "src"}
    ):
        raise RuntimeError("service_image_layout_refused")
    manifest_path = ROOT / "manifest.json"
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 262144:
        raise RuntimeError("service_image_manifest_refused")
    manifest = json.loads(manifest_path.read_bytes())
    if (
        manifest.get("scope") != "authored-source-service-reference"
        or manifest.get("production_ready") is not False
        or manifest.get("working_extraction_service") is not False
    ):
        raise RuntimeError("service_image_manifest_refused")
    for prefix in (SOURCE, "fixtures", "contracts", "static-web", "notices"):
        expected = {
            name.removeprefix(prefix + "/")
            for name in manifest["files"]
            if name.startswith(prefix + "/")
        }
        if not expected or regular_files(ROOT / prefix) != expected:
            raise RuntimeError("service_image_file_set_refused")
        for relative in expected:
            path = ROOT / prefix / relative
            if path.stat().st_size > 16 * 1024 * 1024:
                raise RuntimeError("service_image_source_integrity_refused")
            value = path.read_bytes()
            if manifest["files"][prefix + "/" + relative] != {
                "bytes": len(value),
                "sha256": hashlib.sha256(value).hexdigest(),
            }:
                raise RuntimeError("service_image_source_integrity_refused")
    distributions = {}
    for item in importlib.metadata.distributions():
        name = re.sub(r"[-_.]+", "-", item.metadata["Name"]).lower()
        if name in distributions:
            raise RuntimeError("service_image_distribution_duplicate")
        distributions[name] = item.version
    if distributions != manifest["runtime_distributions"]:
        raise RuntimeError("service_image_dependency_closure_refused")
    return manifest, distributions


def content_digest() -> str:
    """Defined /opt content equality, not OCI archive or whole-system equality."""
    records: dict[str, object] = {}
    total = 0
    for ordinal, path in enumerate(sorted(ROOT.rglob("*")), 1):
        name = path.relative_to(ROOT).as_posix()
        if ordinal > 20000:
            raise RuntimeError("service_image_cap_refused")
        if path.is_symlink():
            target = str(path.readlink())
            if not (
                (name == VENV + "/lib64" and target == "lib")
                or (
                    name in {VENV + "/bin/" + item for item in ("python", "python3", "python3.12")}
                    and target
                    in {
                        "python",
                        "/usr/local/bin/python",
                        "/usr/local/bin/python3",
                        "/usr/local/bin/python3.12",
                    }
                )
            ):
                raise RuntimeError("service_image_link_refused")
            records[name] = {"link": target}
        elif path.is_file():
            size = path.stat().st_size
            total += size
            if total > 512 * 1024 * 1024 or {"__pycache__", ".cache"} & set(path.parts):
                raise RuntimeError("service_image_cap_refused")
            value = hashlib.sha256()
            with path.open("rb") as source:
                for block in iter(lambda: source.read(65536), b""):
                    value.update(block)
            records[name] = {"bytes": size, "sha256": value.hexdigest()}
        elif path.is_dir():
            records[name] = {"directory": True}
        else:
            raise RuntimeError("service_image_layout_refused")
    return hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def installed_imports() -> None:
    for name in IMPORTS:
        importlib.import_module(name)
    from emailmonitor.extraction.fixture import article_bytes

    if not article_bytes("article-a.html"):
        raise RuntimeError("service_image_fixture_closure_refused")
    for name, module in tuple(sys.modules.items()):
        if name == "emailmonitor" or name.startswith("emailmonitor."):
            path = Path(module.__file__ or "")
            if not path.is_file() or not path.is_relative_to(ROOT / SOURCE):
                raise RuntimeError("service_image_import_closure_refused")


def model_refusals() -> None:
    from emailmonitor.runtime.api_entrypoint import ReferenceAPI
    from emailmonitor.runtime.worker import ServiceRuntimeConfig
    from pydantic import ValidationError

    # Each model must report the environment literal violation specifically;
    # missing test identities cannot be mistaken for a production-mode refusal.
    for model in (ReferenceAPI, ServiceRuntimeConfig):
        try:
            model.model_validate_json('{"environment":"production"}')
        except ValidationError as error:
            if not any(
                item["loc"] == ("environment",) and item["type"] == "literal_error"
                for item in error.errors()
            ):
                raise RuntimeError("service_image_production_literal_refused") from None
        else:
            raise RuntimeError("service_image_production_literal_refused")


def kernel_checks() -> list[int]:
    if os.getuid() != 65532 or os.getgid() != 65532 or sys.version_info[:3] != (3, 12, 13):
        raise RuntimeError("service_image_identity_refused")
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if any(
        status.get(key, "").strip() != expected
        for key, expected in {
            "CapEff": "0000000000000000",
            "CapBnd": "0000000000000000",
            "NoNewPrivs": "1",
            "Seccomp": "2",
        }.items()
    ):
        raise RuntimeError("service_image_kernel_refused")
    if not os.statvfs(ROOT).f_flag & os.ST_RDONLY:
        raise RuntimeError("service_image_read_only_refused")
    network_errno = []
    for family, target in (
        (socket.AF_INET, ("192.0.2.1", 443)),
        (socket.AF_INET6, ("2001:db8::1", 443)),
    ):
        with socket.socket(family, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.2)
            network_errno.append(connection.connect_ex(target))
    if network_errno != [errno.ENETUNREACH, errno.ENETUNREACH] or [
        name for _, name in socket.if_nameindex()
    ] != ["lo"]:
        raise RuntimeError("service_image_network_refused")
    return network_errno


def execute(diagnostics: ProbeDiagnostics) -> None:
    diagnostics.mark("kernel")
    network_errno = kernel_checks()
    diagnostics.mark("layout")
    manifest, distributions = verify_layout()
    diagnostics.mark("imports")
    installed_imports()
    diagnostics.mark("models")
    model_refusals()
    diagnostics.mark("content")
    image_content_sha256 = content_digest()
    diagnostics.mark("base_inventory")
    base_inventory = collect_base_inventory()
    diagnostics.mark("receipt")
    print(
        json.dumps(
            {
                "scope": "authored-source-service-reference",
                "production_ready": False,
                "working_extraction_service": False,
                "exact_source_closure": True,
                "source_file_count": sum(
                    name.startswith(SOURCE + "/") for name in manifest["files"]
                ),
                "installed_import_closure": True,
                "production_environment_literal_refusals": 2,
                "interfaces": ["lo"],
                "kernel_restrictions": True,
                "read_only_root": True,
                "network_errno": network_errno,
                "runtime_distributions": distributions,
                "manifest_sha256": hashlib.sha256(
                    (ROOT / "manifest.json").read_bytes()
                ).hexdigest(),
                "image_content_sha256": image_content_sha256,
                "base_inventory": base_inventory,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def main() -> None:
    diagnostics = ProbeDiagnostics()
    try:
        execute(diagnostics)
    except Exception:
        diagnostics.report()
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(1) from None

"""Host-supplied, fixed network-none image probe; never baked into an image."""

import errno
import hashlib
import importlib.metadata
import json
import os
import re
import socket
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from base_inventory import collect_base_inventory

ROOT = Path("/opt/emailmonitor")
# Independent expected layout. Acceptance tests require parity with the collector.
XML_FILES = (
    "__init__.py",
    "administration/__init__.py",
    "administration/binding.py",
    "config.py",
    "discovery/__init__.py",
    "discovery/planning.py",
    "extraction/__init__.py",
    "extraction/html.py",
    "extraction/pdf.py",
    "extraction/pdf_fixture.py",
    "extraction/sciencedirect.py",
    "extraction/xml_retained.py",
    "fetching/__init__.py",
    "fetching/fixture.py",
    "fetching/plan.py",
    "fetching/resources.py",
    "fetching/safety.py",
    "fetching/sciencedirect.py",
    "jobs/__init__.py",
    "jobs/models.py",
    "lifecycle/__init__.py",
    "lifecycle/errors.py",
    "organizations/__init__.py",
    "organizations/database.py",
    "organizations/roles.py",
    "parsing/__init__.py",
    "parsing/affiliation_diagnostic.py",
    "parsing/affiliation_diagnostic_worker.py",
    "parsing/pdf_protocol.py",
    "parsing/pdf_worker.py",
    "parsing/xml_protocol.py",
    "parsing/xml_worker.py",
    "progress/__init__.py",
    "progress/binding.py",
    "sources/__init__.py",
    "sources/access.py",
    "sources/filter_capabilities.py",
    "sources/policy.py",
    "sources/provider_documents.py",
    "sources/sciencedirect.py",
)
NOTICES = (
    "NOTICE.md",
    "reports/dependency-inventory.json",
    "reports/runtime-inventory.json",
    "reports/licenses/pypdf-6.20.1-LICENSE.txt",
    "reports/licenses/pypdf-6.20.1-SOURCE-NOTICES.txt",
)


def normalized(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def regular_files(root: Path) -> set[str]:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("xml_image_layout_refused")
    names: set[str] = set()
    count = 0
    directories: set[str] = set()
    for path in root.rglob("*"):
        count += 1
        if count > 256 or path.is_symlink():
            raise RuntimeError("xml_image_layout_refused")
        if path.is_file():
            names.add(path.relative_to(root).as_posix())
        elif path.is_dir():
            directories.add(path.relative_to(root).as_posix())
        else:
            raise RuntimeError("xml_image_layout_refused")
    expected_directories = {
        parent.as_posix() for name in names for parent in Path(name).parents if parent != Path(".")
    }
    if directories != expected_directories:
        raise RuntimeError("xml_image_layout_refused")
    return names


def content_digest() -> str:
    # Defined content equality under /opt/emailmonitor, not OCI export/config
    # timestamps or an assertion about system packages in the immutable base.
    records: dict[str, object] = {}
    total = 0
    count = 0
    for path in sorted(ROOT.rglob("*")):
        count += 1
        name = path.relative_to(ROOT).as_posix()
        if count > 20000:
            raise RuntimeError("xml_image_cap_refused")
        if path.is_symlink():
            target = str(path.readlink())
            if not (
                (name == ".venv/lib64" and target == "lib")
                or (
                    name in {".venv/bin/python", ".venv/bin/python3", ".venv/bin/python3.12"}
                    and target
                    in {
                        "python",
                        "/usr/local/bin/python",
                        "/usr/local/bin/python3",
                        "/usr/local/bin/python3.12",
                    }
                )
            ):
                raise RuntimeError("xml_image_link_refused")
            records[name] = {"link": target}
        elif path.is_file():
            size = path.stat().st_size
            total += size
            if total > 512 * 1024 * 1024 or any(
                part in {"__pycache__", ".cache"} for part in path.parts
            ):
                raise RuntimeError("xml_image_cap_refused")
            value = hashlib.sha256()
            with path.open("rb") as file:
                for block in iter(lambda: file.read(65536), b""):
                    value.update(block)
            records[name] = {"bytes": size, "sha256": value.hexdigest()}
        elif path.is_dir():
            records[name] = {"directory": True}
        else:
            raise RuntimeError("xml_image_layout_refused")
    return hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def verify_layout() -> dict[str, str]:
    if {path.name for path in ROOT.iterdir()} != {".venv", "src", "notices", "manifest.json"}:
        raise RuntimeError("xml_image_layout_refused")
    if regular_files(ROOT / "src") != {"emailmonitor/" + name for name in XML_FILES}:
        raise RuntimeError("xml_image_source_set_refused")
    if regular_files(ROOT / "notices") != set(NOTICES):
        raise RuntimeError("xml_image_notice_set_refused")
    manifest_path = ROOT / "manifest.json"
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 65536:
        raise RuntimeError("xml_image_manifest_refused")
    manifest = json.loads(manifest_path.read_bytes())
    if (
        manifest.get("scope") != "xml-worker-synthetic-prerequisite"
        or manifest.get("synthetic_test_only") is not True
        or manifest.get("fixture_assets_absent") is not True
        or manifest.get("working_extraction_service") is not False
        or manifest.get("full_service") is not False
        or manifest.get("production_ready") is not False
    ):
        raise RuntimeError("xml_image_manifest_refused")
    expected_files = {
        "xml-worker/pyproject.toml",
        "xml-worker/uv.lock",
        *("xml-worker/src/emailmonitor/" + name for name in XML_FILES),
        *("notices/" + name for name in NOTICES),
    }
    if set(manifest["files"]) != expected_files:
        raise RuntimeError("xml_image_manifest_refused")
    for name in sorted(expected_files - {"xml-worker/pyproject.toml", "xml-worker/uv.lock"}):
        target = ROOT / name.removeprefix("xml-worker/")
        expected = manifest["files"][name]
        if target.stat().st_size > 16 * 1024 * 1024:
            raise RuntimeError("xml_image_source_integrity_refused")
        actual = target.read_bytes()
        if expected != {"bytes": len(actual), "sha256": hashlib.sha256(actual).hexdigest()}:
            raise RuntimeError("xml_image_source_integrity_refused")
    distributions = {}
    for item in importlib.metadata.distributions():
        name = normalized(item.metadata["Name"])
        if name in distributions:
            raise RuntimeError("xml_image_distribution_duplicate")
        distributions[name] = item.version
    if distributions != manifest["runtime_distributions"]:
        raise RuntimeError("xml_image_runtime_closure_refused")
    return distributions


def main() -> None:
    if os.getuid() != 65532 or os.getgid() != 65532 or sys.version_info[:3] != (3, 12, 13):
        raise RuntimeError("xml_image_runtime_identity_refused")
    process_status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if any(
        process_status.get(key, "").strip() != expected
        for key, expected in {
            "CapEff": "0000000000000000",
            "CapBnd": "0000000000000000",
            "NoNewPrivs": "1",
            "Seccomp": "2",
        }.items()
    ):
        raise RuntimeError("xml_image_kernel_restrictions_refused")
    network_errno = []
    for family, target in (
        (socket.AF_INET, ("192.0.2.1", 443)),
        (socket.AF_INET6, ("2001:db8::1", 443)),
    ):
        with socket.socket(family, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.2)
            network_errno.append(connection.connect_ex(target))
    if network_errno != [errno.ENETUNREACH, errno.ENETUNREACH]:
        raise RuntimeError("xml_image_network_refused")
    if [name for _, name in socket.if_nameindex()] != ["lo"]:
        raise RuntimeError("xml_image_network_refused")
    distributions = verify_layout()
    from emailmonitor.parsing import affiliation_diagnostic_worker, pdf_worker, xml_worker  # noqa: F401

    loaded = {
        Path(module.__file__).relative_to(ROOT / "src/emailmonitor").as_posix()
        for name, module in sys.modules.items()
        if (name == "emailmonitor" or name.startswith("emailmonitor.")) and module.__file__
    }
    if loaded != set(XML_FILES):
        raise RuntimeError("xml_image_import_closure_refused")
    print(
        json.dumps(
            {
                "scope": "xml-worker-synthetic-prerequisite",
                "synthetic_test_only": True,
                "fixture_assets_absent": True,
                "working_extraction_service": False,
                "full_service": False,
                "production_ready": False,
                "exact_source_closure": True,
                "source_file_count": len(XML_FILES),
                "interfaces": ["lo"],
                "runtime_distributions": distributions,
                "kernel_restrictions": True,
                "network_errno": network_errno,
                "manifest_sha256": hashlib.sha256(
                    (ROOT / "manifest.json").read_bytes()
                ).hexdigest(),
                "image_content_sha256": content_digest(),
                "base_inventory": collect_base_inventory(),
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # No traceback, source contents, environment, XML or external text escapes.
        sys.stderr.write("XML_IMAGE_PROBE_REFUSED\n")
        raise SystemExit(1) from None

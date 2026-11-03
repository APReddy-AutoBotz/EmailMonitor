"""Exact synthetic XML worker inputs; never source assets or a complete service."""

import io
import re
import tarfile
from pathlib import Path

from artifacts import (
    BASE,
    MAX_BYTES,
    MAX_FILES,
    NOTICES,
    PLATFORM,
    PackagingRefused,
    archive,
    canonical,
    digest,
    materialize,
    read,
)

# Declared import-only closure of the ordinary and explicit diagnostic guests, including
# package initializers. Shared models currently import fixture helper CODE. No
# fixture/sample ASSETS, tests, credentials or unrelated source enter the context.
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
SCOPE = "xml-worker-synthetic-prerequisite"
REMAINING = [
    "real-identity-assembly",
    "working-extraction-runtime",
    "remaining-worker-packaging",
    "private-storage-secrets",
    "staging",
    "production-sbom-signing-license-security-review",
]


def validate_inputs(tree_sha: str, runtime: dict[str, str]) -> None:
    if not re.fullmatch(r"[a-f0-9]{40}", tree_sha):
        raise PackagingRefused("xml_package_source_tree_refused")
    if (
        not runtime
        or len(runtime) > 64
        or any(
            not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
            or not re.fullmatch(r"[A-Za-z0-9.+!-]{1,64}", version)
            for name, version in runtime.items()
        )
    ):
        raise PackagingRefused("xml_package_runtime_manifest_refused")


def manifest(files: dict[str, bytes], tree_sha: str, runtime: dict[str, str]) -> dict[str, object]:
    validate_inputs(tree_sha, runtime)
    return {
        "schema_version": "1.0",
        "scope": SCOPE,
        "synthetic_test_only": True,
        "fixture_assets_absent": True,
        "working_extraction_service": False,
        "full_service": False,
        "production_ready": False,
        "source_tree": tree_sha,
        "base_image": BASE,
        "platform": PLATFORM,
        "runtime_distributions": runtime,
        "files": {
            name: {"sha256": digest(content), "bytes": len(content)}
            for name, content in sorted(files.items())
            if name != "manifest.json"
        },
        "remaining": REMAINING,
    }


def required_files() -> set[str]:
    return {
        "manifest.json",
        "xml-worker/pyproject.toml",
        "xml-worker/uv.lock",
        *("xml-worker/src/emailmonitor/" + name for name in XML_FILES),
        *("notices/" + name for name in NOTICES),
    }


def collect(root: Path, tree_sha: str, runtime: dict[str, str]) -> dict[str, bytes]:
    validate_inputs(tree_sha, runtime)
    files = {
        "xml-worker/src/emailmonitor/" + name: read(
            root, "services/backend/src/emailmonitor/" + name
        )
        for name in XML_FILES
    }
    for name in ("pyproject.toml", "uv.lock"):
        files["xml-worker/" + name] = read(root, "services/backend/" + name)
    for name in NOTICES:
        files["notices/" + name] = read(root, name)
    files["manifest.json"] = canonical(manifest(files, tree_sha, runtime))
    archive(files)  # Shared exact path grammar, aggregate byte/file limits.
    return dict(sorted(files.items()))


def verify_archive(
    value: bytes, expected_tree: str, expected_runtime: dict[str, str]
) -> dict[str, bytes]:
    validate_inputs(expected_tree, expected_runtime)
    if not 0 < len(value) <= MAX_BYTES:
        raise PackagingRefused("xml_package_archive_refused")
    files: dict[str, bytes] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(value), mode="r:") as bundle:
            for member in bundle:
                if (
                    member.type != tarfile.REGTYPE
                    or member.sparse is not None
                    or member.uid != 0
                    or member.gid != 0
                    or member.mtime != 0
                    or member.mode != 0o644
                    or member.uname
                    or member.gname
                    or member.pax_headers
                    or member.name in files
                    or len(files) >= MAX_FILES
                    or member.size < 0
                    or total + member.size > MAX_BYTES
                ):
                    raise PackagingRefused("xml_package_archive_refused")
                total += member.size
                source = bundle.extractfile(member)
                if source is None:
                    raise PackagingRefused("xml_package_archive_refused")
                files[member.name] = source.read(MAX_BYTES + 1)
                if len(files[member.name]) != member.size:
                    raise PackagingRefused("xml_package_archive_refused")
    except tarfile.TarError:
        raise PackagingRefused("xml_package_archive_refused") from None
    if set(files) != required_files():
        raise PackagingRefused("xml_package_component_refused")
    if archive(files) != value:
        raise PackagingRefused("xml_package_archive_refused")
    # Exact canonical bytes also reject duplicate JSON keys and unknown fields.
    expected = canonical(manifest(files, expected_tree, expected_runtime))
    if files["manifest.json"] != expected:
        raise PackagingRefused("xml_package_manifest_refused")
    return files


__all__ = ["XML_FILES", "archive", "collect", "digest", "materialize", "verify_archive"]

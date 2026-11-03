"""Deterministic authored-source service package, with no deployed credentials."""

import hashlib
import json
import re
import subprocess
from pathlib import Path

from artifacts import MAX_BYTES, MAX_FILES, PackagingRefused, canonical, collect, digest, read


def git_blob_digest(body: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()


def tracked_service_sources(root: Path, tree_sha: str) -> dict[str, str]:
    """Read the exact committed tree's source inventory, never the ignore-filtered worktree."""
    if not re.fullmatch(r"[a-f0-9]{40}", tree_sha):
        raise PackagingRefused("service_source_inventory_refused")
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-tree",
                "-r",
                "-z",
                tree_sha,
                "--",
                "services/backend/src/emailmonitor",
            ],
            capture_output=True,
            check=True,
            timeout=10,
        )
        if len(result.stdout) > 131072:
            raise ValueError
        inventory: dict[str, str] = {}
        for entry in result.stdout.split(b"\0"):
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            mode, kind, blob = metadata.decode("ascii").split(" ")
            path = raw_path.decode("ascii")
            if not path.endswith(".py"):
                continue
            if mode not in {"100644", "100755"} or kind != "blob" or path in inventory:
                raise ValueError
            inventory[path] = blob
        return inventory
    except (ValueError, UnicodeError, OSError, subprocess.SubprocessError):
        raise PackagingRefused("service_source_inventory_refused") from None


def collect_service(
    root: Path, tree_sha: str, runtime: dict[str, str], source_blobs: dict[str, str]
) -> dict[str, bytes]:
    files = collect(root, tree_sha, runtime)
    old = json.loads(files.pop("manifest.json"))
    # Retain separate migration inputs; the runtime entrypoint never runs them.
    for name in tuple(files):
        if name.startswith("metadata-api/"):
            del files[name]
    source = root / "services/backend/src/emailmonitor"
    if not 1 <= len(source_blobs) < MAX_FILES or any(
        not re.fullmatch(r"services/backend/src/emailmonitor/[A-Za-z0-9_/]+\.py", name)
        or not re.fullmatch(r"[a-f0-9]{40}", blob)
        for name, blob in source_blobs.items()
    ):
        raise PackagingRefused("service_source_inventory_refused")
    present: set[str] = set()
    for path in source.rglob("*"):
        if path.is_symlink():
            raise PackagingRefused("package_links_refused")
        if path.is_file() and path.suffix == ".py":
            present.add(path.relative_to(root).as_posix())
    if present != set(source_blobs):
        raise PackagingRefused("service_source_inventory_refused")
    for name, expected in sorted(source_blobs.items()):
        body = read(root, name)
        if git_blob_digest(body) != expected:
            raise PackagingRefused("service_source_inventory_refused")
        files[name] = body
    for name in ("pyproject.toml", "uv.lock"):
        key = "services/backend/" + name
        files[key] = read(root, key)
    # Fixed authored corpus only. Never copy runtime data, downloads or configs.
    fixtures = (
        "html/article-a.html",
        "html/article-b.html",
        "html/no-contact.html",
        "html/search-page-1.html",
        "html/search-page-2.html",
        "html/tooltip.html",
        "pdf/ambiguous.pdf",
        "pdf/article-a.pdf",
        "pdf/article-b.pdf",
        "pdf/corrupt.pdf",
        "pdf/encrypted.pdf",
        "pdf/no-contact.pdf",
        "pdf/page-cap.pdf",
        "pdf/scanned.pdf",
        "pdf/wrapped.pdf",
        "README.md",
    )
    for name in fixtures:
        files["fixtures/" + name] = read(root, "fixtures/" + name)
    if len(files) >= MAX_FILES or sum(map(len, files.values())) > MAX_BYTES:
        raise PackagingRefused("package_cap_refused")
    files["manifest.json"] = canonical(
        {
            **old,
            "scope": "authored-source-service-reference",
            "production_ready": False,
            "working_extraction_service": False,
            "service_authority": "explicit-registered-principal-scoped-delegation",
            "identity_mode": "explicit-test-provider-composition-only",
            "entrypoints": {
                "api": "python -m emailmonitor.runtime.entrypoint api --config FILE",
                "worker": "python -m emailmonitor.runtime.entrypoint worker --config FILE",
                "publisher": "python -m emailmonitor.runtime.entrypoint publish-once --config FILE",
            },
            "files": {
                name: {"sha256": digest(body), "bytes": len(body)}
                for name, body in sorted(files.items())
            },
            "remaining": [
                "actual-service-operator-acceptance",
                "real-identity-assembly",
                "private-storage-secrets",
                "staging",
                "production-security-license-review",
            ],
        }
    )
    return dict(sorted(files.items()))


def verify_service_archive(value: bytes, expected_manifest: bytes) -> dict[str, bytes]:
    """Verify against the caller's separately retained build receipt, not self-asserted hashes."""
    import io
    import re
    import tarfile

    if not 0 < len(value) <= MAX_BYTES or len(expected_manifest) > 262_144:
        raise PackagingRefused("service_package_refused")
    try:
        manifest = json.loads(expected_manifest)
        if (
            manifest["scope"] != "authored-source-service-reference"
            or manifest["production_ready"] is not False
            or not re.fullmatch(r"[a-f0-9]{40}", manifest["source_tree"])
            or canonical(manifest) != expected_manifest
        ):
            raise ValueError
        expected = manifest["files"]
        if not isinstance(expected, dict) or not 1 <= len(expected) < MAX_FILES:
            raise ValueError
        files: dict[str, bytes] = {}
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
                    or not re.fullmatch(r"[A-Za-z0-9_./-]{1,99}", member.name)
                    or member.name.startswith("/")
                    or any(part in {"", ".", ".."} for part in member.name.split("/"))
                    or not 0 <= member.size <= MAX_BYTES
                ):
                    raise ValueError
                stream = bundle.extractfile(member)
                if stream is None:
                    raise ValueError
                files[member.name] = stream.read(MAX_BYTES + 1)
                if sum(map(len, files.values())) > MAX_BYTES:
                    raise ValueError
        if files.pop("manifest.json") != expected_manifest or set(files) != set(expected):
            raise ValueError
        if any(
            expected[name] != {"sha256": digest(body), "bytes": len(body)}
            for name, body in files.items()
        ):
            raise ValueError
        files["manifest.json"] = expected_manifest
        return dict(sorted(files.items()))
    except (ValueError, KeyError, TypeError, tarfile.TarError, OSError):
        raise PackagingRefused("service_package_refused") from None

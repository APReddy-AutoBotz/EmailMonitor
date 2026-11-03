"""Deterministic metadata-only prerequisite inputs, never a deployment or restore tool."""

import ast
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path
from typing import Any

BASE = (
    "python:3.12.13-slim-bookworm@sha256:"
    "4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2"
)
PLATFORM = "linux/amd64"
MAX_BYTES = 16 * 1024 * 1024
MAX_FILES = 256
API_FILES = ("__init__.py", "config.py", "api.py")
NOTICES = (
    "NOTICE.md",
    "reports/dependency-inventory.json",
    "reports/runtime-inventory.json",
    "reports/licenses/pypdf-6.20.1-LICENSE.txt",
    "reports/licenses/pypdf-6.20.1-SOURCE-NOTICES.txt",
)
REMAINING = [
    "real-identity-assembly",
    "working-extraction-runtime",
    "worker-packaging",
    "private-storage-secrets",
    "staging",
    "production-sbom-signing-license-security-review",
]


class PackagingRefused(RuntimeError):
    """Fixed safe refusal, with no source/configuration content in errors."""


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read(root: Path, relative: str) -> bytes:
    path = root / relative
    if root.is_symlink() or any(part.is_symlink() for part in (path, *path.parents)):
        raise PackagingRefused("package_links_refused")
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise PackagingRefused("package_input_refused")
    return path.read_bytes()


def migration_head(files: dict[str, bytes]) -> str:
    chain: dict[str, str | None] = {}
    for name, content in files.items():
        if not re.fullmatch(r"migrations/migrations/versions/[0-9]{4}_[a-z_]+\.py", name):
            continue
        try:
            tree = ast.parse(content)
        except SyntaxError:
            raise PackagingRefused("package_migration_chain_refused") from None
        values: dict[str, Any] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                    values[target.id] = ast.literal_eval(node.value)
        revision, parent = values.get("revision"), values.get("down_revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9]{4}_[a-z_]+", revision):
            raise PackagingRefused("package_migration_chain_refused")
        if parent is not None and not isinstance(parent, str):
            raise PackagingRefused("package_migration_chain_refused")
        if revision != Path(name).stem or revision in chain or name[:-3] + ".sql" not in files:
            raise PackagingRefused("package_migration_chain_refused")
        chain[revision] = parent
    python_stems = {
        name[:-3]
        for name in files
        if re.fullmatch(r"migrations/migrations/versions/[0-9]{4}_[a-z_]+\.py", name)
    }
    sql_stems = {
        name[:-4]
        for name in files
        if re.fullmatch(r"migrations/migrations/versions/[0-9]{4}_[a-z_]+\.sql", name)
    }
    if python_stems != sql_stems:
        raise PackagingRefused("package_migration_chain_refused")
    if not chain or len(chain) > 32:
        raise PackagingRefused("package_migration_chain_refused")
    heads = set(chain) - {value for value in chain.values() if value is not None}
    if len(heads) != 1:
        raise PackagingRefused("package_migration_chain_refused")
    head = next(iter(heads))
    visited: set[str] = set()
    current: str | None = head
    while current is not None:
        if current not in chain or current in visited:
            raise PackagingRefused("package_migration_chain_refused")
        visited.add(current)
        current = chain[current]
    if visited != set(chain):
        raise PackagingRefused("package_migration_chain_refused")
    return head


def collect(root: Path, tree_sha: str, runtime: dict[str, str]) -> dict[str, bytes]:
    if not re.fullmatch(r"[a-f0-9]{40}", tree_sha):
        raise PackagingRefused("package_source_tree_refused")
    if (
        not runtime
        or len(runtime) > 64
        or any(
            not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
            or not re.fullmatch(r"[A-Za-z0-9.+!-]{1,64}", version)
            for name, version in runtime.items()
        )
    ):
        raise PackagingRefused("package_runtime_manifest_refused")
    files: dict[str, bytes] = {}
    for name in API_FILES:
        files["metadata-api/src/emailmonitor/" + name] = read(
            root, "services/backend/src/emailmonitor/" + name
        )
    for name in ("pyproject.toml", "uv.lock"):
        files["metadata-api/" + name] = read(root, "services/backend/" + name)
    files["migrations/alembic.ini"] = read(root, "services/backend/alembic.ini")
    files["migrations/migrations/env.py"] = read(root, "services/backend/migrations/env.py")
    versions = root / "services/backend/migrations/versions"
    if versions.is_symlink():
        raise PackagingRefused("package_links_refused")
    for path in sorted(versions.iterdir()):
        if path.name == "__pycache__" and path.is_dir() and not path.is_symlink():
            continue
        if not re.fullmatch(r"[0-9]{4}_[a-z_]+\.(py|sql)", path.name):
            raise PackagingRefused("package_migration_input_refused")
        files["migrations/migrations/versions/" + path.name] = read(
            root, str(path.relative_to(root))
        )
    web = root / "apps/web/dist"
    if web.is_symlink():
        raise PackagingRefused("package_links_refused")
    assets = []
    for path in sorted(web.rglob("*")):
        if path.is_symlink():
            raise PackagingRefused("package_links_refused")
        if path.is_dir():
            continue
        name = path.relative_to(web).as_posix()
        if name != "index.html" and not re.fullmatch(
            r"assets/index-[A-Za-z0-9_-]{8}\.(js|css)", name
        ):
            raise PackagingRefused("package_web_input_refused")
        assets.append(name)
        files["static-web/" + name] = read(root, str(path.relative_to(root)))
    if "index.html" not in assets or len(assets) > 20 or not any(x.endswith(".js") for x in assets):
        raise PackagingRefused("package_web_input_refused")
    for name in NOTICES:
        files["notices/" + name] = read(root, name)
    for path in sorted((root / "contracts").glob("*.schema.json")):
        files["contracts/" + path.name] = read(root, str(path.relative_to(root)))
    if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_BYTES:
        raise PackagingRefused("package_cap_refused")
    manifest = {
        "schema_version": "1.0",
        "scope": "metadata-only-offline-prerequisite",
        "working_extraction_service": False,
        "production_ready": False,
        "source_tree": tree_sha,
        "base_image": BASE,
        "platform": PLATFORM,
        "migration_head": migration_head(files),
        "migration_mode": "forward-only-separate-identity",
        "runtime_distributions": runtime,
        "files": {
            name: {"sha256": digest(content), "bytes": len(content)}
            for name, content in sorted(files.items())
        },
        "remaining": REMAINING,
    }
    files["manifest.json"] = canonical(manifest)
    return dict(sorted(files.items()))


def archive(files: dict[str, bytes]) -> bytes:
    if not files or len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_BYTES:
        raise PackagingRefused("package_cap_refused")
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as bundle:
        for name, content in sorted(files.items()):
            if (
                not re.fullmatch(r"[A-Za-z0-9_./-]{1,99}", name)
                or name.startswith("/")
                or any(part in {"", ".", ".."} for part in name.split("/"))
            ):
                raise PackagingRefused("package_archive_path_refused")
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.uid, entry.gid, entry.mtime = len(content), 0o644, 0, 0, 0
            entry.uname = entry.gname = ""
            bundle.addfile(entry, io.BytesIO(content))
    if output.tell() > MAX_BYTES:
        raise PackagingRefused("package_cap_refused")
    return output.getvalue()


def materialize(files: dict[str, bytes], destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise PackagingRefused("package_owned_destination_required")
    # Validate all names and bounds before creating any output.
    archive(files)
    destination.mkdir(mode=0o700)
    for name, content in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as file:
            file.write(content)
        path.chmod(0o644)


def verify_archive(
    value: bytes, expected_tree: str, expected_runtime: dict[str, str]
) -> dict[str, bytes]:
    if not 0 < len(value) <= MAX_BYTES:
        raise PackagingRefused("package_archive_refused")
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
                    or member.size > MAX_BYTES
                    or member.size < 0
                    or total + member.size > MAX_BYTES
                ):
                    raise PackagingRefused("package_archive_refused")
                total += member.size
                source = bundle.extractfile(member)
                if source is None:
                    raise PackagingRefused("package_archive_refused")
                files[member.name] = source.read(MAX_BYTES + 1)
                if len(files[member.name]) != member.size:
                    raise PackagingRefused("package_archive_refused")
    except tarfile.TarError:
        raise PackagingRefused("package_archive_refused") from None
    archive(files)  # Reapply path grammar and aggregate bounds; never extract to disk.
    try:
        manifest = json.loads(files["manifest.json"])
    except (KeyError, ValueError):
        raise PackagingRefused("package_manifest_refused") from None
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "1.0"
        or manifest.get("source_tree") != expected_tree
        or not re.fullmatch(r"[a-f0-9]{40}", expected_tree)
        or manifest.get("runtime_distributions") != expected_runtime
        or not expected_runtime
        or len(expected_runtime) > 64
        or any(
            not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
            or not re.fullmatch(r"[A-Za-z0-9.+!-]{1,64}", version)
            for name, version in expected_runtime.items()
        )
        or manifest.get("scope") != "metadata-only-offline-prerequisite"
        or manifest.get("working_extraction_service") is not False
        or manifest.get("production_ready") is not False
        or manifest.get("base_image") != BASE
        or manifest.get("platform") != PLATFORM
        or manifest.get("migration_head") != migration_head(files)
        or manifest.get("migration_mode") != "forward-only-separate-identity"
        or manifest.get("remaining") != REMAINING
    ):
        raise PackagingRefused("package_manifest_refused")
    required = {
        "manifest.json",
        "metadata-api/pyproject.toml",
        "metadata-api/uv.lock",
        "migrations/alembic.ini",
        "migrations/migrations/env.py",
        "static-web/index.html",
        *("metadata-api/src/emailmonitor/" + name for name in API_FILES),
        *("notices/" + name for name in NOTICES),
    }
    if not required <= files.keys() or any(
        name not in required
        and not re.fullmatch(r"migrations/migrations/versions/[0-9]{4}_[a-z_]+\.(py|sql)", name)
        and not re.fullmatch(r"static-web/assets/index-[A-Za-z0-9_-]{8}\.(js|css)", name)
        and not re.fullmatch(r"contracts/[A-Za-z0-9_-]+\.schema\.json", name)
        for name in files
    ):
        raise PackagingRefused("package_component_refused")
    web_assets = [name for name in files if name.startswith("static-web/")]
    if len(web_assets) > 20 or not any(name.endswith(".js") for name in web_assets):
        raise PackagingRefused("package_component_refused")
    expected = {
        name: {"sha256": digest(content), "bytes": len(content)}
        for name, content in files.items()
        if name != "manifest.json"
    }
    if manifest.get("files") != expected:
        raise PackagingRefused("package_manifest_refused")
    if set(manifest) != {
        "schema_version",
        "scope",
        "working_extraction_service",
        "production_ready",
        "source_tree",
        "base_image",
        "platform",
        "migration_head",
        "migration_mode",
        "runtime_distributions",
        "files",
        "remaining",
    }:
        raise PackagingRefused("package_manifest_refused")
    return files

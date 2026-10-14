"""Pure artifact/ownership grammar and minimal in-process API import; no Docker or services."""

import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

from artifacts import API_FILES, PackagingRefused, archive, collect, materialize
from run_acceptance import LABEL, OwnedBuilds, require_ci, runtime_versions, validate_container

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def inputs(tmp_path: Path) -> Path:
    values = {
        "services/backend/pyproject.toml": "[project]\nname='synthetic'\n",
        "services/backend/uv.lock": "version=1\n",
        "services/backend/alembic.ini": "[alembic]\n",
        "services/backend/migrations/env.py": "# separate migration identity\n",
        "services/backend/migrations/versions/0001_synthetic.py": (
            "revision='0001_synthetic'\ndown_revision=None\n"
        ),
        "services/backend/migrations/versions/0001_synthetic.sql": "SELECT 1;\n",
        "apps/web/dist/index.html": '<script src="/assets/index-12345678.js"></script>',
        "apps/web/dist/assets/index-12345678.js": "// synthetic compiled asset\n",
        "NOTICE.md": "No project distribution license selected\n",
        "reports/dependency-inventory.json": "{}",
        "reports/runtime-inventory.json": "{}",
        "reports/licenses/pypdf-6.20.1-LICENSE.txt": "synthetic notice",
        "reports/licenses/pypdf-6.20.1-SOURCE-NOTICES.txt": "synthetic notice",
        "contracts/synthetic.schema.json": "{}",
    }
    values.update(
        {"services/backend/src/emailmonitor/" + name: "# synthetic source\n" for name in API_FILES}
    )
    for name, value in values.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    return tmp_path


def package(root: Path) -> dict[str, bytes]:
    return collect(root, "a" * 40, {"fastapi": "0.143.0"})


def test_two_artifacts_are_byte_identical_despite_mtimes_and_iteration_order(inputs: Path) -> None:
    first = package(inputs)
    for path in inputs.rglob("*"):
        os.utime(path, (12345678, 12345678))
    second = package(inputs)
    assert first == second
    assert archive(first) == archive(dict(reversed(list(second.items()))))
    with tarfile.open(fileobj=io.BytesIO(archive(first))) as bundle:
        assert all(
            m.uid == m.gid == m.mtime == 0 and m.mode == 0o644 and m.isfile() for m in bundle
        )
    manifest = json.loads(first["manifest.json"])
    assert manifest["working_extraction_service"] is manifest["production_ready"] is False
    assert manifest["migration_head"] == "0001_synthetic"


def test_allowlist_never_copies_test_fixtures_caches_or_ambient_credentials(inputs: Path) -> None:
    for name in (
        ".env",
        "fixtures/private/auth.json",
        "services/backend/tests/secret.py",
        "services/backend/src/emailmonitor/identity/fixture.py",
        "apps/web/node_modules/secret",
    ):
        path = inputs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("DO_NOT_DISTRIBUTE_SYNTHETIC_SENTINEL")
    assert b"DO_NOT_DISTRIBUTE_SYNTHETIC_SENTINEL" not in archive(package(inputs))
    assert set(name for name in package(inputs) if name.startswith("metadata-api/src/")) == {
        "metadata-api/src/emailmonitor/" + name for name in API_FILES
    }


@pytest.mark.parametrize(
    "relative",
    [
        "services/backend/src/emailmonitor/api.py",
        "apps/web/dist/assets/index-12345678.js",
        "services/backend/migrations/versions/0001_synthetic.sql",
    ],
)
def test_symlink_inputs_refuse_before_packaging(inputs: Path, relative: str) -> None:
    path = inputs / relative
    path.unlink()
    path.symlink_to(inputs / "NOTICE.md")
    with pytest.raises(PackagingRefused, match="links"):
        package(inputs)


@pytest.mark.parametrize(
    "relative", ["apps/web/dist/source.map", "services/backend/migrations/versions/extra.env"]
)
def test_unexpected_generated_inputs_refuse(inputs: Path, relative: str) -> None:
    (inputs / relative).write_text("synthetic")
    with pytest.raises(PackagingRefused):
        package(inputs)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/../escape", "a//b", "a/./b"])
def test_tar_path_escape_refuses(name: str) -> None:
    with pytest.raises(PackagingRefused):
        archive({name: b"synthetic"})


def test_existing_destination_refuses_without_overwriting(inputs: Path) -> None:
    with pytest.raises(PackagingRefused):
        materialize(package(inputs), inputs)


@pytest.mark.parametrize("parent", ["missing", "0001_synthetic"])
def test_missing_or_cyclic_migration_parent_refuses(inputs: Path, parent: str) -> None:
    (inputs / "services/backend/migrations/versions/0001_synthetic.py").write_text(
        f"revision='0001_synthetic'\ndown_revision={parent!r}\n"
    )
    with pytest.raises(PackagingRefused, match="chain"):
        package(inputs)


def test_runtime_export_markers_extras_closure_and_versions() -> None:
    result = runtime_versions(
        "PyJWT==2.15.1\ncryptography==50.0.2\n"
        "cffi==2.1.1 ; implementation_name == 'cpython'\n"
        "pycparser==3.11\ntzdata==2026.5 ; sys_platform == 'win32'\n"
    )
    assert result == {
        "pyjwt": "2.15.1",
        "cryptography": "50.0.2",
        "cffi": "2.1.1",
        "pycparser": "3.11",
    }
    assert runtime_versions("tzdata==2026.5\n") == {"tzdata": "2026.5"}


@pytest.mark.parametrize(
    "requirements",
    [
        "",
        "httpx>=1",
        "name @ https://invalid.example/x",
        "pyjwt[crypto]==2.15.1",
        "name==1\nname==2",
    ],
)
def test_unpinned_or_unexpected_exports_refuse(requirements: str) -> None:
    with pytest.raises(PackagingRefused):
        runtime_versions(requirements)


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_ACTIONS", "false"),
        ("EM_REQUIRE_METADATA_PACKAGING", "true"),
        ("DOCKER_HOST", "ssh://foreign"),
        ("DOCKER_CONTEXT", "foreign"),
        ("DOCKER_TLS_VERIFY", "1"),
        ("DOCKER_CERT_PATH", "/foreign"),
    ],
)
def test_actual_build_requires_exact_ci_context(key: str, value: str) -> None:
    env = {
        "GITHUB_ACTIONS": "true",
        "EM_REQUIRE_METADATA_PACKAGING": "synthetic-test-only",
        key: value,
    }
    with pytest.raises(PackagingRefused):
        require_ci(env)


def container() -> dict[str, Any]:
    return {
        "Config": {"User": "65532:65532"},
        "Mounts": [],
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
        },
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("NetworkMode", "host"),
        ("Privileged", True),
        ("CapAdd", ["SYS_ADMIN"]),
        ("CapDrop", []),
        ("SecurityOpt", []),
        ("ReadonlyRootfs", False),
        ("Binds", ["/var/run/docker.sock:/socket"]),
        ("Memory", 0),
        ("MemorySwap", -1),
        ("PidsLimit", -1),
        ("NanoCpus", 0),
        ("PortBindings", {"8000/tcp": [{}]}),
        ("Tmpfs", {"/tmp": "exec"}),
    ],
)
def test_runtime_profile_cannot_expand(key: str, value: object) -> None:
    value_record = container()
    value_record["HostConfig"][key] = value
    with pytest.raises(PackagingRefused):
        validate_container(value_record)


def test_exact_profile_accepts_and_foreign_mount_or_user_refuses() -> None:
    validate_container(container())
    for change in (
        {"Config": {"User": "0:0"}},
        {"Mounts": [{"Type": "bind", "Destination": "/tmp"}]},
    ):
        with pytest.raises(PackagingRefused):
            validate_container({**container(), **change})


def test_build_timeout_still_reconciles_only_registered_owned_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    owner = OwnedBuilds("a" * 32)
    state: dict[str, bool] = {"exists": False}
    calls: list[list[str]] = []

    def inspect(kind: str, name: str) -> dict[str, Any] | None:
        return {"Config": {"Labels": {LABEL: owner.owner}}} if state["exists"] else None

    def run(arguments: list[str], timeout: float = 180) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments[1] == "build":
            state["exists"] = True
            raise PackagingRefused("package_command_failed")
        state["exists"] = False
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(owner, "inspect", inspect)
    monkeypatch.setattr("run_acceptance.command", run)
    with pytest.raises(PackagingRefused):
        owner.build(tmp_path, 1)
    owner.close()
    assert calls[-1][:4] == ["docker", "image", "rm", "--force"]
    assert owner.images[0] == calls[-1][-1] and not state["exists"]


def test_unknown_cleanup_ownership_never_removes_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = OwnedBuilds("b" * 32)
    owner.images = ["exact-owned-name"]
    calls: list[object] = []
    monkeypatch.setattr(
        owner, "inspect", lambda kind, name: {"Config": {"Labels": {LABEL: "foreign"}}}
    )
    monkeypatch.setattr("run_acceptance.command", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(PackagingRefused, match="cleanup"):
        owner.close()
    assert not calls


def test_actual_minimal_api_import_has_no_fixture_modules_and_needs_no_listener(
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "emailmonitor"
    package_path.mkdir()
    for name in API_FILES:
        (package_path / name).write_bytes(
            (ROOT / "services/backend/src/emailmonitor" / name).read_bytes()
        )
    env = {key: value for key, value in os.environ.items() if not key.startswith("EMAILMONITOR_")}
    env["PYTHONPATH"] = str(tmp_path) + os.pathsep + str(ROOT / "scripts/packaging")
    script = """import asyncio,json,sys
from probe import response
async def check():
 assert await response('/healthz') == (200,{'status':'ok'})
 assert (await response('/api/v1/jobs','POST'))[0] == 404
 assert (await response('/api/v1/capabilities'))[1]['tenant_data_api_available'] is False
asyncio.run(check())
modules = {x for x in sys.modules if x == 'emailmonitor' or x.startswith('emailmonitor.')}
assert modules == {'emailmonitor','emailmonitor.api','emailmonitor.config'}
print('minimal_metadata_only_passed')
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "minimal_metadata_only_passed"


def test_actual_archive_roundtrip_verifies_every_component_and_tamper_refuses(inputs: Path) -> None:
    from artifacts import verify_archive

    files = package(inputs)
    assert verify_archive(archive(files), "a" * 40, {"fastapi": "0.143.0"}) == files
    changed = {**files, "migrations/migrations/versions/0001_synthetic.sql": b"SELECT 2;\n"}
    with pytest.raises(PackagingRefused, match="manifest"):
        verify_archive(archive(changed), "a" * 40, {"fastapi": "0.143.0"})
    manifest = json.loads(files["manifest.json"])
    manifest["production_ready"] = True
    with pytest.raises(PackagingRefused, match="manifest"):
        verify_archive(
            archive({**files, "manifest.json": json.dumps(manifest).encode()}),
            "a" * 40,
            {"fastapi": "0.143.0"},
        )


def test_orphan_migration_sql_refuses(inputs: Path) -> None:
    (inputs / "services/backend/migrations/versions/0002_orphan.sql").write_text("SELECT 2;")
    with pytest.raises(PackagingRefused, match="chain"):
        package(inputs)


@pytest.mark.parametrize(
    "stdout,stderr,allowed",
    [
        ("[]\n", "Error response from daemon: No such image: unique-owned-name\n", True),
        ("", "Error: No such object: unique-owned-name\n", True),
        ("[]\n", "permission denied while trying to connect to the Docker daemon socket", False),
        ("", "Error: No such object: another-name", False),
    ],
)
def test_only_exact_missing_resource_is_absence(
    monkeypatch: pytest.MonkeyPatch, stdout: str, stderr: str, allowed: bool
) -> None:
    monkeypatch.setattr(
        "run_acceptance.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, stdout, stderr),
    )
    owner = OwnedBuilds("c" * 32)
    if allowed:
        assert owner.inspect("image", "unique-owned-name") is None
    else:
        with pytest.raises(PackagingRefused, match="inspect"):
            owner.inspect("image", "unique-owned-name")


def test_container_create_timeout_still_reconciles_owned_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = OwnedBuilds("d" * 32)
    owner.images = ["owned-image"]
    existing = {("image", "owned-image")}
    calls: list[list[str]] = []

    def inspect(kind: str, name: str) -> dict[str, Any] | None:
        return {"Config": {"Labels": {LABEL: owner.owner}}} if (kind, name) in existing else None

    def run(arguments: list[str], timeout: float = 180) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments[1] == "create":
            existing.add(("container", owner.containers[0]))
            raise PackagingRefused("package_command_failed")
        existing.discard((arguments[1], arguments[-1]))
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(owner, "inspect", inspect)
    monkeypatch.setattr("run_acceptance.command", run)
    with pytest.raises(PackagingRefused):
        owner.smoke("owned-image", "# fixed probe", 1)
    owner.close()
    removals = [call for call in calls if call[2:4] == ["rm", "--force"]]
    assert removals == [
        ["docker", "container", "rm", "--force", owner.containers[0]],
        ["docker", "image", "rm", "--force", "owned-image"],
    ]
    assert not existing


def test_dockerfile_and_workflow_use_existing_pins_and_no_distribution_or_listener() -> None:
    from artifacts import BASE

    dockerfile = (ROOT / "scripts/packaging/Metadata.Dockerfile").read_text()
    assert dockerfile.count(BASE) == 2
    assert "uv sync --locked --no-dev" in dockerfile
    assert "USER 65532:65532" in dockerfile and "EXPOSE " not in dockerfile
    assert (
        "working_extraction_service=false" in dockerfile and "production_ready=false" in dockerfile
    )
    workflow = (ROOT / ".github/workflows/metadata-packaging.yml").read_text()
    assert "contents: read" in workflow and "persist-credentials: false" in workflow
    for prohibited in (
        "pull_request_target",
        "secrets.",
        "docker login",
        "--push",
        "privileged",
        "--network=host",
    ):
        assert prohibited not in workflow + dockerfile


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "999"),
        ("source_tree", "b" * 40),
        ("source_tree", "not-a-tree"),
        ("runtime_distributions", {"unlocked": "0"}),
        ("migration_mode", "unsafe"),
        ("remaining", []),
        ("unknown", True),
    ],
)
def test_archive_provenance_and_scope_are_verified_against_trusted_inputs(
    inputs: Path, field: str, value: object
) -> None:
    from artifacts import verify_archive

    files = package(inputs)
    manifest = json.loads(files["manifest.json"])
    manifest[field] = value
    files["manifest.json"] = json.dumps(manifest).encode()
    with pytest.raises(PackagingRefused, match="manifest"):
        verify_archive(archive(files), "a" * 40, {"fastapi": "0.143.0"})


@pytest.mark.parametrize(
    "name", ["static-web/source.map", "migrations/migrations/versions/extra.env", "other/file"]
)
def test_self_consistent_unknown_archive_components_refuse(inputs: Path, name: str) -> None:
    from artifacts import digest, verify_archive

    files = package(inputs)
    files[name] = b"synthetic"
    manifest = json.loads(files["manifest.json"])
    manifest["files"][name] = {"bytes": len(files[name]), "sha256": digest(files[name])}
    files["manifest.json"] = json.dumps(manifest).encode()
    with pytest.raises(PackagingRefused, match="component"):
        verify_archive(archive(files), "a" * 40, {"fastapi": "0.143.0"})


@pytest.mark.parametrize(
    "mutation", ["link", "sparse", "duplicate", "owner", "mode", "truncated", "path"]
)
def test_malformed_archive_members_refuse_without_extraction(inputs: Path, mutation: str) -> None:
    from artifacts import verify_archive

    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as bundle:
        for ordinal, (name, content) in enumerate(package(inputs).items()):
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(content), 0o644
            if ordinal == 0:
                if mutation == "link":
                    entry.type, entry.linkname = tarfile.SYMTYPE, "../../outside"
                elif mutation == "sparse":
                    entry.type = tarfile.GNUTYPE_SPARSE
                elif mutation == "owner":
                    entry.uid = 1
                elif mutation == "mode":
                    entry.mode = 0o755
                elif mutation == "path":
                    entry.name = "../outside"
                if mutation == "duplicate":
                    bundle.addfile(entry, io.BytesIO(content))
            bundle.addfile(entry, io.BytesIO(content))
    value = output.getvalue()
    if mutation == "truncated":
        value = value[:600]
    with pytest.raises(PackagingRefused):
        verify_archive(value, "a" * 40, {"fastapi": "0.143.0"})
    assert not (inputs.parent / "outside").exists()


def test_cleanup_continues_after_failure_and_reports_remaining_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = OwnedBuilds("e" * 32)
    owner.containers = ["failed-container"]
    owner.images = ["owned-image"]
    calls: list[list[str]] = []
    existing = {"failed-container", "owned-image"}

    def inspect(kind: str, name: str) -> dict[str, Any] | None:
        return {"Config": {"Labels": {LABEL: owner.owner}}} if name in existing else None

    def run(arguments: list[str], timeout: float = 180) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments[-1] == "failed-container":
            raise PackagingRefused("package_command_failed")
        existing.remove(arguments[-1])
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(owner, "inspect", inspect)
    monkeypatch.setattr("run_acceptance.command", run)
    with pytest.raises(PackagingRefused, match="cleanup"):
        owner.close()
    assert [call[-1] for call in calls] == ["failed-container", "owned-image"]
    assert existing == {"failed-container"}


@pytest.mark.parametrize(
    "uv_version",
    [
        "uv 0.12.23",
        "uv 0.12.23 (x86_64-unknown-linux-gnu)",
        "uv 0.12.23 (123abc45 2026-10-01)",
    ],
)
def test_exact_uv_pin_allows_only_bounded_build_metadata(uv_version: str) -> None:
    from run_acceptance import require_tool_versions

    require_tool_versions({"uv": uv_version, "pnpm": "11.25.0", "node": "v24.19.0"})


@pytest.mark.parametrize(
    "name,value",
    [
        ("uv", "uv 0.12.230"),
        ("uv", "uv 0.12.24 (123abc45 2026-10-01)"),
        ("uv", "uv 0.12.23\nextra"),
        ("uv", "uv 0.12.23 (" + "x" * 129 + ")"),
        ("uv", "uv 0.12.23 ; command"),
        ("pnpm", "11.25.1"),
        ("node", "v24.19.1"),
    ],
)
def test_changed_or_ambiguous_build_tool_versions_refuse(name: str, value: str) -> None:
    from run_acceptance import require_tool_versions

    versions = {"uv": "uv 0.12.23", "pnpm": "11.25.0", "node": "v24.19.0", name: value}
    with pytest.raises(PackagingRefused, match="tool_version"):
        require_tool_versions(versions)


@pytest.mark.parametrize(
    "stderr,reason",
    [
        ("RuntimeError: metadata_runtime_closure_refused\n", "metadata_runtime_closure_refused"),
        (
            "RuntimeError: metadata_image_link_refused\n",
            "metadata_image_link_refused",
        ),
        ("RuntimeError: metadata_unknown_secret\n", "unclassified_probe_failure"),
        ("ValueError: SYNTHETIC_SECRET_MARKER\n", "unclassified_probe_failure"),
        ("private/path: SYNTHETIC_SECRET_MARKER\n", "unclassified_probe_failure"),
    ],
)
def test_smoke_failure_diagnostics_emit_only_fixed_source_owned_reasons(
    capsys: pytest.CaptureFixture[str], stderr: str, reason: str
) -> None:
    from run_acceptance import report_smoke_failure

    report_smoke_failure(1, stderr)
    output = capsys.readouterr()
    assert json.loads(output.out) == {"metadata_smoke_failure": {"returncode": 1, "reason": reason}}
    assert "SYNTHETIC_SECRET_MARKER" not in output.out and not output.err


@pytest.mark.parametrize(
    "name,target,allowed",
    [
        (".venv/bin/python", "/usr/local/bin/python3", True),
        (".venv/bin/python3", "python", True),
        (".venv/bin/python3.12", "python", True),
        (".venv/lib64", "lib", True),
        (".venv/bin/python", "/usr/bin/python3", False),
        (".venv/bin/foreign", "/usr/local/bin/python3", False),
        (".venv/bin/python", "../../secret", False),
    ],
)
def test_image_digest_accepts_only_fixed_base_interpreter_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, target: str, allowed: bool
) -> None:
    from probe import content_digest

    link = tmp_path / name
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    monkeypatch.setattr("probe.ROOT", tmp_path)
    if allowed:
        first = content_digest()
        assert len(first) == 64 and first == content_digest()
    else:
        with pytest.raises(RuntimeError, match="metadata_image_link_refused"):
            content_digest()

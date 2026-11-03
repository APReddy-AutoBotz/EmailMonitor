"""Installed authored-source artifact, without repository imports or credentials."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from service_artifacts import collect_service, git_blob_digest, verify_service_archive

from artifacts import NOTICES, PackagingRefused, archive, materialize

ROOT = Path(__file__).resolve().parents[3]


def test_service_artifact_receipt_and_installed_entrypoint(tmp_path: Path) -> None:
    # CLI/import smoke uses an authored minimal web fixture, never claims the
    # keyboard operator journey or depends on an untracked pre-existing build.
    inputs = tmp_path / "inputs"
    for name in ("services/backend/src", "services/backend/migrations", "fixtures", "contracts"):
        shutil.copytree(ROOT / name, inputs / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in (
        *NOTICES,
        "services/backend/pyproject.toml",
        "services/backend/uv.lock",
        "services/backend/alembic.ini",
    ):
        target = inputs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    web = inputs / "apps/web/dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text('<script src="/assets/index-12345678.js"></script>')
    (web / "assets/index-12345678.js").write_text("// authored packaging smoke only\n")
    inventory = {
        path.relative_to(inputs).as_posix(): git_blob_digest(path.read_bytes())
        for path in (inputs / "services/backend/src/emailmonitor").rglob("*.py")
    }
    files = collect_service(inputs, "a" * 40, {"python": "3.12.13"}, inventory)
    hidden = inputs / "services/backend/src/emailmonitor/build/hidden.py"
    hidden.parent.mkdir()
    hidden.write_text("# ignored source must not acquire HEAD attribution\n")
    with pytest.raises(PackagingRefused, match="service_source_inventory_refused"):
        collect_service(inputs, "a" * 40, {"python": "3.12.13"}, inventory)
    hidden.unlink()
    changed = inputs / next(iter(inventory))
    prior = changed.read_bytes()
    changed.write_bytes(prior + b"\n# dirty tracked source\n")
    with pytest.raises(PackagingRefused, match="service_source_inventory_refused"):
        collect_service(inputs, "a" * 40, {"python": "3.12.13"}, inventory)
    changed.write_bytes(prior)
    receipt = files["manifest.json"]
    assert verify_service_archive(archive(files), receipt) == files
    damaged = dict(files)
    damaged["services/backend/src/emailmonitor/runtime/worker.py"] += b"\n# changed\n"
    with pytest.raises(PackagingRefused):
        verify_service_archive(archive(damaged), receipt)
    destination = tmp_path / "installed"
    materialize(files, destination)
    code = """
import sys
sys.path.insert(0,sys.argv[1])
from emailmonitor.runtime.entrypoint import main
from emailmonitor.runtime.api_entrypoint import ReferenceAPI
from emailmonitor.extraction.fixture import article_bytes
assert article_bytes("article-a.html")
print('installed_import_closure')
sys.argv=['service','--help']
main()
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(destination / "services/backend/src")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        env={key: value for key, value in os.environ.items() if not key.startswith("EM_")},
    )
    assert result.returncode == 0, result.stderr
    assert "installed_import_closure" in result.stdout
    assert "publish-once" in result.stdout and "reconcile-once" in result.stdout
    assert not any(name.endswith((".key", ".pem", ".env")) for name in files)


def test_source_inventory_is_bound_to_git_tree_not_ignore_filtered_worktree(tmp_path: Path) -> None:
    from service_artifacts import tracked_service_sources

    def git(*arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(tmp_path), *arguments],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()

    git("init", "--quiet")
    (tmp_path / ".gitignore").write_text("build/\n")
    relative = "services/backend/src/emailmonitor/__init__.py"
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    source.write_bytes(b"# authored inventory fixture\n")
    git("add", ".")
    git(
        "-c",
        "user.name=Authored Fixture",
        "-c",
        "user.email=fixture@example.test",
        "commit",
        "--quiet",
        "-m",
        "Authored source inventory",
    )
    tree = git("rev-parse", "HEAD^{tree}")
    hidden = source.parent / "build/hidden.py"
    hidden.parent.mkdir()
    hidden.write_text("# ignored and not committed\n")
    assert git("ls-files", "--others", "--exclude-standard") == ""
    assert tracked_service_sources(tmp_path, tree) == {
        relative: git_blob_digest(source.read_bytes())
    }
    with pytest.raises(PackagingRefused, match="service_source_inventory_refused"):
        tracked_service_sources(tmp_path, "HEAD")

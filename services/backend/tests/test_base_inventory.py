"""Synthetic fixed-root inventory evidence; never reads the host base or invokes Docker."""

import ast
import copy
import hashlib
import inspect
import json
import os
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import pytest
from base_inventory import collect_base_inventory, validate_base_inventory


def write_base_fixture(root: Path) -> Path:
    """Write only authored fixed inputs; shared by the fake owned-probe tests."""
    values = {
        "usr/lib/os-release": (
            b'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\n'
            b'ID=debian\nVERSION_ID="12"\nVERSION_CODENAME=bookworm\n'
        ),
        "var/lib/dpkg/status": (
            b"Package: zlib1g\nStatus: install ok installed\nArchitecture: amd64\n"
            b"Version: 1:1.2.13.dfsg-1\nSource: zlib (1:1.2.13.dfsg-1)\n"
            b"Description: authored fixture\n continuation only\n\n"
            b"Package: base-files\nStatus: hold ok installed\nArchitecture: amd64\n"
            b"Version: 12.4+deb12u1\n\n"
            b"Package: removed-package\nStatus: deinstall ok config-files\nArchitecture: all\n"
            b"Version: 1.0\n\n"
        ),
        "usr/share/doc/zlib1g/copyright": b"AUTHORED COPYRIGHT SENTINEL, NEVER OUTPUT\n",
        "usr/local/include/python3.12/patchlevel.h": (
            b'#define PY_VERSION "3.12.13"\n#define PY_MAJOR_VERSION 3\n'
            b"#define PY_MINOR_VERSION 12\n#define PY_MICRO_VERSION 13\n"
        ),
        "usr/local/bin/python3.12": b"\x7fELF\x02\x01" + b"\0" * 12 + b"\x3e\x00" + b"fixture",
        "usr/local/lib/python3.12/LICENSE.txt": b"AUTHORED PYTHON NOTICE, NEVER OUTPUT\n",
        "usr/local/lib/python3.12/site-packages/pip-25.2.dist-info/METADATA": (
            b"Metadata-Version: 2.4\nName: pip\nVersion: 25.2\n"
            b"Classifier: first\nClassifier: second\n\nSynthetic distribution\n"
        ),
    }
    for name, content in values.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (root / "etc").mkdir(exist_ok=True)
    (root / "etc/os-release").symlink_to("../usr/lib/os-release")
    return root


def valid_base_inventory(root: Path) -> dict[str, object]:
    return collect_base_inventory(write_base_fixture(root))


@pytest.fixture
def base_root(tmp_path: Path) -> Path:
    return write_base_fixture(tmp_path)


def rehash(report: dict[str, Any]) -> None:
    body = {key: value for key, value in report.items() if key != "inventory_sha256"}
    report["inventory_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_observations_are_deterministic_bounded_and_do_not_output_notice_contents(
    base_root: Path,
) -> None:
    first = collect_base_inventory(base_root)
    for path in base_root.rglob("*"):
        if not path.is_symlink():
            os.utime(path, (12345678, 12345678))
    status = base_root / "var/lib/dpkg/status"
    status.write_text("\n\n".join(reversed(status.read_text()[:-2].split("\n\n"))) + "\n\n")
    second = collect_base_inventory(base_root)
    assert first == second == validate_base_inventory(first)
    output = json.dumps(first)
    assert len(output.encode()) < 48 * 1024
    assert "SENTINEL" not in output and "AUTHORED" not in output
    assert "removed-package" not in output
    packages = first["packages"]
    assert isinstance(packages, list)
    assert packages[0]["source"] is None
    assert packages[0]["copyright"]["status"] == "missing"
    assert packages[1]["source"] == {"name": "zlib", "version": "1:1.2.13.dfsg-1"}
    assert (
        packages[1]["copyright"]["sha256"]
        == hashlib.sha256((base_root / "usr/share/doc/zlib1g/copyright").read_bytes()).hexdigest()
    )


def test_base_inputs_change_digest_and_ignore_active_virtualenv(base_root: Path) -> None:
    before = collect_base_inventory(base_root)
    active = base_root / "opt/emailmonitor/.venv/lib/python3.12/site-packages/evil.dist-info"
    active.mkdir(parents=True)
    (active / "METADATA").write_text("this must not be read")
    assert collect_base_inventory(base_root) == before
    (base_root / "usr/share/doc/zlib1g/copyright").write_text("different authored notice\n")
    assert collect_base_inventory(base_root)["inventory_sha256"] != before["inventory_sha256"]


def test_safe_doc_aliases_and_explicit_source_without_version(base_root: Path) -> None:
    notice = base_root / "usr/share/doc/zlib1g/copyright"
    target = base_root / "usr/share/doc/zlib-source"
    target.mkdir()
    notice.rename(target / "copyright")
    notice.symlink_to("../zlib-source/copyright")
    status = base_root / "var/lib/dpkg/status"
    status.write_text(status.read_text().replace("Source: zlib (1:1.2.13.dfsg-1)", "Source: zlib"))
    report = collect_base_inventory(base_root)
    packages = report["packages"]
    assert isinstance(packages, list)
    assert packages[1]["source"] == {"name": "zlib", "version": None}
    assert packages[1]["copyright"]["resolved_path"] == "/usr/share/doc/zlib-source/copyright"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("Package: zlib1g", "Package: ../private"),
        ("Version: 1:1.2.13.dfsg-1", "Version: bad version"),
        ("Architecture: amd64", "Architecture: arm64"),
        ("Status: install ok installed", "Status: pretend installed"),
        ("Source: zlib (1:1.2.13.dfsg-1)", "Source: zlib (bad version)"),
        ("Source: zlib (1:1.2.13.dfsg-1)", "Source: zlib (bad-version)"),
        ("Package: zlib1g", "Package: zlib1g\npackage: duplicate"),
        ("Version: 1:1.2.13.dfsg-1", "Version: 1:1.2.13.dfsg-1\n continuation"),
    ],
)
def test_malformed_package_records_refuse(base_root: Path, old: str, new: str) -> None:
    path = base_root / "var/lib/dpkg/status"
    path.write_text(path.read_text().replace(old, new, 1))
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        collect_base_inventory(base_root)


@pytest.mark.parametrize("kind", ["missing", "truncated", "duplicate", "oversized", "empty"])
def test_missing_truncated_duplicate_or_oversized_database_refuses(
    base_root: Path, kind: str
) -> None:
    path = base_root / "var/lib/dpkg/status"
    if kind == "missing":
        path.unlink()
    elif kind == "truncated":
        path.write_text(path.read_text()[:-1])
    elif kind == "duplicate":
        path.write_text(path.read_text() * 2)
    elif kind == "oversized":
        path.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    else:
        path.write_text("")
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        collect_base_inventory(base_root)


@pytest.mark.parametrize(
    "target", ["/etc/passwd", "../../../../etc/passwd", "../absent/copyright", "copyright"]
)
def test_unsafe_dangling_or_looping_notice_links_refuse(base_root: Path, target: str) -> None:
    path = base_root / "usr/share/doc/zlib1g/copyright"
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        collect_base_inventory(base_root)


@pytest.mark.parametrize("kind", ["fifo", "directory", "oversized", "empty"])
def test_nonregular_or_unbounded_notice_refuses(base_root: Path, kind: str) -> None:
    path = base_root / "usr/share/doc/zlib1g/copyright"
    path.unlink()
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    elif kind == "oversized":
        path.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    else:
        path.write_text("")
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        collect_base_inventory(base_root)


@pytest.mark.parametrize(
    ("relative", "content"),
    [
        ("usr/lib/os-release", b"ID=alpine\nVERSION_ID=12\nVERSION_CODENAME=bookworm\n"),
        ("usr/lib/os-release", b"ID=debian\nID=debian\n"),
        ("usr/lib/os-release", b'ID="$(private)"\n'),
        ("usr/lib/os-release", b"ID=debian"),
        ("usr/local/include/python3.12/patchlevel.h", b'#define PY_VERSION "3.12.14"\n'),
        ("usr/local/bin/python3.12", b"not an ELF executable"),
        (
            "usr/local/lib/python3.12/site-packages/pip-25.2.dist-info/METADATA",
            b"Metadata-Version: 2.4\nName: pip\nVersion: 25.2\nName: evil\n\n",
        ),
        (
            "usr/local/lib/python3.12/site-packages/pip-25.2.dist-info/METADATA",
            b"Metadata-Version: 2.4\nName: pip\nVersion: 25.2",
        ),
    ],
)
def test_unsupported_or_malformed_fixed_identity_refuses(
    base_root: Path, relative: str, content: bytes
) -> None:
    (base_root / relative).write_bytes(content)
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        collect_base_inventory(base_root)


def test_missing_python_notice_is_explicit(base_root: Path) -> None:
    (base_root / "usr/local/lib/python3.12/LICENSE.txt").unlink()
    report = collect_base_inventory(base_root)
    python = report["upstream_python"]
    assert isinstance(python, dict)
    assert python["copyright"]["status"] == "missing"


def test_doc_directory_alias_preserves_requested_and_resolved_references(base_root: Path) -> None:
    original = base_root / "usr/share/doc/zlib1g"
    original.rename(base_root / "usr/share/doc/zlib-source")
    original.symlink_to("zlib-source", target_is_directory=True)
    report = collect_base_inventory(base_root)
    packages = report["packages"]
    assert isinstance(packages, list)
    notice = packages[1]["copyright"]
    assert notice["path"] == "/usr/share/doc/zlib1g/copyright"
    assert notice["resolved_path"] == "/usr/share/doc/zlib-source/copyright"


@pytest.mark.parametrize("kind", ["absolute", "directory_link", "file_link"])
def test_non_notice_inputs_refuse_unapproved_symlinks(base_root: Path, kind: str) -> None:
    if kind == "absolute":
        path = base_root / "etc/os-release"
        path.unlink()
        path.symlink_to("/private/os-release")
    elif kind == "directory_link":
        path = base_root / "var/lib/dpkg"
        path.rename(base_root / "var/lib/other")
        path.symlink_to("other", target_is_directory=True)
    else:
        path = base_root / "usr/local/include/python3.12/patchlevel.h"
        path.rename(path.with_name("other.h"))
        path.symlink_to("other.h")
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        collect_base_inventory(base_root)


def test_total_notice_bytes_are_bounded(base_root: Path) -> None:
    status = []
    for index in range(9):
        name = f"pkg{index:03d}"
        path = base_root / f"usr/share/doc/{name}/copyright"
        path.parent.mkdir()
        path.write_bytes(b"x" * (2 * 1024 * 1024))
        status.append(
            f"Package: {name}\nStatus: install ok installed\nArchitecture: amd64\nVersion: 1\n\n"
        )
    (base_root / "var/lib/dpkg/status").write_text("".join(status))
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        collect_base_inventory(base_root)


def test_fixed_inputs_never_walk_or_execute_bundled_code(
    base_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = base_root / "usr/local/lib/python3.12/site-packages"
    (site / "evil.pth").write_text("import os; raise RuntimeError('must never execute')\n")
    (site / "pip").mkdir()
    (site / "pip/__init__.py").write_text("raise RuntimeError('must never import')\n")
    paths: list[Path] = []
    original = os.scandir

    def scan(path: Path) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
        paths.append(path)
        return original(path)

    def no_walk(*args: object, **kwargs: object) -> None:
        raise AssertionError("unbounded walk")

    monkeypatch.setattr(os, "scandir", scan)
    monkeypatch.setattr(Path, "rglob", no_walk)
    collect_base_inventory(base_root)
    assert paths == [site]
    assert inspect.signature(collect_base_inventory).parameters["root"].default == Path("/")


def test_changed_file_identity_refuses(base_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = os.fstat
    calls = 0

    def changed(fd: int) -> os.stat_result:
        nonlocal calls
        calls += 1
        actual = original(fd)
        if calls == 2:
            items = list(actual)
            items[6] += 1
            return os.stat_result(items)
        return actual

    monkeypatch.setattr(os, "fstat", changed)
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        collect_base_inventory(base_root)


@pytest.mark.parametrize("kind", ["paragraphs", "fields", "line", "paragraph"])
def test_status_parser_internal_bounds(base_root: Path, kind: str) -> None:
    path = base_root / "var/lib/dpkg/status"
    if kind == "paragraphs":
        path.write_text("Package: ab\n\n" * 513)
    else:
        value = path.read_text()
        if kind == "fields":
            extra = "".join(f"X-Field-{index}: fixture\n" for index in range(129))
        elif kind == "line":
            extra = "Description: " + "x" * 16385 + "\n"
        else:
            extra = "Description: first\n" + (" x" + "x" * 1024 + "\n") * 256
        path.write_text(value.replace("Package: zlib1g\n", "Package: zlib1g\n" + extra))
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        collect_base_inventory(base_root)


def test_system_metadata_symlinks_and_distribution_duplicates_refuse(base_root: Path) -> None:
    site = base_root / "usr/local/lib/python3.12/site-packages"
    original = site / "pip-25.2.dist-info"
    duplicate = site / "pip-25.3.dist-info"
    duplicate.mkdir()
    (duplicate / "METADATA").write_bytes((original / "METADATA").read_bytes())
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        collect_base_inventory(base_root)
    (duplicate / "METADATA").unlink()
    duplicate.rmdir()
    original.rename(site / "outside")
    original.symlink_to("outside", target_is_directory=True)
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        collect_base_inventory(base_root)


@pytest.mark.parametrize("kind", ["entries", "distributions", "packages", "serialized"])
def test_count_and_output_caps_refuse_without_truncation(base_root: Path, kind: str) -> None:
    if kind == "entries":
        site = base_root / "usr/local/lib/python3.12/site-packages"
        for index in range(512):
            (site / f"entry-{index}").touch()
    elif kind == "distributions":
        site = base_root / "usr/local/lib/python3.12/site-packages"
        for index in range(32):
            path = site / f"pkg{index}-1.dist-info/METADATA"
            path.parent.mkdir()
            path.write_text(f"Metadata-Version: 2.4\nName: pkg{index}\nVersion: 1\n\n")
    else:
        count = 257 if kind == "packages" else 200
        version = "1" if kind == "packages" else "1" + "x" * 127
        (base_root / "var/lib/dpkg/status").write_text(
            "".join(
                f"Package: pkg{index:03d}\nStatus: install ok installed\n"
                f"Architecture: amd64\nVersion: {version}\n\n"
                for index in range(count)
            )
        )
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        collect_base_inventory(base_root)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_field",
        "digest",
        "claim",
        "nested_unknown",
        "package_duplicate",
        "package_order",
        "source",
        "notice_missing_hash",
        "notice_path",
        "notice_bool_size",
        "metadata_escape",
        "python_version",
    ],
)
def test_host_rejects_forged_reports_even_after_rehash(base_root: Path, mutation: str) -> None:
    report: dict[str, Any] = copy.deepcopy(collect_base_inventory(base_root))
    if mutation == "unknown_field":
        report["image_id"] = "sha256:" + "a" * 64
    elif mutation == "digest":
        report["inventory_sha256"] = "0" * 64
    elif mutation == "claim":
        report["limitations"] = []
    elif mutation == "nested_unknown":
        report["packages"][0]["license"] = "inferred"
    elif mutation == "package_duplicate":
        report["packages"].append(report["packages"][0])
    elif mutation == "package_order":
        report["packages"].reverse()
    elif mutation == "source":
        report["packages"][0]["source"] = {"name": "x", "version": "1"}
    elif mutation == "notice_missing_hash":
        report["packages"][1]["copyright"]["sha256"] = None
    elif mutation == "notice_path":
        report["packages"][1]["copyright"]["resolved_path"] = "/usr/share/doc/../private/copyright"
    elif mutation == "notice_bool_size":
        report["packages"][1]["copyright"]["bytes"] = True
    elif mutation == "metadata_escape":
        report["upstream_python"]["bundled_distributions"][0]["metadata_path"] = "/private/METADATA"
    else:
        report["upstream_python"]["version"] = "3.12.14"
    if mutation != "digest":
        rehash(report)
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        validate_base_inventory(report)


@pytest.mark.parametrize("kind", ["total_bytes", "conflicting_alias"])
def test_host_enforces_aggregate_notice_consistency(base_root: Path, kind: str) -> None:
    report: dict[str, Any] = copy.deepcopy(collect_base_inventory(base_root))
    observed = report["packages"][1]
    if kind == "total_bytes":
        report["packages"] = []
        for index in range(9):
            package = copy.deepcopy(observed)
            package["name"] = f"pkg{index:03d}"
            package["copyright"]["path"] = f"/usr/share/doc/pkg{index:03d}/copyright"
            package["copyright"]["resolved_path"] = package["copyright"]["path"]
            package["copyright"]["bytes"] = 2 * 1024 * 1024
            report["packages"].append(package)
    else:
        notice = copy.deepcopy(observed["copyright"])
        notice["path"] = "/usr/share/doc/base-files/copyright"
        notice["sha256"] = "0" * 64
        report["packages"][0]["copyright"] = notice
    rehash(report)
    with pytest.raises(RuntimeError, match="^base_inventory_refused$"):
        validate_base_inventory(report)


def test_shared_prefix_has_only_imports_definitions_and_no_collection() -> None:
    path = Path(__file__).resolve().parents[3] / "scripts/packaging/base_inventory.py"
    source = path.read_text()
    assert len(source.encode()) <= 32 * 1024
    module = ast.parse(source)
    assert all(
        isinstance(node, ast.ImportFrom | ast.Import | ast.FunctionDef)
        or (index == 0 and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
        for index, node in enumerate(module.body)
    )
    assert not any(
        isinstance(node, ast.Import)
        and any(
            name.name in {"subprocess", "socket", "importlib", "emailmonitor"}
            for name in node.names
        )
        for node in ast.walk(module)
    )
    namespace: dict[str, Any] = {"__name__": "__main__", "ROOT": "sentinel"}
    exec(compile(source, str(path), "exec"), namespace)
    assert namespace["ROOT"] == "sentinel"
    assert callable(namespace["collect_base_inventory"])


def test_error_contains_no_private_file_content_or_fixture_root(base_root: Path) -> None:
    path = base_root / "var/lib/dpkg/status"
    path.write_bytes(b"PRIVATE SENTINEL\xff")
    with pytest.raises(RuntimeError) as error:
        collect_base_inventory(base_root)
    assert str(error.value) == "base_inventory_refused"
    assert error.value.__suppress_context__ is True

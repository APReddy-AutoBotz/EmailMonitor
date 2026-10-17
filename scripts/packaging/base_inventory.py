"""Bounded, read-only observations for the existing immutable Debian/Python images.

The trusted host prefixes these definitions to its fixed disposable probes. Nothing
is collected on import. A fixture root is an explicit test-code input, never a
command-line/environment/customer option. The caller has already verified the
read-only, network-none image profile; no concurrent filesystem writer is assumed.
"""

from pathlib import Path as _BaseInventoryPath


def _base_inventory_fixed() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "scope": "observed-debian-base-system",
        "distro": {"ID": "debian", "VERSION_ID": "12", "VERSION_CODENAME": "bookworm"},
        "limitations": [
            "fixed-path observations; not a complete SBOM",
            "source metadata unavailable when the Debian Source field is absent",
            "notice references and hashes only; no inferred or reviewed licenses",
            "upstream Python shared libraries and other untracked files unresolved",
            "bundled distributions cover direct system dist-info metadata only",
            "bundled-distribution legal notices are unresolved",
            "active application virtualenv, embedded wheels and vendored components excluded",
            "no vulnerability assessment or signed provenance",
            "immutable base identity and source tree are bound by the host receipt",
        ],
    }


def validate_base_inventory(value: object) -> dict[str, object]:
    """Validate the entire guest schema and independently recompute its digest."""
    import hashlib
    import json
    import re
    from typing import cast

    def refuse() -> None:
        raise RuntimeError("base_inventory_refused")

    def record(item: object, keys: set[str]) -> dict[str, object]:
        if type(item) is not dict or set(item) != keys:
            refuse()
        return cast(dict[str, object], item)

    def string(item: object, pattern: str, maximum: int = 128) -> str:
        if type(item) is not str or len(item) > maximum or re.fullmatch(pattern, item) is None:
            refuse()
        return cast(str, item)

    def digest(item: object) -> None:
        string(item, r"[0-9a-f]{64}", 64)

    observed_notices: dict[str, tuple[int, object]] = {}

    def notice(item: object, expected: str) -> None:
        obj = record(item, {"path", "resolved_path", "status", "bytes", "sha256"})
        if obj["path"] != expected:
            refuse()
        if obj["status"] == "missing":
            if any(obj[key] is not None for key in ("resolved_path", "bytes", "sha256")):
                refuse()
        elif obj["status"] == "present":
            resolved = string(obj["resolved_path"], r"/[A-Za-z0-9_+./-]+", 256)
            if any(part in {"", ".", ".."} for part in resolved.split("/")[1:]):
                refuse()
            if expected.startswith("/usr/share/doc/"):
                if not resolved.startswith("/usr/share/doc/") or not resolved.endswith(
                    "/copyright"
                ):
                    refuse()
            elif resolved != expected:
                refuse()
            if type(obj["bytes"]) is not int or not 0 < obj["bytes"] <= 2097152:
                refuse()
            digest(obj["sha256"])
            observation = (cast(int, obj["bytes"]), obj["sha256"])
            if resolved in observed_notices and observed_notices[resolved] != observation:
                refuse()
            observed_notices[resolved] = observation
            if sum(size for size, _ in observed_notices.values()) > 16 * 1024 * 1024:
                refuse()
        else:
            refuse()

    fixed = _base_inventory_fixed()
    report = record(value, set(fixed) | {"packages", "upstream_python", "inventory_sha256"})
    for key, expected in fixed.items():
        if report[key] != expected:
            refuse()
    # Exact nested types, including list/dict and no bool-as-int substitutions.
    record(report["distro"], {"ID", "VERSION_ID", "VERSION_CODENAME"})
    if type(report["limitations"]) is not list:
        refuse()
    packages = report["packages"]
    if type(packages) is not list or not 1 <= len(packages) <= 256:
        refuse()
    package_keys: list[tuple[str, str]] = []
    for item in cast(list[object], packages):
        obj = record(item, {"name", "version", "architecture", "source", "copyright"})
        name = string(obj["name"], r"[a-z0-9][a-z0-9+.-]+")
        string(obj["version"], r"[0-9][A-Za-z0-9.+:~\-]*")
        arch = string(obj["architecture"], r"amd64|all", 5)
        package_keys.append((name, arch))
        if obj["source"] is not None:
            source = record(obj["source"], {"name", "version"})
            string(source["name"], r"[a-z0-9][a-z0-9+.-]+")
            if source["version"] is not None:
                string(source["version"], r"[0-9][A-Za-z0-9.+:~\-]*")
        notice(obj["copyright"], "/usr/share/doc/" + name + "/copyright")
    if package_keys != sorted(set(package_keys)):
        refuse()
    python = record(
        report["upstream_python"],
        {"version", "header_sha256", "executable_sha256", "copyright", "bundled_distributions"},
    )
    if python["version"] != "3.12.13":
        refuse()
    digest(python["header_sha256"])
    digest(python["executable_sha256"])
    notice(python["copyright"], "/usr/local/lib/python3.12/LICENSE.txt")
    distributions = python["bundled_distributions"]
    if type(distributions) is not list or len(distributions) > 32:
        refuse()
    distribution_names: list[str] = []
    for item in cast(list[object], distributions):
        obj = record(item, {"name", "version", "metadata_path", "metadata_sha256"})
        name = string(obj["name"], r"[a-z0-9]+(?:-[a-z0-9]+)*")
        version = string(obj["version"], r"[A-Za-z0-9][A-Za-z0-9.!+_-]*")
        path = string(obj["metadata_path"], r"/[A-Za-z0-9_.+!/-]+", 384)
        if path != (
            "/usr/local/lib/python3.12/site-packages/"
            + name.replace("-", "_")
            + "-"
            + version
            + ".dist-info/METADATA"
        ):
            refuse()
        digest(obj["metadata_sha256"])
        distribution_names.append(name)
    if distribution_names != sorted(set(distribution_names)):
        refuse()
    digest(report["inventory_sha256"])
    # Use the probe's default JSON spacing here; leave 16 KiB for its other proof.
    if len(json.dumps(report, sort_keys=True).encode("utf-8")) > 48 * 1024:
        refuse()
    body = {key: item for key, item in report.items() if key != "inventory_sha256"}
    actual = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if actual != report["inventory_sha256"]:
        refuse()
    return report


def collect_base_inventory(root: _BaseInventoryPath = _BaseInventoryPath("/")) -> dict[str, object]:
    """Collect fixed system inputs; errors contain no file contents or host paths."""
    try:
        return _base_inventory_collect(root)
    except Exception:
        raise RuntimeError("base_inventory_refused") from None


def _base_inventory_collect(root: _BaseInventoryPath) -> dict[str, object]:
    import hashlib
    import json
    import os
    import re
    import stat

    if not root.is_absolute() or not stat.S_ISDIR(root.lstat().st_mode):
        raise ValueError

    def safe_path(relative: str, *, docs: bool = False) -> _BaseInventoryPath:
        parts = relative.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError
        index = 0
        links = 0
        while index < len(parts):
            path = root.joinpath(*parts[: index + 1])
            try:
                mode = path.lstat().st_mode
            except FileNotFoundError:
                if links:
                    raise ValueError from None
                raise
            if stat.S_ISLNK(mode):
                links += 1
                if not docs or index < 3 or links > 8:
                    raise ValueError
                target = os.readlink(path)
                if not re.fullmatch(r"[A-Za-z0-9_+./-]{1,256}", target) or target.startswith("/"):
                    raise ValueError
                resolved = parts[:index]
                for part in target.split("/"):
                    if part in {"", "."}:
                        raise ValueError
                    if part == "..":
                        if len(resolved) <= 3:
                            raise ValueError
                        resolved.pop()
                    else:
                        resolved.append(part)
                if resolved[:3] != ["usr", "share", "doc"]:
                    raise ValueError
                parts = resolved + parts[index + 1 :]
                index = 0
                continue
            if index < len(parts) - 1 and not stat.S_ISDIR(mode):
                raise ValueError
            index += 1
        return root.joinpath(*parts)

    def read(relative: str, limit: int, *, docs: bool = False) -> tuple[bytes, str]:
        path = safe_path(relative, docs=docs)
        # O_NONBLOCK avoids a FIFO open even if a changed file evades lstat.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
                raise ValueError
            content = source.read(limit + 1)
            after = os.fstat(source.fileno())
        if (
            len(content) != before.st_size
            or len(content) > limit
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_mode)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_mode)
        ):
            raise ValueError
        return content, "/" + path.relative_to(root).as_posix()

    notice_bytes = 0
    notice_cache: dict[str, tuple[bytes, str]] = {}

    def notice(relative: str, *, docs: bool = False) -> dict[str, object]:
        nonlocal notice_bytes
        result: dict[str, object] = {
            "path": "/" + relative,
            "status": "missing",
            "resolved_path": None,
            "bytes": None,
            "sha256": None,
        }
        try:
            resolved = safe_path(relative, docs=docs).relative_to(root).as_posix()
        except FileNotFoundError:
            return result
        if resolved not in notice_cache:
            content, actual = read(resolved, 2 * 1024 * 1024)
            notice_bytes += len(content)
            if notice_bytes > 16 * 1024 * 1024:
                raise ValueError
            notice_cache[resolved] = content, actual
        content, actual = notice_cache[resolved]
        return {
            "path": "/" + relative,
            "status": "present",
            "resolved_path": actual,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    def text(content: bytes) -> str:
        value = content.decode("utf-8")
        if any(ord(char) < 32 and char not in "\n\t" for char in value) or "\x7f" in value:
            raise ValueError
        return value

    release_path = "etc/os-release"
    if (root / release_path).is_symlink():
        if os.readlink(root / release_path) not in {"../usr/lib/os-release", "/usr/lib/os-release"}:
            raise ValueError
        release_path = "usr/lib/os-release"
    release = text(read(release_path, 16 * 1024)[0])
    if not release.endswith("\n"):
        raise ValueError
    distro: dict[str, str] = {}
    for line in release.splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.*)", line)
        if match is None or match[1] in distro:
            raise ValueError
        value = match[2]
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError
            value = value[1:-1]
        if any(char in value for char in "\\$`\"'"):
            raise ValueError
        distro[match[1]] = value
    report = _base_inventory_fixed()
    if {key: distro.get(key) for key in ("ID", "VERSION_ID", "VERSION_CODENAME")} != report[
        "distro"
    ]:
        raise ValueError

    status = text(read("var/lib/dpkg/status", 4 * 1024 * 1024)[0])
    if not status.endswith("\n\n"):
        raise ValueError
    paragraphs = status[:-2].split("\n\n")
    if not 1 <= len(paragraphs) <= 512:
        raise ValueError
    packages: list[dict[str, object]] = []
    identities: set[tuple[str, str]] = set()
    for paragraph in paragraphs:
        if len(paragraph.encode("utf-8")) > 256 * 1024:
            raise ValueError
        fields: dict[str, str] = {}
        previous = ""
        for line in paragraph.split("\n"):
            if len(line) > 16384:
                raise ValueError
            if line.startswith((" ", "\t")):
                if not previous:
                    raise ValueError
                if previous in {"package", "architecture", "version", "source", "status"}:
                    # Identity fields are single-line. Never concatenate large descriptions.
                    raise ValueError
                continue
            match = re.fullmatch(r"([A-Za-z][A-Za-z0-9-]*):[ \t]*(.*)", line)
            if (
                match is None
                or len(match[1]) > 128
                or match[1].lower() in fields
                or len(fields) >= 128
            ):
                raise ValueError
            previous = match[1].lower()
            fields[previous] = match[2]
        state = fields.get("status", "")
        if not re.fullmatch(
            r"(?:unknown|install|hold|deinstall|purge) (?:ok|reinstreq) "
            r"(?:not-installed|config-files|half-installed|unpacked|half-configured|"
            r"triggers-awaited|triggers-pending|installed)",
            state,
        ):
            raise ValueError
        name, arch = fields.get("package", ""), fields.get("architecture", "")
        if (
            re.fullmatch(r"[a-z0-9][a-z0-9+.-]{1,127}", name) is None
            or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", arch) is None
            or (name, arch) in identities
        ):
            raise ValueError
        identities.add((name, arch))
        if state.split()[-1] != "installed":
            continue
        source: dict[str, object] | None = None
        if "source" in fields:
            match = re.fullmatch(
                r"([a-z0-9][a-z0-9+.-]{1,127})(?: \(([^() ]+)\))?", fields["source"]
            )
            if match is None:
                raise ValueError
            source = {"name": match[1], "version": match[2]}
        packages.append(
            {
                "name": name,
                "version": fields.get("version", ""),
                "architecture": arch,
                "source": source,
                "copyright": notice("usr/share/doc/" + name + "/copyright", docs=True),
            }
        )
        if len(packages) > 256:
            raise ValueError
    report["packages"] = sorted(
        packages, key=lambda item: (str(item["name"]), str(item["architecture"]))
    )

    header = read("usr/local/include/python3.12/patchlevel.h", 64 * 1024)[0]
    macros: dict[str, str] = {}
    for line in text(header).splitlines():
        match = re.fullmatch(
            r"\s*#\s*define\s+(PY_VERSION|PY_MAJOR_VERSION|PY_MINOR_VERSION|PY_MICRO_VERSION)\s+(.+)",
            line,
        )
        if match:
            if match[1] in macros:
                raise ValueError
            macros[match[1]] = match[2].strip()
    if macros != {
        "PY_VERSION": '"3.12.13"',
        "PY_MAJOR_VERSION": "3",
        "PY_MINOR_VERSION": "12",
        "PY_MICRO_VERSION": "13",
    }:
        raise ValueError
    executable = read("usr/local/bin/python3.12", 16 * 1024 * 1024)[0]
    if (
        len(executable) < 20
        or executable[:6] != b"\x7fELF\x02\x01"
        or executable[18:20] != b"\x3e\x00"
    ):
        raise ValueError
    site = "usr/local/lib/python3.12/site-packages"
    site_path = safe_path(site)
    if not stat.S_ISDIR(site_path.lstat().st_mode):
        raise ValueError
    names: list[str] = []
    with os.scandir(site_path) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > 512:
                raise ValueError
    distributions: list[dict[str, object]] = []
    for name in sorted(names):
        if not name.endswith(".dist-info"):
            continue
        if len(distributions) >= 32 or not re.fullmatch(
            r"[A-Za-z0-9_.+!-]{1,256}\.dist-info", name
        ):
            raise ValueError
        metadata, path = read(site + "/" + name + "/METADATA", 256 * 1024)
        metadata_text = metadata.decode("utf-8").replace("\r\n", "\n")
        if "\n\n" not in metadata_text:
            raise ValueError
        headers: dict[str, str] = {}
        previous = ""
        for line in text(metadata_text.split("\n\n", 1)[0].encode()).splitlines():
            if line.startswith((" ", "\t")):
                if not previous or previous in {"name", "version", "metadata-version"}:
                    raise ValueError
                continue
            match = re.fullmatch(r"([A-Za-z][A-Za-z0-9-]*):[ \t]*(.*)", line)
            if match is None:
                raise ValueError
            previous = match[1].lower()
            if previous in {"name", "version", "metadata-version"} and previous in headers:
                raise ValueError
            headers[previous] = match[2]
        if not re.fullmatch(r"[12]\.[0-9]", headers.get("metadata-version", "")):
            raise ValueError
        distribution_name = re.sub(r"[-_.]+", "-", headers.get("name", "")).lower()
        distributions.append(
            {
                "name": distribution_name,
                "version": headers.get("version", ""),
                "metadata_path": path,
                "metadata_sha256": hashlib.sha256(metadata).hexdigest(),
            }
        )
    distributions.sort(key=lambda item: str(item["name"]))
    report["upstream_python"] = {
        "version": "3.12.13",
        "header_sha256": hashlib.sha256(header).hexdigest(),
        "executable_sha256": hashlib.sha256(executable).hexdigest(),
        "copyright": notice("usr/local/lib/python3.12/LICENSE.txt"),
        "bundled_distributions": distributions,
    }
    report["inventory_sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return validate_base_inventory(report)

"""Offline inventory/lock parity gate; never fetches registry metadata."""

import hashlib
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_LICENSES = {
    "MIT",
    "MIT-0",
    "Apache-2.0 OR BSD-3-Clause",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "BSD-3-Clause AND Unicode-3.0",
    "ISC",
    "0BSD",
    "BlueOak-1.0.0",
    "CC0-1.0",
    "CC-BY-4.0",
    "PSF-2.0",
    "MPL-2.0",
    "Apache-2.0 OR BSD-2-Clause",
    "(MIT OR CC0-1.0)",
    "(MIT AND Zlib)",
    "MIT AND Zlib",
    "MIT AND PSF-2.0",
    "Python-2.0",
    "Unlicense",
}


def main() -> None:
    report = json.loads((ROOT / "reports/dependency-inventory.json").read_text())
    python_lock = ROOT / "services/backend/uv.lock"
    node_lock = ROOT / "apps/web/pnpm-lock.yaml"
    python_packages = {
        (p["name"], p["version"])
        for p in tomllib.loads(python_lock.read_text())["package"]
        if p["name"] != "emailmonitor-backend"
    }
    package_section = node_lock.read_text().split("packages:\n", 1)[1].split("\nsnapshots:", 1)[0]
    node_packages = {
        tuple(match.group(1).strip("'").rsplit("@", 1))
        for match in re.finditer(r"^  (\S+):$", package_section, re.M)
    }
    for ecosystem, packages in (("python", python_packages), ("javascript", node_packages)):
        entries = report[ecosystem]
        actual = {(p["name"], p["version"]) for p in entries}
        if actual != packages or len(entries) != len(actual):
            raise ValueError(f"Inventory does not match {ecosystem} lock")
        for package in entries:
            if package["license"] not in ALLOWED_LICENSES:
                raise ValueError(f"Unreviewed license: {package['name']}")
            if any(s in package["name"].lower() for s in ("pymupdf", "mupdf")):
                raise ValueError("Parser license gate requires separate review")
    for path in (python_lock, node_lock):
        key = str(path.relative_to(ROOT))
        if report["lock_sha256"][key] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError(f"Lock changed without inventory review: {key}")
    runtime = json.loads((ROOT / "reports/runtime-inventory.json").read_text())
    for dependency in ("postgresql", "rabbitmq"):
        image = runtime[dependency]["ci_image"]
        if image not in (ROOT / ".github/workflows/application.yml").read_text():
            raise ValueError("CI image differs from reviewed immutable runtime inventory")
    parser_image = runtime["python_parser"]["ci_image"]
    parser_dockerfile = (ROOT / "scripts/isolation/Dockerfile.parser").read_text()
    if "FROM " + parser_image + "\n" not in parser_dockerfile:
        raise ValueError("Parser image differs from reviewed immutable runtime inventory")
    browser_image = runtime["playwright_browser"]["image"]
    if (
        "FROM --platform=linux/amd64 " + browser_image + "\n"
        not in (ROOT / "scripts/isolation/Dockerfile.browser").read_text()
    ):
        raise ValueError("Browser image differs from reviewed immutable runtime inventory")
    for name, key in (
        ("seccomp-default.json", "source_sha256"),
        ("seccomp-browser.json", "derived_sha256"),
    ):
        if (
            hashlib.sha256((ROOT / "scripts/isolation" / name).read_bytes()).hexdigest()
            != runtime["browser_seccomp"][key]
        ):
            raise ValueError("Browser profile differs from reviewed inventory")
    packaging_image = runtime["metadata_packaging"]["base_image"]
    if (
        packaging_image != parser_image
        or (ROOT / "scripts/packaging/Metadata.Dockerfile")
        .read_text()
        .count("FROM --platform=linux/amd64 " + packaging_image)
        != 2
    ):
        raise ValueError("Metadata prerequisite image differs from reviewed immutable base")
    print(
        f"PASS: license inventory covers {len(python_packages)} Python and "
        f"{len(node_packages)} JavaScript locked packages"
    )


if __name__ == "__main__":
    main()

"""Offline inventory/lock parity gate; never fetches registry metadata."""

import hashlib
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_LICENSES = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
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
    print(
        f"PASS: license inventory covers {len(python_packages)} Python and "
        f"{len(node_packages)} JavaScript locked packages"
    )


if __name__ == "__main__":
    main()

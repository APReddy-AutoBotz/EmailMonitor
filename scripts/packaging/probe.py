"""Fixed network-none in-process metadata image probe; never starts a listener."""

import asyncio
import hashlib
import importlib.metadata
import json
import os
import re
import socket
import subprocess
import sys
from collections.abc import MutableMapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from base_inventory import collect_base_inventory

ROOT = Path("/opt/emailmonitor")


def normalized(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


async def response(path: str, method: str = "GET") -> tuple[int, object]:
    from emailmonitor.api import app

    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        if len(messages) > 4:
            raise RuntimeError("metadata_probe_response_refused")
        messages.append(dict(message))

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"x-organization-id", b"synthetic-forged-tenant")],
            "server": ("metadata.invalid", 443),
            "client": ("127.0.0.1", 0),
        },
        receive,
        send,
    )
    start = [m for m in messages if m["type"] == "http.response.start"]
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    if len(start) != 1 or len(body) > 65536:
        raise RuntimeError("metadata_probe_response_refused")
    return int(start[0]["status"]), json.loads(body)


def content_digest() -> str:
    records: dict[str, object] = {}
    total = 0
    for path in sorted(ROOT.rglob("*")):
        name = path.relative_to(ROOT).as_posix()
        if len(records) >= 20000:
            raise RuntimeError("metadata_image_cap_refused")
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
                raise RuntimeError("metadata_image_link_refused")
            records[name] = {"link": target}
        elif path.is_file():
            total += path.stat().st_size
            if total > 512 * 1024 * 1024 or any(
                part in {"__pycache__", ".cache"} for part in path.parts
            ):
                raise RuntimeError("metadata_image_cap_refused")
            value = hashlib.sha256()
            with path.open("rb") as file:
                for block in iter(lambda: file.read(65536), b""):
                    value.update(block)
            records[name] = {"bytes": path.stat().st_size, "sha256": value.hexdigest()}
    return hashlib.sha256(
        json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def refusals() -> int:
    code = "try:\n from emailmonitor.api import app\nexcept ValueError:\n raise SystemExit(42)\n"
    base = {key: value for key, value in os.environ.items() if not key.startswith("EMAILMONITOR_")}
    baseline = subprocess.run(
        [sys.executable, "-c", code], env=base, capture_output=True, timeout=5, check=False
    )
    if baseline.returncode != 0:
        raise RuntimeError("metadata_baseline_import_refused")
    modes = (
        "FIXTURE_MODE",
        "IDENTITY_STUB",
        "LIVE_SOURCES_ENABLED",
        "OUTBOUND_EMAIL_ENABLED",
        "EXTERNAL_AI_ENABLED",
        "WIDER_WEB_ENABLED",
        "OCR_ENABLED",
        "ALLOW_PRIVATE_URLS",
    )
    for mode in modes:
        env = {**base, "EMAILMONITOR_ENVIRONMENT": "production", "EMAILMONITOR_" + mode: "true"}
        failed = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, timeout=5, check=False
        )
        if failed.returncode != 42:
            raise RuntimeError("metadata_production_refusal_missing")
    return len(modes)


async def main() -> None:
    if os.getuid() != 65532 or os.getgid() != 65532 or sys.version_info[:3] != (3, 12, 13):
        raise RuntimeError("metadata_runtime_identity_refused")
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
        raise RuntimeError("metadata_kernel_restrictions_refused")
    network_errno = []
    for family, target in (
        (socket.AF_INET, ("192.0.2.1", 443)),
        (socket.AF_INET6, ("2001:db8::1", 443)),
    ):
        with socket.socket(family, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.2)
            network_errno.append(connection.connect_ex(target))
    if network_errno != [101, 101]:
        raise RuntimeError("metadata_runtime_network_refused")
    if [name for _, name in socket.if_nameindex()] != ["lo"]:
        raise RuntimeError("metadata_runtime_network_refused")
    if await response("/healthz") != (200, {"status": "ok"}):
        raise RuntimeError("metadata_health_refused")
    expected = {
        "schema_version": "1.0",
        "implementation_stage": "scaffold",
        "extraction_implemented": False,
        "live_sources_enabled": False,
        "outbound_email_enabled": False,
        "external_ai_enabled": False,
        "tenant_data_api_available": False,
    }
    if await response("/api/v1/capabilities") != (200, expected):
        raise RuntimeError("metadata_capabilities_refused")
    status, spec = await response("/openapi.json")
    if (
        status != 200
        or not isinstance(spec, dict)
        or set(spec["paths"]) != {"/healthz", "/api/v1/capabilities"}
    ):
        raise RuntimeError("metadata_paths_refused")
    if (await response("/api/v1/jobs", "POST"))[0] != 404:
        raise RuntimeError("metadata_forged_scope_refused")
    if {
        name for name in sys.modules if name == "emailmonitor" or name.startswith("emailmonitor.")
    } != {"emailmonitor", "emailmonitor.api", "emailmonitor.config"}:
        raise RuntimeError("metadata_fixture_import_refused")
    distributions = {}
    for item in importlib.metadata.distributions():
        name = normalized(item.metadata["Name"])
        if name in distributions:
            raise RuntimeError("metadata_distribution_duplicate")
        distributions[name] = item.version
    manifest = json.loads((ROOT / "manifest.json").read_bytes())
    if distributions != manifest["runtime_distributions"]:
        raise RuntimeError("metadata_runtime_closure_refused")
    for name in ("api.py", "config.py", "__init__.py"):
        expected_file = manifest["files"]["metadata-api/src/emailmonitor/" + name]
        actual = (ROOT / "src/emailmonitor" / name).read_bytes()
        if (
            len(actual) != expected_file["bytes"]
            or hashlib.sha256(actual).hexdigest() != expected_file["sha256"]
        ):
            raise RuntimeError("metadata_source_integrity_refused")
    refused = refusals()
    print(
        json.dumps(
            {
                "scope": "metadata-only-offline-prerequisite",
                "working_extraction_service": False,
                "production_ready": False,
                "metadata_asgi": True,
                "forged_tenant_404": True,
                "fixture_code_absent": True,
                "production_refusals": refused,
                "interfaces": ["lo"],
                "runtime_distributions": distributions,
                "kernel_restrictions": True,
                "network_errno": network_errno,
                "image_content_sha256": content_digest(),
                "base_inventory": collect_base_inventory(),
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())

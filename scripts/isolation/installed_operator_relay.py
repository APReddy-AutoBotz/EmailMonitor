"""Test-only, exact-origin TLS relay inside the existing network-none UI RPC.

This is not an application proxy. The host accepts only two caller-created
loopback origins, pinned ephemeral CA trust, fixed methods/headers and bounded
asset ranges. It never follows redirects or disables certificate verification.
"""

import asyncio
import base64
import json
import re
import ssl
import sys
import threading
from pathlib import Path
from typing import Any, Literal, get_args
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

CHUNK = 12_288
REQUEST_HEADERS = frozenset(
    {
        "content-type",
        "cookie",
        "origin",
        "x-csrf-token",
        "x-emailmonitor-ui",
        "idempotency-key",
        "last-event-id",
        "accept",
    }
)
REPLY_HEADERS = frozenset(
    {
        "content-type",
        "cache-control",
        "content-disposition",
        "location",
        "set-cookie",
        "content-range",
    }
)
RelayRoute = Literal[
    "issuer_authorize",
    "auth",
    "callback_document",
    "static",
    "job_list",
    "job_detail",
    "job_progress",
    "job_items",
    "job_events",
    "export_metadata",
    "export_download",
    "other_api",
]
RelayPhase = Literal["client_open", "response_enter", "response_open"]
_UUID_PATH = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def diagnostic_route(target: str, api: str, issuer: str, assets: dict[str, str]) -> RelayRoute:
    """Classify an already validated target; no target data enters the record."""
    parsed = urlsplit(target)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path
    if origin == issuer and path == "/authorize":
        return "issuer_authorize"
    if origin != api:
        raise ValueError("Validated installed relay target required")
    if path in {"/api/v1/auth/start", "/api/v1/auth/session", "/api/v1/auth/logout"}:
        return "auth"
    if path == "/auth/complete":
        return "callback_document"
    if path == "/" or path.lstrip("/") in assets:
        return "static"
    scoped = re.fullmatch(rf"/api/v1/organizations/{_UUID_PATH}/(.+)", path)
    if scoped is not None:
        resource = scoped.group(1)
        if resource == "jobs":
            return "job_list"
        if re.fullmatch(rf"jobs/{_UUID_PATH}", resource):
            return "job_detail"
        if re.fullmatch(rf"jobs/{_UUID_PATH}/progress", resource):
            return "job_progress"
        if re.fullmatch(rf"jobs/{_UUID_PATH}/progress/items", resource):
            return "job_items"
        if re.fullmatch(rf"jobs/{_UUID_PATH}/events", resource):
            return "job_events"
        if resource == "exports" or re.fullmatch(rf"exports/{_UUID_PATH}", resource):
            return "export_metadata"
        if re.fullmatch(rf"exports/{_UUID_PATH}/download", resource):
            return "export_download"
    return "other_api"


class RelayDiagnostics:
    """One request-local, closed failure tuple across the host's relay threads."""

    def __init__(self) -> None:
        self.first: tuple[RelayRoute, RelayPhase, Literal["read_timeout"]] | None = None
        self._lock = threading.Lock()

    def capture(self, error: Exception, route: RelayRoute, last_phase: RelayPhase) -> None:
        if type(error) is not httpx.ReadTimeout:
            return
        if (
            type(route) is not str
            or route not in get_args(RelayRoute)
            or type(last_phase) is not str
            or last_phase not in get_args(RelayPhase)
        ):
            raise ValueError("Closed installed relay diagnostic required")
        record: tuple[RelayRoute, RelayPhase, Literal["read_timeout"]] = (
            route,
            last_phase,
            "read_timeout",
        )
        with self._lock:
            if self.first is not None:
                return
            self.first = record
        # Latch before output, with no retry if formatting or stderr fails.
        print(
            json.dumps(
                {
                    "diagnostic": "installed-relay-failure",
                    "route": record[0],
                    "last_phase": record[1],
                    "error": record[2],
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )


def validate_target(
    value: dict[str, Any], api: str, issuer: str, assets: dict[str, str]
) -> tuple[str, str, dict[str, str], str]:
    if set(value) != {"target", "method", "headers", "body", "offset"}:
        raise ValueError("Closed installed relay grammar required")
    target, method, headers, body, offset = (
        value[key] for key in ("target", "method", "headers", "body", "offset")
    )
    if (
        not isinstance(target, str)
        or len(target) > 8192
        or method not in {"GET", "POST", "PATCH"}
        or not isinstance(headers, dict)
        or len(headers) > 12
        or not isinstance(body, str)
        or len(body.encode()) > 16_384
        or (method == "GET" and body)
    ):
        raise ValueError("Bounded installed request required")
    parsed = urlsplit(target)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if (
        origin not in {api, issuer}
        or parsed.username
        or parsed.password
        or parsed.fragment
        or any(part in parsed.path for part in ("%", "\\", "/../", "/./"))
    ):
        raise ValueError("Exact ephemeral loopback origin required")
    for key, item in headers.items():
        if (
            key not in REQUEST_HEADERS
            or not isinstance(item, str)
            or len(item) > 4096
            or not item.isascii()
            or any(ord(char) < 32 or ord(char) == 127 for char in item)
        ):
            raise ValueError("Closed request headers required")
    if "origin" in headers and headers["origin"] != api:
        raise ValueError("Exact API origin required")
    if origin == issuer:
        if method != "GET" or parsed.path != "/authorize" or offset is not None:
            raise ValueError("Browser may only reach the synthetic authorization endpoint")
        if "cookie" in headers or "x-csrf-token" in headers:
            raise ValueError("Application credentials must not reach issuer")
    elif parsed.path.startswith("/api/v1/"):
        if offset is not None:
            raise ValueError("API ranges refused")
    elif parsed.path in {"/", "/auth/complete"} or parsed.path.lstrip("/") in assets:
        if (
            method != "GET"
            or type(offset) is not int
            or offset < 0
            or offset > 1_048_576
            or offset % CHUNK
            or (parsed.query and parsed.path != "/auth/complete")
        ):
            raise ValueError("Bounded compiled asset range required")
        headers = {**headers, "range": f"bytes={offset}-{offset + CHUNK - 1}"}
    else:
        raise ValueError("Installed relay path refused")
    return target, method, headers, body


def application(
    api: str, issuer: str, ca: Path, assets: dict[str, str], downloads: list[bytes]
) -> FastAPI:
    for origin in (api, issuer):
        if not re.fullmatch(r"https://127\.0\.0\.1:[1-9][0-9]{0,4}", origin):
            raise ValueError("Ephemeral loopback HTTPS origin required")
    context = ssl.create_default_context(cafile=str(ca))
    app = FastAPI()
    diagnostics = RelayDiagnostics()

    @app.post("/api/v1/installed-relay")
    async def relay(request: Request) -> JSONResponse:
        raw = await request.body()
        if len(raw) > 32768:
            raise ValueError("Bounded relay envelope required")
        target, method, headers, body = validate_target(json.loads(raw), api, issuer, assets)
        route = diagnostic_route(target, api, issuer, assets)
        # These are last-entered phases, not attribution to an exact failing I/O.
        last_phase: RelayPhase = "client_open"
        try:
            async with httpx.AsyncClient(
                verify=context, trust_env=False, follow_redirects=False, timeout=4
            ) as client:
                last_phase = "response_enter"
                async with client.stream(method, target, headers=headers, content=body) as response:
                    last_phase = "response_open"  # Includes body processing and context cleanup.
                    output = bytearray()
                    stream = response.headers.get("content-type", "").startswith(
                        "text/event-stream"
                    )
                    try:
                        async with asyncio.timeout(2 if stream else 5):
                            async for chunk in response.aiter_bytes():
                                output.extend(chunk)
                                if len(output) > 16_384:
                                    raise ValueError("Actual HTTPS response exceeds bounded relay")
                    except TimeoutError:
                        if not stream:
                            raise
                    if stream:
                        end = output.rfind(b"\n\n")
                        output = output[: end + 2] if end >= 0 else bytearray()
                    if urlsplit(target).path.endswith("/download") and response.status_code == 200:
                        if len(downloads) >= 2:
                            raise ValueError("Bounded export receipt count exceeded")
                        downloads.append(bytes(output))
                    result_headers = {
                        key: "\n".join(response.headers.get_list(key))
                        for key in REPLY_HEADERS
                        if key in response.headers
                    }
                    return JSONResponse(
                        {
                            "status": response.status_code,
                            "headers": result_headers,
                            "body": base64.b64encode(output).decode(),
                        }
                    )
        except httpx.ReadTimeout as error:
            try:
                diagnostics.capture(error, route, last_phase)
            except BaseException:
                # A secondary diagnostic failure must never replace the pending failure.
                pass
            raise

    return app

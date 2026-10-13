"""Synthetic UI diagnostic RPC grammar; never a general network proxy."""

import base64
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ORIGIN = "https://app.example.test"
MAX_BODY = 32768


class RequestFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: str
    identifier: int = Field(ge=1, le=512)
    url: str = Field(max_length=4096)
    method: str
    headers: dict[str, str] = Field(max_length=12)
    body: str = Field(default="", max_length=MAX_BODY)

    @model_validator(mode="after")
    def fixed_same_origin_api(self) -> "RequestFrame":
        parsed = urlsplit(self.url)
        if (
            self.kind != "request"
            or self.method not in {"GET", "POST", "PATCH"}
            or parsed.scheme != "https"
            or parsed.netloc != "app.example.test"
            or parsed.fragment
            or parsed.username
            or parsed.password
            or not parsed.path.startswith("/api/v1/")
            or any(value in parsed.path for value in ("%", "\\", "/../", "/./"))
            or parsed.path.startswith("/api/v1/auth/")
            and parsed.path not in {"/api/v1/auth/session", "/api/v1/auth/logout"}
        ):
            raise ValueError("Fixed synthetic same-origin API only")
        if self.method == "GET" and self.body:
            raise ValueError("GET body refused")
        if len(self.body.encode()) > MAX_BODY:
            raise ValueError("Bounded JSON request required")
        return self

    @field_validator("headers")
    @classmethod
    def fixed_headers(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {
            "content-type",
            "cookie",
            "origin",
            "x-csrf-token",
            "x-emailmonitor-ui",
            "idempotency-key",
            "last-event-id",
            "accept",
        }
        if any(
            key not in allowed
            or not item.isascii()
            or len(item) > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in key + item)
            for key, item in value.items()
        ):
            raise ValueError("Bounded allowlisted headers required")
        if value.get("origin", ORIGIN) != ORIGIN:
            raise ValueError("Fixed synthetic origin required")
        return value


def encoded_reply(
    identifier: int, status: int, headers: dict[str, str], body: bytes
) -> dict[str, object]:
    if len(body) > MAX_BODY or not 100 <= status <= 599:
        raise ValueError("Diagnostic response exceeds bound")
    if any(key not in {"content-type", "cache-control"} for key in headers):
        raise ValueError("Only safe response metadata crosses diagnostic channel")
    return {
        "kind": "reply",
        "identifier": identifier,
        "status": status,
        "headers": headers,
        "body": base64.b64encode(body).decode(),
    }


def asset_manifest(root: Path) -> dict[str, str]:
    """Only actual bounded compiled entry/script/style files, never links or secrets."""
    import hashlib
    import re

    manifest: dict[str, str] = {}
    if root.is_symlink():
        raise ValueError("Owned compiled asset directory required")
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Compiled asset links refused")
        if not path.is_file():
            continue
        name = str(path.relative_to(root))
        if name != "index.html" and not re.fullmatch(
            r"assets/index-[A-Za-z0-9_-]{8}\.(js|css)", name
        ):
            raise ValueError("Only fixed compiled UI asset types allowed")
        if path.stat().st_size > 1048576 or len(manifest) >= 20:
            raise ValueError("Compiled UI asset limits exceeded")
        manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if "index.html" not in manifest:
        raise ValueError("Actual compiled entry point required")
    return manifest


STAGES = (
    "browser_launch",
    "sandbox",
    "assets_session",
    "source_review",
    "keyword_plan",
    "pause_resume",
    "old_replay",
    "keyword_worker",
    "contacts_retry",
    "evidence_review",
    "export_preview",
    "export_worker",
    "metadata_screens",
    "url_plan",
    "url_worker",
    "empty_contacts",
    "old_contact_response",
    "readonly_role",
    "final_cleanup",
)
ERRORS = {
    "TimeoutError",
    "RuntimeError",
    "Error",
    "AssertionError",
    "ValueError",
    "UnexpectedError",
}


class DiagnosticFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["stage", "failure"]
    stage: str
    error: (
        Literal[
            "TimeoutError",
            "RuntimeError",
            "Error",
            "AssertionError",
            "ValueError",
            "UnexpectedError",
        ]
        | None
    ) = None
    api_statuses: list[int] = Field(default_factory=list, max_length=512)

    @model_validator(mode="after")
    def fixed_diagnostic(self) -> "DiagnosticFrame":
        if self.stage not in STAGES or any(
            type(code) is not int or not 100 <= code <= 599 for code in self.api_statuses
        ):
            raise ValueError("Fixed bounded UI diagnostic required")
        if (
            self.kind == "failure"
            and self.error is None
            or self.kind == "stage"
            and (self.error is not None or self.api_statuses)
        ):
            raise ValueError("Explicit failure or fixed stage required")
        return self


def stderr_summary(raw: bytes) -> dict[str, object]:
    """Fixed source/error metadata only; never echo a guest cookie/body/exception message."""
    value = raw.decode(errors="replace")
    labels = (
        "TimeoutError",
        "RuntimeError",
        "Error",
        "AssertionError",
        "ValueError",
        "ValidationError",
        "TypeError",
        "BrokenPipeError",
        "CancelledError",
        "InvalidStateError",
        "TargetClosedError",
        "UnicodeDecodeError",
        "Task exception was never retrieved",
        "Future exception was never retrieved",
    )
    errors = [
        label
        for label in labels
        if re.search(r"(?<![A-Za-z])" + re.escape(label) + r"(?![A-Za-z])", value)
    ]
    frames = re.findall(
        r'File "/app/(operator_ui_acceptance\.py|operator_ui_protocol\.py)", '
        r"line ([0-9]{1,6})(?:,|\n)",
        value,
    )
    return {
        "bytes": len(raw),
        "classes": errors[:8],
        "frames": [{"file": name, "line": int(line)} for name, line in frames[-8:]],
    }

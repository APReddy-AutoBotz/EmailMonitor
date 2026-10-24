"""Synthetic UI diagnostic RPC grammar; never a general network proxy."""

import base64
import re
from pathlib import Path
from typing import Literal, get_args
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

InstalledLoginPhase = Literal[
    "initial_session",
    "start_activation",
    "authorize_failure",
    "authorize_navigation",
    "callback_failure",
    "callback_document",
    "callback_session",
    "callback_complete",
    "organization",
]
InstalledReason = Literal[
    "installed_login_failed",
    "installed_login_deadline",
    "installed_expected_navigation_mismatch",
    "installed_redirect_order",
    "installed_redirect_source",
    "installed_redirect_request_identity",
    "installed_redirect_status",
    "installed_redirect_location",
    "installed_redirect_query",
    "installed_redirect_authorization",
    "installed_redirect_cookie",
    "installed_redirect_callback_query",
    "installed_redirect_state",
    "installed_redirect_failure_identity",
    "installed_redirect_ancestry",
    "installed_redirect_aborted",
    "installed_redirect_certificate",
    "installed_redirect_timeout",
    "installed_redirect_network",
    "installed_route_headers",
    "installed_route_relay",
    "installed_relay_request_capacity",
    "installed_relay_admission_capacity",
    "installed_relay_request_size",
    "installed_relay_outer_status",
    "installed_static_range",
    "installed_static_hash",
    "installed_redirect_arm",
    "installed_route_fulfill",
]


OutcomePhase = Literal[
    "outcomes_actual_escape",
    "outcomes_actual_modal",
    "outcomes_actual_quality",
    "outcomes_actual_initial_focus",
    "outcomes_authored_load",
    "outcomes_authored_modal",
    "outcomes_complete_page_set",
    "outcomes_counts_and_states",
    "outcomes_late_job",
    "outcomes_presence_keyboard",
    "outcomes_late_filter",
    "outcomes_exact_article_navigation",
    "outcomes_actual_filter_preview",
    "outcomes_request_generation",
    "outcomes_late_organization",
    "outcomes_organization_switch_away",
    "outcomes_organization_switch_back",
    "outcomes_organization_reopen_job",
    "outcomes_modal_tab",
    "outcomes_next_focus",
    "outcomes_next_rows",
    "outcomes_next_tab",
    "outcomes_page_denied",
    "outcomes_previous_focus",
    "outcomes_previous_rows",
    "outcomes_previous_tab",
    "outcomes_quality_denied",
    "outcomes_quality_escape",
    "outcomes_quality_pending",
    "outcomes_read_only",
    "outcomes_scoped_contacts",
    "outcomes_scoped_review",
    "outcomes_stream_invalidation",
]
OUTCOME_PHASES = get_args(OutcomePhase)

EvidencePhase = Literal["contacts", "open", "citation", "reason", "save", "closed", "returned"]
EVIDENCE_PHASES = get_args(EvidencePhase)
InstalledCallbackDelivery = Literal[
    "not_requested", "request_received", "asset_verified", "fulfilled"
]


class InstalledExportStep(BaseModel):
    """Only fixed steps of the owned synthetic XML export journey."""

    model_config = ConfigDict(extra="forbid", strict=True)
    phase: Literal[
        "navigate",
        "format",
        "preview_activate",
        "preview_wait",
        "create",
        "row_wait",
        "ready_wait",
        "refresh",
        "download_activate",
        "download_wait",
        "verify",
    ]
    format: Literal["xlsx", "csv"] | None


class FocusExhaustion(BaseModel):
    """Value-free state sampled after the unchanged keyboard limit fails."""

    model_config = ConfigDict(extra="forbid", strict=True)
    target_focused: bool
    document_focused: bool
    modal_open: bool
    active_kind: Literal["target", "body", "outcomes_heading", "other", "none"]
    target_kind: Literal["button", "textarea", "select", "input", "other"] | None = None
    active_control: Literal["button", "textarea", "select", "input", "other"] | None = None
    target_disabled: bool | None = None
    target_in_dialog: bool | None = None
    active_in_target_dialog: bool | None = None
    target_inert: bool | None = None
    target_tab_stop: bool | None = None


class ObservationState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    opener_connected: bool
    region_connected: bool
    dialog_present: bool
    dialog_open: bool
    quality: Literal["missing", "loading", "unavailable", "expected", "other"]


class ObservationTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    states: list[ObservationState] = Field(min_length=1, max_length=8)
    truncated: bool


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
    reason: (
        Literal[
            "unknown",
            "rpc_capacity",
            "rpc_request_capacity",
            "rpc_admission_capacity",
            "keyboard_focus",
            "dialog_focus_restore",
            "route_fulfill_failed",
            "route_fulfill_unclassified",
            "route_headers_aborted",
            "route_headers_unclassified",
            "route_headers_future_state",
            "route_headers_loop_state",
            "route_headers_iteration_state",
        ]
        | InstalledReason
    ) = "unknown"
    outcome_phase: OutcomePhase | None = None
    observation_trace: ObservationTrace | Literal["unavailable"] | None = None
    evidence_phase: EvidencePhase | None = None
    installed_callback_delivery: InstalledCallbackDelivery | None = None
    installed_export_step: InstalledExportStep | None = None
    focus_exhaustion: FocusExhaustion | Literal["unavailable"] | None = None
    installed_login_phase: InstalledLoginPhase | None = None
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
            and (self.error is not None or self.api_statuses or self.reason != "unknown")
        ):
            raise ValueError("Explicit failure or fixed stage required")
        if self.outcome_phase is not None and (
            self.kind != "failure" or self.stage != "url_worker"
        ):
            raise ValueError("Outcome phase requires its exact failure stage")
        if self.observation_trace is not None and (
            self.kind != "failure"
            or self.stage != "url_worker"
            or self.outcome_phase != "outcomes_actual_quality"
            or self.error != "AssertionError"
        ):
            raise ValueError("Observation trace requires its exact content assertion failure")
        if self.focus_exhaustion is not None and (
            self.kind != "failure"
            or self.reason != "keyboard_focus"
            or self.error != "RuntimeError"
        ):
            raise ValueError("Focus state requires its exact keyboard failure")
        if self.evidence_phase is not None and (
            self.kind != "failure" or self.stage != "evidence_review"
        ):
            raise ValueError("Evidence phase requires its exact failure stage")
        if self.installed_export_step is not None and (
            self.kind != "failure" or self.stage != "export_preview"
        ):
            raise ValueError("Export step requires its exact failure stage")
        if self.installed_callback_delivery is not None and (
            self.kind != "failure" or self.installed_login_phase != "callback_document"
        ):
            raise ValueError("Callback delivery requires its exact navigation failure")
        if self.installed_login_phase is not None and (
            self.kind != "failure" or self.stage not in {"assets_session", "keyword_worker"}
        ):
            raise ValueError("Installed login phase requires its exact failure stage")
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


def failure_reason(error: BaseException) -> str:
    """Exact known source messages only; no substring or arbitrary exception text."""
    if type(error) is not RuntimeError or len(error.args) != 1 or type(error.args[0]) is not str:
        return "unknown"
    return {
        "UI diagnostic concurrency/request cap exceeded": "rpc_capacity",
        "UI diagnostic request cap exceeded": "rpc_request_capacity",
        "UI diagnostic admission cap exceeded": "rpc_admission_capacity",
        "Control not reachable by keyboard": "keyboard_focus",
        "Evidence dialog did not restore keyboard focus": "dialog_focus_restore",
    }.get(error.args[0], "unknown")


def route_failure_reason(failure: object) -> str:
    """Diagnostic category only; never changes refusal or echoes request text."""
    return (
        "route_fulfill_failed"
        if type(failure) is str and failure == "net::ERR_FAILED"
        else "route_fulfill_unclassified"
    )


def route_headers_reason(failure: object, error: object = None) -> str:
    """Closed diagnostic categories; no message is returned and every error still refuses."""
    if type(error) is RuntimeError and len(error.args) == 1 and type(error.args[0]) is str:
        message = error.args[0]
        if (
            len(message) <= 2048
            and message.isascii()
            and "\n" not in message
            and "\r" not in message
        ):
            # Pinned Playwright preserves the exception class while adding this
            # API prefix when replaying a prior callback error at all_headers.
            if message.startswith("Request.all_headers: "):
                message = message.removeprefix("Request.all_headers: ")
            elif message.startswith(": "):
                # rawRequestHeaders is_internal=True clears the pinned apiName.
                message = message.removeprefix(": ")
            if message in {
                "UI diagnostic concurrency/request cap exceeded",
                "UI diagnostic request cap exceeded",
                "UI diagnostic admission cap exceeded",
            }:
                return failure_reason(RuntimeError(message))
            if message in {
                "await wasn't used with future",
                "cannot reuse already awaited coroutine",
            }:
                return "route_headers_future_state"
            if message == "Event loop is closed" or (
                message.startswith("Task ")
                and " got Future " in message
                and message.endswith(" attached to a different loop")
            ):
                return "route_headers_loop_state"
            if message == "dictionary changed size during iteration":
                return "route_headers_iteration_state"
    return (
        "route_headers_aborted"
        if type(failure) is str and failure == "net::ERR_ABORTED"
        else "route_headers_unclassified"
    )


def completion_state_counts(states: object) -> dict[str, int]:
    """Fixed operational state counts only, never IDs or arbitrary job content."""
    known = {
        "draft",
        "awaiting_approval",
        "ready",
        "queued",
        "running",
        "pausing",
        "paused",
        "cancelling",
        "cancelled",
        "completed",
        "completed_partial",
        "failed",
    }
    if (
        type(states) is not list
        or len(states) > 16
        or any(type(value) is not str or value not in known for value in states)
    ):
        raise ValueError("Bounded known job states required")
    return {value: states.count(value) for value in sorted(set(states))}


class CompletionUnit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["discover", "article"]
    state: Literal[
        "pending",
        "running",
        "retry_wait",
        "succeeded",
        "no_contact",
        "needs_review",
        "policy_blocked",
        "access_blocked",
        "unsupported",
        "skipped",
        "failed",
        "cancelled",
    ]
    reason: Literal[
        "scheduled",
        "leased",
        "observed",
        "no_contact",
        "requires_review",
        "browser_not_completed",
        "source_policy_changed",
        "worker_failure",
        "lease_exhausted",
        "user_cancelled",
        "pagination_committed",
        "quota_exhausted",
    ]
    attempts: int = Field(ge=0, le=3)
    lease_live: bool
    published: bool


def completion_unit_counts(rows: object) -> dict[str, int]:
    """Closed phase/fence categories only; never input URLs or resource identifiers."""
    if type(rows) is not list or len(rows) > 32:
        raise ValueError("Bounded completion rows required")
    counts: dict[str, int] = {}
    for value in rows:
        unit = CompletionUnit.model_validate(value)
        label = (
            f"{unit.kind}:{unit.state}:{unit.reason}:attempts={unit.attempts}:"
            f"lease_live={int(unit.lease_live)}:published={int(unit.published)}"
        )
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def completion_failure_classes(body: bytes) -> list[str]:
    """Match a small class allowlist in owned logs without returning log text."""
    if len(body) > 65536:
        raise ValueError("Bounded owned log tail required")
    known = (
        "AuthorizationDenied",
        "RevisionConflict",
        "ProgrammingError",
        "OperationalError",
        "IntegrityError",
        "HTTPException",
        "TimeoutError",
        "RuntimeError",
        "ValueError",
        "DBAPIError",
    )
    return sorted(name for name in known if name.encode() in body)


def completion_queue_counts(ready: object, consumers: object) -> dict[str, int]:
    """Only bounded integer counts from one exact owned parse queue, never queue names."""
    if type(ready) is not int or not 0 <= ready <= 10000:
        raise ValueError("Bounded owned ready count required")
    if type(consumers) is not int or not 0 <= consumers <= 16:
        raise ValueError("Bounded owned consumer count required")
    return {"ready": ready, "consumers": consumers}


WORKER_PREFIX = b"EM_UI_WORKER_V1 "
WORKER_STAGES = (
    "worker_ready",
    "task_received",
    "execute_enter",
    "validated",
    "claim_enter",
    "claim_empty",
    "claim_acquired",
    "claim_error",
    "process_enter",
    "process_return",
    "process_error",
    "task_postrun",
    "task_failure",
)
WORKER_FAILURE_CLASSES = (
    "FetchDenied",
    "IsolationUnavailable",
    "AssertionError",
    "KeyError",
    "OSError",
    "RuntimeError",
    "TimeoutError",
    "TypeError",
    "ValueError",
    "other",
)
WORKER_FAILURE_REASONS = (
    "source_entitlement_denied",
    "source_policy_denied",
    "source_resource_scope_denied",
    "source_admission_deadline",
    "source_response_denied",
    "total_deadline_exceeded",
    "other",
)


class WorkerFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    phase: Literal["claim", "process", "other"]
    exception_class: str = Field(alias="class")
    reason: str

    @model_validator(mode="after")
    def closed_failure(self) -> "WorkerFailure":
        if (
            self.exception_class not in WORKER_FAILURE_CLASSES
            or self.reason not in WORKER_FAILURE_REASONS
            or self.exception_class != "FetchDenied"
            and self.reason != "other"
        ):
            raise ValueError("Closed worker failure categories required")
        return self


class WorkerSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    counts: dict[str, int]
    last_stage: str
    last_failure: WorkerFailure | None
    saturated: bool

    @model_validator(mode="after")
    def closed_cumulative_snapshot(self) -> "WorkerSnapshot":
        if (
            set(self.counts) != set(WORKER_STAGES)
            or any(not 0 <= value <= 512 for value in self.counts.values())
            or self.last_stage not in WORKER_STAGES
            or self.counts.get(self.last_stage, 0) == 0
            or not 1 <= sum(self.counts.values()) <= 512
            or self.saturated != (sum(self.counts.values()) == 512)
            or (self.last_failure is not None) != (self.counts.get("task_failure", 0) > 0)
            or self.last_failure is not None
            and self.last_failure.phase != "other"
            and self.counts.get(self.last_failure.phase + "_error", 0) == 0
        ):
            raise ValueError("Closed bounded worker counters required")
        return self


def completion_worker_snapshot(raw: bytes, *, truncated: bool = False) -> dict[str, object]:
    """Parse only fixed-prefix cumulative records in the existing bounded owned tail.

    Missing/truncated/invalid evidence never becomes zero counts. Ordinary log
    text, task IDs, bodies, routes, exception messages and secrets are not echoed.
    A task_postrun observation is not a broker acknowledgement.
    """
    import json

    empty: dict[str, object] = {
        "counts": None,
        "last_stage": None,
        "last_failure": None,
        "saturated": None,
    }
    if len(raw) > 65536 or type(truncated) is not bool:
        return {"status": "invalid", **empty}
    lines = raw.splitlines(keepends=True)
    if truncated and lines:
        lines = lines[1:]  # A bounded tail may start in the middle of any log line.
    last: WorkerSnapshot | None = None
    incomplete = truncated

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate diagnostic key")
            value[key] = item
        return value

    for line in lines:
        if not line.startswith(WORKER_PREFIX):
            continue
        if not line.endswith(b"\n"):
            incomplete = True
            continue
        if len(line) > 1024:
            return {"status": "invalid", **empty}
        try:
            value = WorkerSnapshot.model_validate(
                json.loads(line[len(WORKER_PREFIX) :], object_pairs_hook=unique)
            )
            if last is not None and (
                any(
                    value.counts[key] != last.counts[key] + int(key == value.last_stage)
                    for key in WORKER_STAGES
                )
                or value.last_stage != "task_failure"
                and value.last_failure != last.last_failure
                or value.last_stage == "task_failure"
                and value.last_failure is not None
                and value.last_failure.phase
                != {"claim_error": "claim", "process_error": "process"}.get(
                    last.last_stage, "other"
                )
            ):
                raise ValueError("Non-cumulative diagnostic counters")
            last = value
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return {"status": "invalid", **empty}
    if last is None:
        return {"status": "truncated" if incomplete else "unavailable", **empty}
    return {
        "status": "truncated" if incomplete or last.saturated else "available",
        **last.model_dump(by_alias=True),
    }


def validate_journey(setup: dict[str, object]) -> None:
    """Closed built-in journeys only; no caller-supplied browser destinations."""
    journey = setup.get("journey")
    if journey not in (
        None,
        "controlled_provider",
        "controlled_browser",
        "controlled_keyword_browser",
    ):
        raise ValueError("Fixed controlled operator journey required")
    if journey in ("controlled_browser", "controlled_keyword_browser") and set(setup) != {
        "kind",
        "origin",
        "journey",
        "cookies",
        "assets",
        "initial_organization",
        "other_organization",
    }:
        raise ValueError("Fixed controlled browser bootstrap required")

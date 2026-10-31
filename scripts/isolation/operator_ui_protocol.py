"""Synthetic UI diagnostic RPC grammar; never a general network proxy."""

import base64
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Literal, get_args
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ORIGIN = "https://app.example.test"
MAX_BODY = 32768


@dataclass(eq=False)
class ReplayRequest:
    kind: str
    epoch: int
    eligible: bool
    offered: bool = False
    delivered: bool = False
    loading: bool = False
    headers_seen: bool = False
    item: str | None = None
    render_before: object | None = None


class OutcomeReplayReadiness:
    """Owned test observations only; never authorizes or changes a reply."""

    def __init__(self, organization: str, job: str | None = None) -> None:
        self.organization = str(UUID(organization))
        self.root = f"/api/v1/organizations/{self.organization}"
        self.job = str(UUID(job)) if job is not None else None
        self.generation: int | None = None
        self.terminal_job = False
        self.epoch = 0
        self.cursor: str | None = None
        self.sequence = 0
        self.replay: ReplayRequest | None = None
        self.ack: ReplayRequest | None = None
        self.progress: ReplayRequest | None = None
        self.outcomes: ReplayRequest | None = None
        self.job_request: ReplayRequest | None = None
        self.failed = False
        self.invalidated = False
        self.latest_events: ReplayRequest | None = None

    def begin(self, url: str, method: str) -> ReplayRequest | None:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "app.example.test":
            return None
        if parsed.path == self.root + "/jobs" and method == "POST" and self.job is None:
            return ReplayRequest("create", self.epoch, False)
        if self.job is None or method != "GET":
            return None
        base = self.root + "/jobs/" + self.job
        kind = {base: "job", base + "/events": "events", base + "/progress": "progress"}.get(
            parsed.path
        )
        if parsed.path == self.root + "/article-outcomes":
            query = parse_qs(parsed.query)
            if query.get("job_id") == [self.job] and query.get("limit") == ["25"]:
                if query.keys() - {"job_id", "limit", "article_outcome_presence"} or query.get(
                    "article_outcome_presence", ["all"]
                ) != ["all"]:
                    self.failed = True
                kind = "outcomes"
        if kind is None:
            return None
        token = ReplayRequest(kind, self.epoch, self.cursor is not None)
        if kind == "events":
            self.latest_events = token
        elif kind == "job":
            self.job_request = token
            self.terminal_job = False
        elif kind == "progress":
            self.progress = token
        elif kind == "outcomes":
            self.outcomes = token
        return token

    def headers(self, token: ReplayRequest | None, headers: dict[str, str]) -> None:
        if token is None or token.kind != "events" or token is not self.latest_events:
            return
        token.headers_seen = True
        cursor = headers.get("last-event-id", "")
        if not cursor:
            self.epoch += 1
            self.invalidated = False
            token.epoch = self.epoch
            self.cursor, self.sequence = None, 0
            self.replay, self.ack, self.progress, self.outcomes = None, None, None, None
        elif token.epoch == self.epoch and self.cursor is not None:
            if cursor == self.cursor:
                if self.ack is None or not self.ack.delivered:
                    self.ack = token
            else:
                self.failed = True

    def current(self, token: ReplayRequest) -> bool:
        if token.kind in {"create", "job"}:
            return token.kind == "create" or token is self.job_request
        return token.epoch == self.epoch and (
            token.kind == "events" or token is self.progress or token is self.outcomes
        )

    def offer(self, token: ReplayRequest | None, status: int, body: bytes) -> None:
        if token is None or not self.current(token):
            return
        try:
            if len(body) > MAX_BODY or status != (201 if token.kind == "create" else 200):
                raise ValueError
            if token.kind == "events":
                last: tuple[str, int, str] | None = None
                terminal = False
                for frame in body.decode().split("\n\n"):
                    data = [line[6:] for line in frame.splitlines() if line.startswith("data: ")]
                    if not data:
                        continue
                    ids = [line[4:] for line in frame.splitlines() if line.startswith("id: ")]
                    if len(data) != 1 or len(ids) != 1:
                        raise ValueError
                    event = json.loads(data[0])
                    sequence = event.get("sequence")
                    if (
                        event.get("organization_id") != self.organization
                        or event.get("job_id") != self.job
                        or type(sequence) is not int
                        or not 1 <= sequence <= 9223372036854775807
                        or ids[0] != f"{self.organization}/{self.job}:{sequence}"
                        or last is not None
                        and sequence <= last[1]
                    ):
                        raise ValueError
                    terminal = terminal or event.get("event_type") == "job.finished"
                    last = (ids[0], sequence, event.get("event_type", ""))
                if terminal and last is not None:
                    self.cursor, self.sequence, self.replay = last[0], last[1], token
                    self.ack, self.progress, self.outcomes = None, None, None
                elif last is not None and self.cursor is not None:
                    # A later event invalidates this content-inspection precondition.
                    raise ValueError
            else:
                data = json.loads(body)
                if token.kind == "create":
                    self.job = str(UUID(data["id"]))
                elif token.kind == "job":
                    generation = data.get("generation")
                    if (
                        data.get("id") != self.job
                        or type(generation) is not int
                        or generation < 1
                        or self.generation not in {None, generation}
                    ):
                        raise ValueError
                    self.generation = generation
                    self.terminal_job = data.get("state") == "completed"
                elif token.eligible:
                    if token.kind == "progress":
                        if (
                            data.get("organization_id") != self.organization
                            or data.get("job_id") != self.job
                            or data.get("generation") != self.generation
                            or type(data.get("generation")) is not int
                            or data.get("state") != "completed"
                            or type(data.get("last_sequence")) is not int
                            or data["last_sequence"] < self.sequence
                        ):
                            raise ValueError
                    elif token.kind == "outcomes":
                        token.item = self.outcome_item(data, token)
            token.offered = True
        except (ValueError, TypeError, KeyError, AttributeError):
            self.failed = True

    def outcome_item(self, data: dict[str, object], token: ReplayRequest) -> str:
        items = data.get("items")
        if (
            not isinstance(items, list)
            or len(items) != 1
            or data.get("next_cursor") is not None
            or not token.loading
        ):
            raise ValueError
        item = items[0]
        if (
            item.get("organization_id") != self.organization
            or item.get("job_id") != self.job
            or item.get("state") != "no_contact"
            or item.get("batch_id") is None
        ):
            raise ValueError
        return str(UUID(item["item_id"]))

    def finish(self, token: ReplayRequest | None, delivered: bool) -> None:
        if token is None or not self.current(token):
            return
        if not delivered and token.kind == "events":
            self.invalidated = True
        token.delivered = delivered

    def ready(self) -> ReplayRequest | None:
        if self.failed or self.invalidated or not self.terminal_job or self.generation is None:
            return None
        if self.latest_events is None or not self.latest_events.headers_seen:
            return None
        tokens = (self.job_request, self.replay, self.ack, self.progress, self.outcomes)
        if any(token is None or not token.offered or not token.delivered for token in tokens):
            return None
        if any(token is None or not token.eligible for token in (self.progress, self.outcomes)):
            return None
        return self.outcomes if self.outcomes is not None and self.outcomes.item else None


class AuthoredOutcomeReplayReadiness(OutcomeReplayReadiness):
    """Only the existing authored 127-row journey's first 25-row response."""

    def outcome_item(self, data: dict[str, object], token: ReplayRequest) -> str:
        items = data.get("items")
        if (
            not token.loading
            or not isinstance(items, list)
            or len(items) != 25
            or data.get("next_cursor") != "25"
        ):
            raise ValueError
        states = (
            "no_contact",
            "policy_blocked",
            "access_blocked",
            "unsupported",
            "failed",
            "succeeded",
        )
        for index, item in enumerate(items):
            if not isinstance(item, dict) or any(
                (
                    item.get("organization_id") != self.organization,
                    item.get("job_id") != self.job,
                    item.get("item_id") != f"00000000-0000-4000-8000-{index + 1:012d}",
                    item.get("source_url")
                    != f"https://synthetic.publisher.example/authored-outcome-{index:03d}.html",
                    item.get("state") != states[index % len(states)],
                    item.get("batch_id")
                    != ("00000000-0000-4000-8000-000000000127" if index == 0 else None),
                )
            ):
                raise ValueError
        return "00000000-0000-4000-8000-000000000001"


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
    "lifecycle_cancel",
    "lifecycle_pause",
    "lifecycle_resume",
    "lifecycle_confirm_cancel",
    "lifecycle_cancel_retry",
    "lifecycle_retained_review",
    "lifecycle_export",
    "lifecycle_export_preview",
    "lifecycle_export_create",
    "lifecycle_export_wait",
    "lifecycle_export_ready",
    "lifecycle_unlink_export_navigation",
    "lifecycle_unlink_export_assertion",
    "lifecycle_unlink_export_loading_present",
    "lifecycle_unlink_export_alert_present",
    "lifecycle_unlink_export_empty",
    "lifecycle_unlink_export_enabled",
    "lifecycle_unlink_export_disabled",
    "lifecycle_unlink_export_missing",
    "lifecycle_unlink_export_not_exports",
    "lifecycle_unlink_export_unavailable",
    "lifecycle_cleanup",
    "lifecycle_retry",
    "lifecycle_switch",
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
    "reuse_plan",
    "reuse_worker",
    "reuse_results",
    "reuse_review",
    "reuse_export",
    "reuse_preview",
    "empty_contacts",
    "old_contact_response",
    "readonly_role",
    "contact_suppression",
    "job_deletion",
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
    "installed_redirect_order_bind",
    "installed_redirect_order_commit",
    "installed_redirect_order_lifecycle",
    "installed_redirect_order_public_commit",
    "installed_redirect_order_public_load",
    "installed_redirect_order_begin",
    "installed_redirect_order_arm",
    "installed_redirect_order_failure",
    "installed_redirect_failure_latched",
    "installed_redirect_failure_inactive",
    "installed_redirect_failure_unarmed",
    "installed_redirect_failure_duplicate",
    "installed_redirect_order_next",
    "installed_redirect_order_finish",
    "installed_redirect_order_receipt",
    "installed_redirect_order_observer",
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
    "outcomes_actual_replay",
    "outcomes_replay_delayed",
    "outcomes_replay_invalidated",
    "outcomes_replay_rendered",
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

JobDeletionPhase = Literal[
    "navigate_jobs",
    "open_job",
    "choose_reason",
    "cancel_confirmation",
    "open_confirmation",
    "confirm_focus",
    "confirm_keypress",
    "confirm_close",
    "receipt",
    "settled_requests",
]

ContactSuppressionPhase = Literal[
    "select_organization",
    "open_contacts",
    "read_contact",
    "open_evidence_cancel",
    "open_evidence_confirm",
    "choose_reason_cancel",
    "choose_reason_confirm",
    "open_confirmation_cancel",
    "open_confirmation_confirm",
    "cancel_confirmation",
    "confirm_suppression",
    "verify_result",
]

EvidencePhase = Literal[
    "contacts",
    "open",
    "citation",
    "reason",
    "save",
    "closed",
    "returned",
    "escape_close",
    "button_close",
]
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


class KeyboardTransition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["start", "heading_focus", "target_detached", "target_replaced", "finish"]
    tab: int = Field(ge=0, le=100)
    target_connected: bool


class KeyboardAttemptTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tabs: int = Field(ge=0, le=100)
    truncated: bool
    events: list[KeyboardTransition] = Field(max_length=32)


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
    attempt_trace: KeyboardAttemptTrace | Literal["unavailable"] | None = None


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


class EvidenceFocusState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event: Literal["start", "close", "focus", "mutation", "assertion"]
    dialog_connected: bool
    dialog_open: bool
    close_seen: bool
    opener_connected: bool
    contacts_present: bool
    active_kind: Literal["opener", "dialog", "fallback", "body", "other"]


class EvidenceFocusTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    states: list[EvidenceFocusState] = Field(min_length=1, max_length=8)
    truncated: bool


class HandoffTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key_events: int = Field(ge=0, le=2)
    click_events: int = Field(ge=0, le=2)
    trusted_click: bool
    disabled_on_enter: bool | None
    focused_on_enter: bool | None
    last_enter_target: Literal["handoff", "other", "none"]
    screen: Literal["contacts", "review", "other"]
    association: Literal["accepted", "needs_review", "unmatched", "rejected", "missing", "other"]
    error_count: int = Field(ge=0, le=2)
    error_kind: Literal["none", "type", "reference", "other"]


class LoginTimingTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    total_ms: int = Field(ge=0, le=60000)
    phase_ms: int = Field(ge=0, le=60000)
    callback_fulfilled_ms: int | None = Field(default=None, ge=0, le=60000)


@dataclass
class LoginTiming:
    clock: Callable[[], float] = monotonic
    started: float | None = None
    phase_started: float | None = None
    callback_fulfilled: float | None = None

    def begin(self) -> None:
        self.started = self.clock()
        self.phase_started = self.started
        self.callback_fulfilled = None

    def phase(self) -> None:
        self.phase_started = self.clock()

    def fulfilled(self) -> None:
        if self.callback_fulfilled is None:
            self.callback_fulfilled = self.clock()

    def snapshot(self) -> LoginTimingTrace:
        now = self.clock()
        if self.started is None or self.phase_started is None:
            raise ValueError("Owned login measurement must be started")

        def milliseconds(end: float, start: float) -> int:
            return min(60000, max(0, int((end - start) * 1000)))

        return LoginTimingTrace(
            total_ms=milliseconds(now, self.started),
            phase_ms=milliseconds(now, self.phase_started),
            callback_fulfilled_ms=milliseconds(self.callback_fulfilled, self.started)
            if self.callback_fulfilled is not None
            else None,
        )


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
    handoff_trace: HandoffTrace | Literal["unavailable"] | None = None
    installed_login_timing: LoginTimingTrace | None = None
    export_assertion_line: int | None = Field(default=None, ge=1, le=10000)
    outcome_phase: OutcomePhase | None = None
    job_deletion_phase: JobDeletionPhase | None = None
    contact_suppression_phase: ContactSuppressionPhase | None = None
    observation_trace: ObservationTrace | Literal["unavailable"] | None = None
    evidence_phase: EvidencePhase | None = None
    evidence_focus_trace: EvidenceFocusTrace | Literal["unavailable"] | None = None
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
        if self.handoff_trace is not None and (
            self.kind != "failure" or self.stage != "export_preview"
        ):
            raise ValueError("Handoff trace requires its exact failure stage")
        if self.installed_login_timing is not None and (
            self.kind != "failure" or self.installed_login_phase is None
        ):
            raise ValueError("Login timing requires its owned login failure")
        if self.export_assertion_line is not None and (
            self.kind != "failure"
            or self.stage != "export_preview"
            or self.error != "AssertionError"
        ):
            raise ValueError("Export assertion location requires its exact failure stage")
        if self.outcome_phase is not None and (
            self.kind != "failure" or self.stage != "url_worker"
        ):
            raise ValueError("Outcome phase requires its exact failure stage")
        if self.job_deletion_phase is not None and (
            self.kind != "failure" or self.stage != "job_deletion"
        ):
            raise ValueError("Job deletion phase requires its exact failure stage")
        if self.contact_suppression_phase is not None and (
            self.kind != "failure" or self.stage != "contact_suppression"
        ):
            raise ValueError("Contact suppression phase requires its exact failure stage")
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
        if self.evidence_focus_trace is not None and (
            self.kind != "failure"
            or self.stage != "evidence_review"
            or self.reason != "dialog_focus_restore"
            or self.error != "RuntimeError"
            or self.evidence_phase not in {"escape_close", "button_close"}
        ):
            raise ValueError("Evidence focus trace requires its exact close failure")
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
            self.kind != "failure"
            or self.stage not in {"assets_session", "keyword_worker", "url_worker"}
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


def export_assertion_line(error: BaseException) -> int | None:
    """Only a fixed harness source coordinate; no exception message or local values."""
    if type(error) is not AssertionError:
        return None
    frame = error.__traceback__
    line = None
    while frame is not None:
        if (
            Path(frame.tb_frame.f_code.co_filename).name == "operator_ui_acceptance.py"
            and 1 <= frame.tb_lineno <= 10000
        ):
            line = frame.tb_lineno
        frame = frame.tb_next
    return line


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
    if journey != "controlled_lifecycle" and ({"cancel_job", "retry_job"} & setup.keys()):
        raise ValueError("Lifecycle identifiers require their exact journey")
    if journey not in (
        None,
        "controlled_provider",
        "controlled_lifecycle",
        "controlled_browser",
        "controlled_keyword_browser",
    ):
        raise ValueError("Fixed controlled operator journey required")
    if journey == "controlled_lifecycle":
        if set(setup) != {
            "kind",
            "origin",
            "journey",
            "cookies",
            "assets",
            "initial_organization",
            "other_organization",
            "cancel_job",
            "retry_job",
        }:
            raise ValueError("Fixed lifecycle bootstrap required")
        for key in ("initial_organization", "other_organization", "cancel_job", "retry_job"):
            identifier = setup[key]
            if not isinstance(identifier, str) or str(UUID(identifier)) != identifier:
                raise ValueError("Exact lifecycle identifiers required")
        if setup["cancel_job"] == setup["retry_job"]:
            raise ValueError("Separate lifecycle fixtures required")
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

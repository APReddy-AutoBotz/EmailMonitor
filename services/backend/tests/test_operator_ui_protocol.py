"""Pure diagnostic grammar and actual in-process ASGI transport mechanics."""

import asyncio
import base64
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from operator_ui_asgi import collect_replay, relay
from operator_ui_protocol import ORIGIN, RequestFrame, encoded_reply
from pydantic import ValidationError
from starlette.responses import StreamingResponse


def request(**changes: object) -> RequestFrame:
    return RequestFrame.model_validate(
        {
            "kind": "request",
            "identifier": 1,
            "url": ORIGIN + "/api/v1/organizations/00000000-0000-4000-8000-000000000001/jobs",
            "method": "GET",
            "headers": {},
            **changes,
        }
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "https://external.example/api/v1/jobs"},
        {"url": ORIGIN + "/api/v1/../secret"},
        {"url": ORIGIN + "/api/v1/%2e%2e/secret"},
        {"url": ORIGIN + "/api/v1/auth/start"},
        {"url": "http://app.example.test/api/v1/jobs"},
        {"method": "DELETE"},
        {"identifier": True},
        {"identifier": 1001},
        {"body": "GET-content"},
        {"headers": {"authorization": "unknown"}},
        {"headers": {"origin": "https://external.example"}},
        {"headers": {"cookie": "line\nbreak"}},
        {"url": ORIGIN + "/api/v1/jobs#fragment"},
    ],
)
def test_only_bounded_same_origin_diagnostic_api_is_admitted(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        request(**changes)


def test_diagnostic_reply_preserves_bytes_but_refuses_limits_or_sensitive_headers() -> None:
    value = encoded_reply(1, 200, {"content-type": "application/json"}, b'{"actual":true}')
    assert base64.b64decode(str(value["body"])) == b'{"actual":true}'
    with pytest.raises(ValueError):
        encoded_reply(1, 200, {"set-cookie": "secret"}, b"")
    with pytest.raises(ValueError):
        encoded_reply(1, 200, {}, b"a" * 32769)


def test_actual_asgi_route_status_and_body_are_not_simulated_or_redirected() -> None:
    app = FastAPI()

    @app.get("/api/v1/example")
    def actual() -> dict[str, str]:
        return {"source": "actual-in-process-route"}

    result = asyncio.run(relay(app, request(url=ORIGIN + "/api/v1/example")))
    assert result["status"] == 200
    assert b"actual-in-process-route" in base64.b64decode(str(result["body"]))
    absent = asyncio.run(relay(app, request(url=ORIGIN + "/api/v1/absent")))
    assert absent["status"] == 404


def test_actual_replay_frames_are_preserved_and_incomplete_tail_is_discarded() -> None:
    app = FastAPI()

    @app.get("/api/v1/example/events")
    def events() -> StreamingResponse:
        async def frames() -> AsyncIterator[str]:
            yield 'id: actual\ndata: {"actual":true}\n\n'
            yield "id: incomplete\ndata: "

        return StreamingResponse(frames(), media_type="text/event-stream")

    status, headers, body = asyncio.run(
        collect_replay(app, request(url=ORIGIN + "/api/v1/example/events"))
    )
    assert status == 200 and headers["content-type"].startswith("text/event-stream")
    assert body == b'id: actual\ndata: {"actual":true}\n\n'


def test_asset_manifest_has_only_actual_reviewed_built_files(tmp_path: Path) -> None:
    from operator_ui_protocol import asset_manifest

    (tmp_path / "index.html").write_text("authored entry")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/index-actual12.js").write_text("authored script")
    assert set(asset_manifest(tmp_path)) == {"index.html", "assets/index-actual12.js"}
    (tmp_path / ".env").write_text("unrecognized content")
    with pytest.raises(ValueError):
        asset_manifest(tmp_path)
    (tmp_path / ".env").unlink()
    (tmp_path / "assets/unexpected.js").symlink_to(tmp_path / "index.html")
    with pytest.raises(ValueError):
        asset_manifest(tmp_path)


def test_fixed_failure_and_stage_diagnostics_contain_no_request_content() -> None:
    from operator_ui_protocol import DiagnosticFrame

    assert (
        DiagnosticFrame.model_validate({"kind": "stage", "stage": "assets_session"}).error is None
    )
    row = DiagnosticFrame.model_validate(
        {
            "kind": "failure",
            "stage": "assets_session",
            "error": "TimeoutError",
            "api_statuses": [200, 404],
        }
    )
    assert row.api_statuses == [200, 404]


@pytest.mark.parametrize(
    "changes",
    [
        {"stage": "arbitrary secret"},
        {"error": "arbitrary exception text"},
        {"cookie": "unrecognized"},
        {"api_statuses": [True]},
        {"api_statuses": [99]},
        {"api_statuses": [600]},
        {"api_statuses": [200] * 513},
        {"kind": "stage", "error": "TimeoutError"},
        {"kind": "stage", "error": None, "api_statuses": [200]},
    ],
)
def test_unbounded_or_unrecognized_ui_diagnostics_refuse(changes: dict[str, object]) -> None:
    from operator_ui_protocol import DiagnosticFrame

    with pytest.raises(ValidationError):
        DiagnosticFrame.model_validate(
            {"kind": "failure", "stage": "assets_session", "error": "TimeoutError", **changes}
        )


@pytest.mark.parametrize("phase", [None, "callback_failure"])
def test_owned_pipe_failure_is_observed_before_guest_waits_for_host_eof(
    monkeypatch: pytest.MonkeyPatch,
    phase: str | None,
) -> None:
    import json
    import subprocess
    import sys

    import run_operator_ui_acceptance as host

    original = subprocess.Popen
    frame = {
        "kind": "failure",
        "stage": "assets_session",
        "error": "TimeoutError",
        "api_statuses": [200],
        **(
            {
                "installed_login_phase": phase,
                "reason": "installed_login_deadline",
            }
            if phase is not None
            else {}
        ),
    }

    def owned_python_pipe(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        return original(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdin.readline(); "
                'print(\'{"kind":"stage","stage":"assets_session"}\',flush=True); '
                f"print({json.dumps(frame)!r},flush=True); "
                "sys.stdin.read()",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    monkeypatch.setattr(subprocess, "Popen", owned_python_pipe)
    with pytest.raises(
        RuntimeError, match=r"Actual UI failure at assets_session: TimeoutError.*200"
    ) as failure:
        host.conversation(
            "owned-pipe-only", FastAPI(), {}, lambda action: None, lambda request: False
        )
    if phase is None:
        assert "installed login phase" not in str(failure.value)
    else:
        assert "; installed login phase=callback_failure;" in str(failure.value)


def test_stderr_summary_only_retains_fixed_source_and_error_metadata() -> None:
    from operator_ui_protocol import stderr_summary

    secret = "untrusted-cookie-or-exception-message"
    raw = (
        'Traceback\n  File "/app/operator_ui_acceptance.py", line 123, in main\n'
        "TypeError: " + secret + '\nFile "/unrecognized/' + secret + '", line 4\n'
    ).encode()
    result = stderr_summary(raw)
    assert result == {
        "bytes": len(raw),
        "classes": ["TypeError"],
        "frames": [{"file": "operator_ui_acceptance.py", "line": 123}],
    }
    assert secret not in str(result)
    assert stderr_summary(secret.encode()) == {"bytes": len(secret), "classes": [], "frames": []}


def test_stderr_summary_is_bounded_and_does_not_echo_arbitrary_trace_paths() -> None:
    from operator_ui_protocol import stderr_summary

    result = stderr_summary(b'File "/app/operator_ui_protocol.py", line 99, in fixed\n' * 100)
    assert isinstance(result["frames"], list) and len(result["frames"]) == 8


def test_failure_reason_only_classifies_exact_known_source_messages() -> None:
    from operator_ui_protocol import failure_reason

    assert (
        failure_reason(RuntimeError("UI diagnostic concurrency/request cap exceeded"))
        == "rpc_capacity"
    )
    assert failure_reason(RuntimeError("Control not reachable by keyboard")) == "keyboard_focus"
    assert (
        failure_reason(RuntimeError("Evidence dialog did not restore keyboard focus"))
        == "dialog_focus_restore"
    )
    assert failure_reason(RuntimeError("secret Control not reachable by keyboard")) == "unknown"
    assert failure_reason(RuntimeError("unrecognized private text")) == "unknown"
    assert failure_reason(RuntimeError(1)) == "unknown"
    assert failure_reason(TimeoutError("Control not reachable by keyboard")) == "unknown"


@pytest.mark.parametrize("reason", ["arbitrary secret", "rpc_capacity cookie"])
def test_unrecognized_failure_reason_is_never_accepted(reason: str) -> None:
    from operator_ui_protocol import DiagnosticFrame

    with pytest.raises(ValidationError):
        DiagnosticFrame.model_validate(
            {
                "kind": "failure",
                "stage": "keyword_worker",
                "error": "RuntimeError",
                "reason": reason,
            }
        )


def test_installed_diagnostic_literals_and_existing_frames_are_compatible() -> None:
    from typing import get_args

    from operator_ui_protocol import DiagnosticFrame, InstalledLoginPhase, InstalledReason

    old = {"kind": "failure", "stage": "assets_session", "error": "RuntimeError"}
    parsed = DiagnosticFrame.model_validate(old)
    assert parsed.installed_login_phase is None
    assert parsed.model_dump(exclude_unset=True) == old
    assert "installed_login_phase" not in parsed.model_dump(exclude_none=True)
    stage = DiagnosticFrame.model_validate({"kind": "stage", "stage": "assets_session"})
    assert stage.installed_login_phase is None
    for reason in get_args(InstalledReason):
        for phase in get_args(InstalledLoginPhase):
            for name in ("assets_session", "keyword_worker"):
                row = DiagnosticFrame.model_validate(
                    {
                        **old,
                        "stage": name,
                        "reason": reason,
                        "installed_login_phase": phase,
                    }
                )
                assert row.reason == reason and row.installed_login_phase == phase


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "stage", "error": None, "installed_login_phase": "callback_document"},
        {"stage": "source_review", "installed_login_phase": "callback_document"},
        {"stage": "export_worker", "installed_login_phase": "callback_document"},
        {"installed_login_phase": "private state/code/cookie"},
        {"installed_login_phase": "callback_document private"},
        {"installed_login_phase": 1},
        {"installed_login_phase": True},
        {"reason": "installed_redirect_ancestry private"},
        {"reason": "https://127.0.0.1/private?code=private"},
        {"installed_login_phase": "callback_document", "location": "private"},
        {"installed_login_phase": "callback_document", "cookie": "private"},
    ],
)
def test_installed_diagnostic_phase_and_extra_fields_refuse(
    changes: dict[str, object],
) -> None:
    from operator_ui_protocol import DiagnosticFrame

    with pytest.raises(ValidationError):
        DiagnosticFrame.model_validate(
            {"kind": "failure", "stage": "assets_session", "error": "RuntimeError", **changes}
        )


def _owned_channel(timeout: float = 10.0) -> Any:
    import ast
    import asyncio
    import json

    source = (
        Path(__file__).resolve().parents[3] / "scripts/isolation/operator_ui_acceptance.py"
    ).read_text()
    node = next(
        item
        for item in ast.parse(source).body
        if isinstance(item, ast.ClassDef) and item.name == "Channel"
    )
    namespace: dict[str, Any] = {
        "asyncio": asyncio,
        "json": json,
        "Any": Any,
        "RPC_DEADLINE": timeout,
        "print": lambda *args, **kwargs: None,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "owned-channel", "exec"), namespace)
    return namespace["Channel"]()


def test_owned_channel_admits_bounded_waiter_without_exceeding_active_cap() -> None:
    import asyncio

    async def run() -> None:
        channel = _owned_channel()
        tasks = [asyncio.create_task(channel.request({"kind": "control"})) for _ in range(9)]
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(channel.pending) == 8 and channel.waiting == 1 and channel.identifier == 8
        channel.pending[1].set_result({"kind": "reply"})
        for _ in range(8):
            await asyncio.sleep(0)
        assert len(channel.pending) == 8 and channel.waiting == 0 and channel.identifier == 9
        for future in list(channel.pending.values()):
            future.set_result({"kind": "reply"})
        await asyncio.gather(*tasks)
        assert not channel.pending and channel.capacity._value == 8 and channel.admitted == 0

    asyncio.run(run())


def test_owned_channel_refuses_excess_waiters_and_cleans_cancelled_admissions() -> None:
    import asyncio

    async def run() -> None:
        channel = _owned_channel()
        tasks = [asyncio.create_task(channel.request({"kind": "control"})) for _ in range(16)]
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(channel.pending) == 8 and channel.waiting == 8
        with pytest.raises(RuntimeError, match="admission cap"):
            await channel.request({"kind": "control"})
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert (
            not channel.pending
            and channel.waiting == 0
            and channel.capacity._value == 8
            and channel.admitted == 0
        )
        assert channel.identifier == 8

    asyncio.run(run())


def test_owned_channel_concurrent_timeouts_release_all_capacity() -> None:
    import asyncio

    async def run() -> None:
        channel = _owned_channel(0.03)
        tasks = [asyncio.create_task(channel.request({"kind": "control"})) for _ in range(9)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, TimeoutError) for result in results)
        assert (
            not channel.pending
            and channel.waiting == 0
            and channel.capacity._value == 8
            and channel.admitted == 0
        )
        # Each request has its own deadline; the ninth may acquire a freed slot.
        assert channel.identifier in {8, 9}

    asyncio.run(run())


def test_owned_channel_admission_timeout_does_not_allocate_identifier() -> None:
    async def run() -> None:
        channel = _owned_channel(0.03)
        for _ in range(8):
            await channel.capacity.acquire()
        try:
            with pytest.raises(TimeoutError):
                await channel.request({"kind": "control"})
            assert channel.identifier == 0 and not channel.retired
            assert not channel.pending and channel.waiting == 0 and channel.admitted == 0
            assert channel.capacity._value == 0
        finally:
            for _ in range(8):
                channel.capacity.release()
        assert channel.capacity._value == 8

    asyncio.run(run())


def test_owned_channel_reply_uses_remaining_admission_budget() -> None:
    from types import SimpleNamespace

    async def run() -> None:
        channel = _owned_channel(0.03)
        loop = asyncio.get_running_loop()
        clock = iter([100.0, 100.02])
        timeouts: list[float] = []

        async def wait_for(awaitable: Any, *, timeout: float) -> Any:
            timeouts.append(timeout)
            if len(timeouts) == 1:
                return await awaitable
            awaitable.cancel()
            raise TimeoutError

        channel.request.__func__.__globals__["asyncio"] = SimpleNamespace(
            get_running_loop=lambda: SimpleNamespace(
                time=lambda: next(clock), create_future=loop.create_future
            ),
            wait_for=wait_for,
        )
        with pytest.raises(TimeoutError):
            await channel.request({"kind": "control"})
        assert timeouts == pytest.approx([0.03, 0.01])
        assert channel.identifier == 1
        assert not channel.pending and channel.waiting == 0 and channel.admitted == 0
        assert channel.capacity._value == 8

    asyncio.run(run())


@pytest.mark.parametrize("failure", [None, "arbitrary private text", "net::ERR_FAILED"])
def test_route_fulfill_diagnostics_are_fixed_and_remain_failure(failure: object) -> None:
    from operator_ui_protocol import DiagnosticFrame, route_failure_reason

    reason = route_failure_reason(failure)
    assert reason == (
        "route_fulfill_failed" if failure == "net::ERR_FAILED" else "route_fulfill_unclassified"
    )
    diagnostic = DiagnosticFrame.model_validate(
        {
            "kind": "failure",
            "stage": "empty_contacts",
            "error": "Error",
            "reason": reason,
            "api_statuses": [200],
        }
    )
    assert diagnostic.kind == "failure"


@pytest.mark.parametrize(
    "states", [None, {"running": 1}, ["private arbitrary text"], [True], ["queued"] * 17]
)
def test_job_completion_diagnostics_refuse_unknown_or_unbounded_states(states: object) -> None:
    from operator_ui_protocol import completion_state_counts

    with pytest.raises(ValueError, match="Bounded known job states required"):
        completion_state_counts(states)


def test_job_completion_diagnostics_are_only_fixed_counts() -> None:
    from operator_ui_protocol import completion_state_counts

    assert completion_state_counts([]) == {}
    assert completion_state_counts(["running", "queued", "running"]) == {
        "queued": 1,
        "running": 2,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "unknown"},
        {"state": "private text"},
        {"reason": "secret"},
        {"attempts": True},
        {"attempts": 4},
        {"lease_live": 1},
        {"published": None},
        {"url": "private"},
    ],
)
def test_completion_units_refuse_unknown_values_and_extra_content(
    change: dict[str, object],
) -> None:
    from operator_ui_protocol import completion_unit_counts

    row = {
        "kind": "article",
        "state": "running",
        "reason": "leased",
        "attempts": 1,
        "lease_live": True,
        "published": True,
        **change,
    }
    with pytest.raises(ValueError):
        completion_unit_counts([row])


def test_completion_units_only_count_closed_phase_categories() -> None:
    from operator_ui_protocol import completion_unit_counts

    row = {
        "kind": "article",
        "state": "running",
        "reason": "leased",
        "attempts": 1,
        "lease_live": True,
        "published": True,
    }
    assert completion_unit_counts([row, row]) == {
        "article:running:leased:attempts=1:lease_live=1:published=1": 2,
    }
    assert completion_unit_counts([]) == {}
    with pytest.raises(ValueError):
        completion_unit_counts([row] * 33)


def test_owned_failure_log_matching_never_returns_arbitrary_content() -> None:
    from operator_ui_protocol import completion_failure_classes

    assert completion_failure_classes(b"private text\nProgrammingError\nRevisionConflict") == [
        "ProgrammingError",
        "RevisionConflict",
    ]
    assert completion_failure_classes(b"private arbitrary error") == []
    with pytest.raises(ValueError):
        completion_failure_classes(b"x" * 65537)


def _owned_api_headers() -> tuple[Any, type[Exception]]:
    import ast
    from collections.abc import Callable

    from operator_ui_protocol import route_headers_reason

    source = (
        Path(__file__).resolve().parents[3] / "scripts/isolation/operator_ui_acceptance.py"
    ).read_text()
    node = next(
        item
        for item in ast.parse(source).body
        if isinstance(item, ast.AsyncFunctionDef) and item.name == "api_headers"
    )

    class DriverError(Exception):
        pass

    namespace: dict[str, Any] = {
        "Request": object,
        "Callable": Callable,
        "Error": DriverError,
        "HEADERS": {"cookie", "origin"},
        "route_headers_reason": route_headers_reason,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "owned-api-headers", "exec"), namespace)
    return namespace["api_headers"], DriverError


@pytest.mark.parametrize("driver_error", [False, True])
@pytest.mark.parametrize("failure", [None, "net::ERR_ABORTED"])
def test_actual_header_boundary_reports_fixed_failure_and_rethrows(
    driver_error: bool, failure: str | None
) -> None:
    function, error_type = _owned_api_headers()
    errors: list[tuple[str, str]] = []

    class Request:
        async def all_headers(self) -> dict[str, str]:
            raise (error_type if driver_error else RuntimeError)("private detail never reported")

    incoming = Request()
    incoming.failure = failure  # type: ignore[attr-defined]
    with pytest.raises(error_type if driver_error else RuntimeError):
        asyncio.run(function(incoming, lambda error, reason: errors.append((error, reason))))
    assert errors == [
        (
            "Error" if driver_error else "RuntimeError",
            "route_headers_aborted" if failure else "route_headers_unclassified",
        )
    ]
    from operator_ui_protocol import DiagnosticFrame

    assert (
        DiagnosticFrame.model_validate(
            {
                "kind": "failure",
                "stage": "url_worker",
                "error": errors[0][0],
                "reason": errors[0][1],
            }
        ).kind
        == "failure"
    )


def test_actual_headers_keep_sensitive_allowlist_without_fallback() -> None:
    function, _ = _owned_api_headers()
    errors: list[tuple[str, str]] = []

    class Request:
        async def all_headers(self) -> dict[str, str]:
            return {
                "cookie": "synthetic=test",
                "origin": "https://app.example.test",
                "unknown": "excluded",
            }

    assert asyncio.run(
        function(Request(), lambda error, reason: errors.append((error, reason)))
    ) == {
        "cookie": "synthetic=test",
        "origin": "https://app.example.test",
    }
    assert errors == []


@pytest.mark.parametrize(
    "error,expected",
    [
        (RuntimeError("UI diagnostic concurrency/request cap exceeded"), "rpc_capacity"),
        (
            RuntimeError("Request.all_headers: UI diagnostic concurrency/request cap exceeded"),
            "rpc_capacity",
        ),
        (
            RuntimeError("Request.all_headers: await wasn't used with future"),
            "route_headers_future_state",
        ),
        (RuntimeError("cannot reuse already awaited coroutine"), "route_headers_future_state"),
        (RuntimeError("Request.all_headers: Event loop is closed"), "route_headers_loop_state"),
        (RuntimeError("dictionary changed size during iteration"), "route_headers_iteration_state"),
        (RuntimeError("unrecognized private information"), "route_headers_unclassified"),
        (Exception("UI diagnostic concurrency/request cap exceeded"), "route_headers_unclassified"),
    ],
)
def test_header_runtime_categories_are_closed_diagnostics_never_success(
    error: Exception, expected: str
) -> None:
    from operator_ui_protocol import DiagnosticFrame, route_headers_reason

    reason = route_headers_reason(None, error)
    assert reason == expected
    assert (
        DiagnosticFrame.model_validate(
            {"kind": "failure", "stage": "url_worker", "error": "RuntimeError", "reason": reason}
        ).kind
        == "failure"
    )
    assert "private" not in reason


def test_completion_queue_counts_return_no_identifier_or_task_content() -> None:
    from operator_ui_protocol import completion_queue_counts

    assert completion_queue_counts(3, 1) == {"ready": 3, "consumers": 1}
    assert completion_queue_counts(0, 0) == {"ready": 0, "consumers": 0}


@pytest.mark.parametrize("ready,consumers", [(True, 1), (-1, 1), (10001, 1), (3, True), (3, 17)])
def test_completion_queue_counts_refuse_unbounded_or_coerced_values(
    ready: object, consumers: object
) -> None:
    from operator_ui_protocol import completion_queue_counts

    with pytest.raises(ValueError):
        completion_queue_counts(ready, consumers)


def test_owned_queue_probe_uses_whole_process_timeout_and_fixed_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    import operator_queue_probe as probe

    observed: dict[str, object] = {}

    def run(*args: object, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        observed.update(kwargs)
        return subprocess.CompletedProcess(["owned-probe"], 0, b'{"ready":3,"consumers":1}')

    monkeypatch.setattr(subprocess, "run", run)
    assert probe.observe("pyamqp://synthetic@127.0.0.1:5672//", "em-fixture-owned") == {
        "ready": 3,
        "consumers": 1,
    }
    assert observed["timeout"] == 0.5
    assert observed["stderr"] == subprocess.DEVNULL
    assert observed["check"] is False


@pytest.mark.parametrize("failure", ["timeout", "unavailable", "invalid", "oversize"])
def test_owned_queue_probe_unavailability_never_becomes_completion(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    import subprocess

    import operator_queue_probe as probe

    def run(*args: object, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if failure == "timeout":
            raise subprocess.TimeoutExpired("fixed-owned-command", 0.5)
        if failure == "unavailable":
            return subprocess.CompletedProcess(["owned-probe"], 1, b"")
        return subprocess.CompletedProcess(
            ["owned-probe"], 0, b"x" * 129 if failure == "oversize" else b"{}"
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert probe.observe("pyamqp://synthetic@127.0.0.1:5672//", "em-fixture-owned") is None


def test_owned_queue_probe_actual_stalled_child_is_terminated_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess
    import sys
    import time

    import operator_queue_probe as probe

    actual_run = subprocess.run

    def stalled(*args: object, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return actual_run([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)

    monkeypatch.setattr(subprocess, "run", stalled)
    started = time.monotonic()
    assert probe.observe("pyamqp://synthetic@127.0.0.1:5672//", "em-fixture-owned") is None
    assert time.monotonic() - started < 2


def test_header_classifier_handles_actual_pinned_internal_api_prefix() -> None:
    from operator_ui_protocol import route_headers_reason
    from playwright._impl._connection import _attach_api_call_information
    from playwright._impl._errors import rewrite_error

    stack = _attach_api_call_information(
        {"frames": [], "apiName": "Request.all_headers", "title": None}, True, None
    )
    assert stack["apiName"] == ""
    original = RuntimeError("UI diagnostic concurrency/request cap exceeded")
    wrapped = rewrite_error(original, f"{stack['apiName']}: {original}")
    assert type(wrapped) is RuntimeError
    assert route_headers_reason(None, wrapped) == "rpc_capacity"


def test_header_classifier_does_not_strip_nested_or_unknown_prefixes() -> None:
    from operator_ui_protocol import route_headers_reason

    for prefix in (": : ", "Unknown.api: ", "Request.all_headers: : "):
        assert (
            route_headers_reason(
                None, RuntimeError(prefix + "UI diagnostic concurrency/request cap exceeded")
            )
            == "route_headers_unclassified"
        )


def test_owned_channel_request_limit_has_distinct_fixed_failure() -> None:
    from operator_ui_protocol import failure_reason, route_headers_reason

    async def run() -> None:
        channel = _owned_channel()
        channel.identifier = 512
        with pytest.raises(RuntimeError, match="^UI diagnostic request cap exceeded$") as error:
            await channel.request({"kind": "control"})
        assert failure_reason(error.value) == "rpc_request_capacity"
        assert (
            route_headers_reason(None, RuntimeError(": " + str(error.value)))
            == "rpc_request_capacity"
        )
        assert channel.identifier == 512 and channel.admitted == 0 and not channel.pending

    asyncio.run(run())


def test_owned_channel_sixteen_admitted_limit_has_distinct_fixed_failure() -> None:
    from operator_ui_protocol import failure_reason, route_headers_reason

    async def run() -> None:
        channel = _owned_channel(timeout=1)
        tasks = [asyncio.create_task(channel.request({"kind": "control"})) for _ in range(16)]
        for _ in range(8):
            await asyncio.sleep(0)
        assert channel.admitted == 16 and len(channel.pending) == 8 and channel.waiting == 8
        with pytest.raises(RuntimeError, match="^UI diagnostic admission cap exceeded$") as error:
            await channel.request({"kind": "control"})
        assert failure_reason(error.value) == "rpc_admission_capacity"
        assert (
            route_headers_reason(None, RuntimeError(": " + str(error.value)))
            == "rpc_admission_capacity"
        )
        assert channel.admitted == 16 and channel.identifier == 8
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert not channel.pending and channel.admitted == 0 and channel.capacity._value == 8

    asyncio.run(run())


def test_outcome_investigation_phases_are_closed_failure_only_categories() -> None:
    """Localize assertions without publishing DOM, records, URLs or IDs."""
    import ast

    from operator_ui_protocol import OUTCOME_PHASES, DiagnosticFrame

    root = Path(__file__).resolve().parents[3]
    source = (root / "scripts/isolation/operator_ui_acceptance.py").read_text()
    module = ast.parse(source)
    observed = {
        call.args[0].value
        for call in ast.walk(module)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id in {"checkpoint", "outcome_checkpoint"}
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
        and call.args[0].value.startswith("outcomes_")
    }
    assert observed == set(OUTCOME_PHASES) and len(observed) == 29
    old = {"kind": "failure", "stage": "url_worker", "error": "AssertionError"}
    assert DiagnosticFrame.model_validate(old).outcome_phase is None
    for phase in OUTCOME_PHASES:
        frame = DiagnosticFrame.model_validate({**old, "outcome_phase": phase})
        assert frame.outcome_phase == phase and frame.stage == "url_worker"
        assert frame.api_statuses == [] and frame.reason == "unknown"
        for changes in (
            {"kind": "stage", "error": None},
            {"stage": "keyword_worker"},
            {"stage": phase},
            {"outcome_phase": phase + ":private-record"},
            {"outcome_phase": [phase]},
            {"body": "private"},
        ):
            with pytest.raises(ValidationError):
                DiagnosticFrame.model_validate({**old, "outcome_phase": phase, **changes})
    helper = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "authored_outcome_paging"
    )
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"
        for node in ast.walk(helper)
    )


def test_outcome_failure_phase_preserves_stage_identity_cap_and_reset() -> None:
    import ast

    root = Path(__file__).resolve().parents[3]
    module = ast.parse((root / "scripts/isolation/operator_ui_acceptance.py").read_text())
    callbacks = {
        node.name: ast.unparse(node)
        for node in ast.walk(module)
        if isinstance(node, ast.FunctionDef) and node.name in {"checkpoint", "outcome_checkpoint"}
    }
    code = callbacks["outcome_checkpoint"]
    assert "stage != 'url_worker'" in code and "value not in OUTCOME_PHASES" in code
    assert "outcome_phase = value" in code and "stage = value" not in code and "print(" not in code
    assert "outcome_phase = None" in callbacks["checkpoint"]
    host = (root / "scripts/isolation/run_operator_ui_acceptance.py").read_text()
    assert "if stages > 32:" in host and "if diagnostic.stage != stage:" in host
    assert '"; outcome phase=" + diagnostic.outcome_phase' in host


def test_native_outcome_modal_checks_controls_without_forcing_dom_focus_wrap() -> None:
    import ast

    root = Path(__file__).resolve().parents[3]
    source = (root / "scripts/isolation/operator_ui_acceptance.py").read_text()
    start = source.index('checkpoint("outcomes_modal_tab")')
    end = source.index('checkpoint("outcomes_quality_pending")', start)
    segment = source[start:end]
    assert "range(6)" not in segment and "document.activeElement" not in segment
    assert segment.count("node.matches(':modal')") == 2
    assert segment.count("await expect(close).to_be_focused()") == 2
    assert 'name="Refresh article observation"' in segment
    keys = [
        call.args[0].value
        for call in ast.walk(ast.parse("async def check():\n        " + segment))
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "press"
        and call.args
        and isinstance(call.args[0], ast.Constant)
    ]
    assert keys == ["Tab", "Shift+Tab"]


def test_scoped_association_select_uses_unique_label_prefix_and_exact_values() -> None:
    import ast

    root = Path(__file__).resolve().parents[3]
    module = ast.parse((root / "scripts/isolation/operator_ui_acceptance.py").read_text())
    helper = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "authored_outcome_paging"
    )
    checks = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "to_have_value"
        and "Association state" in ast.unparse(node.func.value)
    ]
    assert len(checks) == 4
    assert [ast.literal_eval(check.args[0]) for check in checks] == [
        "accepted",
        "needs_review",
        "accepted",
        "needs_review",
    ]
    for check in checks:
        assert isinstance(check.func, ast.Attribute)
        # No .first/.nth shortcut: Playwright's assertion still requires one match.
        assert ast.unparse(check.func.value) == (
            "expect(page.get_by_label(re.compile('^Association state')))"
        )


def test_late_organization_hold_follows_ready_first_page_and_targets_next_page() -> None:
    import ast

    root = Path(__file__).resolve().parents[3]
    source = (root / "scripts/isolation/operator_ui_acceptance.py").read_text()
    helper = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "authored_outcome_paging"
    )
    body = next(node for node in helper.body if isinstance(node, ast.Try)).body
    statements = [ast.unparse(node) for node in body]
    marker = statements.index("checkpoint('outcomes_late_organization')")
    assert "name='Jobs'" in statements[marker - 3]
    assert "to_contain_text('Page 1: 25 article outcomes')" in statements[marker - 2]
    assert "name='Next article outcome page'" in statements[marker - 1]
    assert statements[marker - 1].endswith(".to_be_enabled()")
    following = statements[marker + 1 :]
    assert following.index("held_offset = None") < following.index("hold = True")
    held_assertion = following.index("assert held_offset == 25")
    assert "requested.wait()" in following[held_assertion - 1]
    assert following.index("hold = True") < held_assertion
    code = ast.unparse(helper)
    assert "if hold and offset == 25:" in code
    assert code.count("assert held_offset == 25") == 2


def test_contact_request_generation_regressions_use_actual_hook_and_held_responses() -> None:
    """Wiring check only; the actual browser matrix still requires hosted execution."""
    import ast

    root = Path(__file__).resolve().parents[3]
    source = (root / "scripts/isolation/operator_ui_acceptance.py").read_text()
    module = ast.parse(source)
    helper = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "authored_contact_request_ownership"
    )
    code = ast.unparse(helper)
    for required in (
        "for seed_error in (False, True):",
        "for disabled_interval in (False, True):",
        "phase = 'held'",
        "changed.wait()",
        "returned.wait()",
        "release_returned.wait()",
        "release_changed.wait()",
        "assert changed_requests == 0",
        "assert changed_requests == 1",
        "expect(empty).not_to_be_visible()",
        "expect(error).not_to_be_visible()",
        "expect(loading).to_be_visible()",
        "await page.unroute(pattern, contacts)",
    ):
        assert required in code
    assert "await authored_contact_request_ownership(page, outcome_checkpoint)" in source
    hook = (root / "apps/web/src/ui.tsx").read_text()
    assert "useMemo(() => ({ scope, path, revision }), [scope, path, revision])" in hook
    assert "}, [request])" in hook and "owned?.request !== request" in hook
    assert "setOwned({ request, resource:" in hook
    assert "setOwned(current => ({ request, resource:" in hook

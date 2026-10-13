"""Pure diagnostic grammar and actual in-process ASGI transport mechanics."""

import asyncio
import base64
from collections.abc import AsyncIterator
from pathlib import Path

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


def test_owned_pipe_failure_is_observed_before_guest_waits_for_host_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess
    import sys

    import run_operator_ui_acceptance as host

    original = subprocess.Popen

    def owned_python_pipe(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        return original(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdin.readline(); "
                'print(\'{"kind":"stage","stage":"assets_session"}\',flush=True); '
                'print(\'{"kind":"failure","stage":"assets_session",'
                '"error":"TimeoutError","api_statuses":[200]}\',flush=True); '
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
    ):
        host.conversation(
            "owned-pipe-only", FastAPI(), {}, lambda action: None, lambda request: False
        )


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

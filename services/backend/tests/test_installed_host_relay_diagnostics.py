"""Closed host-only ReadTimeout evidence; no browser, database or network access."""

import ast
import asyncio
import hashlib
import json
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args

import httpx
import installed_operator_relay as relay
import pytest
from fastapi import FastAPI
from test_service_api_entrypoint import certificate

API = "https://127.0.0.1:4444"
ISSUER = "https://127.0.0.1:4445"
ASSETS = {"index.html": "a" * 64, "assets/index-12345678.js": "b" * 64}
ORGANIZATION = "abcdef00-1234-5678-9abc-0123456789ab"
RESOURCE = "01234567-89ab-cdef-0123-456789abcdef"
SCOPE = f"/api/v1/organizations/{ORGANIZATION}"


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/api/v1/auth/start", "auth"),
        ("/api/v1/auth/session", "auth"),
        ("/api/v1/auth/logout", "auth"),
        ("/auth/complete?code=private&state=private", "callback_document"),
        ("/", "static"),
        ("/assets/index-12345678.js", "static"),
        (SCOPE + "/jobs", "job_list"),
        (SCOPE + f"/jobs/{RESOURCE}", "job_detail"),
        (SCOPE + f"/jobs/{RESOURCE}/progress", "job_progress"),
        (SCOPE + f"/jobs/{RESOURCE}/progress/items", "job_items"),
        (SCOPE + f"/jobs/{RESOURCE}/events?cursor=private", "job_events"),
        (SCOPE + "/exports", "export_metadata"),
        (SCOPE + f"/exports/{RESOURCE}", "export_metadata"),
        (SCOPE + f"/exports/{RESOURCE}/download?token=private", "export_download"),
        (SCOPE + f"/exports/{RESOURCE}/download/extra", "other_api"),
        (SCOPE + f"/jobs/{RESOURCE}/progress/items/extra", "other_api"),
        (SCOPE + "/jobs/private", "other_api"),
        (SCOPE + f"/jobs/{RESOURCE.upper()}/events", "other_api"),
        (f"/api/v1/organizations/{ORGANIZATION.upper()}/jobs", "other_api"),
        ("/api/v1/private?cookie=private", "other_api"),
    ],
)
def test_validated_routes_emit_only_authored_categories(path: str, expected: str) -> None:
    target = API + path
    offset = 0 if expected in {"static", "callback_document"} else None
    validated, *_ = relay.validate_target(envelope(target, offset), API, ISSUER, ASSETS)
    assert relay.diagnostic_route(validated, API, ISSUER, ASSETS) == expected


def test_issuer_and_foreign_origins_are_never_mislabelled_as_api() -> None:
    target = ISSUER + "/authorize?code=private&state=private"
    validated, *_ = relay.validate_target(envelope(target), API, ISSUER, ASSETS)
    assert relay.diagnostic_route(validated, API, ISSUER, ASSETS) == "issuer_authorize"
    for target in (ISSUER + "/token", "https://private.example/api/v1/auth/session"):
        with pytest.raises(ValueError, match="Validated installed relay target required"):
            relay.diagnostic_route(target, API, ISSUER, ASSETS)


def test_diagnostic_has_exact_fixed_enums() -> None:
    assert get_args(relay.RelayRoute) == (
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
    )
    assert get_args(relay.RelayPhase) == ("client_open", "response_enter", "response_open")


def envelope(target: str, offset: int | None = None) -> dict[str, Any]:
    return {"target": target, "method": "GET", "headers": {}, "body": "", "offset": offset}


@pytest.fixture(scope="module")
def ca(tmp_path_factory: pytest.TempPathFactory) -> Path:
    public, _ = certificate(tmp_path_factory.mktemp("relay-ca"))
    return public


@pytest.fixture
def app(ca: Path) -> FastAPI:
    return relay.application(API, ISSUER, ca, ASSETS, [])


def inject_client(
    monkeypatch: pytest.MonkeyPatch, point: str, failure: BaseException | None
) -> list[tuple[str, BaseException | None]]:
    """Replace this helper's module reference, never global httpx.AsyncClient."""
    trace: list[tuple[str, BaseException | None]] = []

    def visit(name: str, error: BaseException | None = None) -> None:
        trace.append((name, error))
        if point == name and failure is not None:
            raise failure

    class Response:
        headers = httpx.Headers({"content-type": "application/json"})
        status_code = 200

        async def aiter_bytes(self) -> AsyncIterator[bytes]:
            visit("body")
            yield b"{}"

    class Stream:
        async def __aenter__(self) -> Response:
            visit("response_enter")
            return Response()

        async def __aexit__(self, kind: Any, error: Any, traceback: Any) -> None:
            visit("response_close", error)

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            assert set(kwargs) == {"verify", "trust_env", "follow_redirects", "timeout"}
            assert kwargs["verify"].check_hostname
            assert kwargs["trust_env"] is False
            assert kwargs["follow_redirects"] is False
            assert kwargs["timeout"] == 4
            visit("client_create")

        async def __aenter__(self) -> "Client":
            visit("client_enter")
            return self

        async def __aexit__(self, kind: Any, error: Any, traceback: Any) -> None:
            visit("client_close", error)

        def stream(self, method: str, target: str, **kwargs: Any) -> Stream:
            assert method == "GET" and target == API + "/api/v1/auth/session"
            assert kwargs == {"headers": {}, "content": ""}
            visit("stream_create")
            return Stream()

    monkeypatch.setattr(
        relay, "httpx", SimpleNamespace(AsyncClient=Client, ReadTimeout=httpx.ReadTimeout)
    )
    return trace


async def request(app: FastAPI, target: str = API + "/api/v1/auth/session") -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://owned"
    ) as client:
        return await client.post("/api/v1/installed-relay", json=envelope(target))


@pytest.mark.parametrize(
    "point,phase,steps",
    [
        ("client_create", "client_open", ["client_create"]),
        ("client_enter", "client_open", ["client_create", "client_enter"]),
        (
            "stream_create",
            "response_enter",
            ["client_create", "client_enter", "stream_create", "client_close"],
        ),
        (
            "response_enter",
            "response_enter",
            ["client_create", "client_enter", "stream_create", "response_enter", "client_close"],
        ),
        (
            "body",
            "response_open",
            [
                "client_create",
                "client_enter",
                "stream_create",
                "response_enter",
                "body",
                "response_close",
                "client_close",
            ],
        ),
        (
            "response_close",
            "response_open",
            [
                "client_create",
                "client_enter",
                "stream_create",
                "response_enter",
                "body",
                "response_close",
                "client_close",
            ],
        ),
        (
            "client_close",
            "response_open",
            [
                "client_create",
                "client_enter",
                "stream_create",
                "response_enter",
                "body",
                "response_close",
                "client_close",
            ],
        ),
    ],
)
def test_actual_handler_preserves_exception_and_context_unwind(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    point: str,
    phase: str,
    steps: list[str],
) -> None:
    failure = httpx.ReadTimeout(
        "private URL/state/cookie", request=httpx.Request("GET", API + "/private")
    )
    trace = inject_client(monkeypatch, point, failure)
    with pytest.raises(httpx.ReadTimeout) as caught:
        asyncio.run(request(app))
    assert caught.value is failure
    assert [name for name, _ in trace] == steps
    if point == "body":
        assert trace[-2:] == [("response_close", failure), ("client_close", failure)]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "diagnostic": "installed-relay-failure",
        "route": "auth",
        "last_phase": phase,
        "error": "read_timeout",
    }
    assert "private" not in captured.err and API not in captured.err


class ReadTimeoutSubclass(httpx.ReadTimeout):
    pass


@pytest.mark.parametrize(
    "failure",
    [
        ReadTimeoutSubclass("private"),
        httpx.ConnectTimeout("private"),
        httpx.ReadError("private"),
        RuntimeError("private"),
        TimeoutError("private"),
        ValueError("private"),
        asyncio.CancelledError(),
    ],
)
def test_other_errors_and_cancellation_produce_no_record(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: BaseException,
) -> None:
    trace = inject_client(monkeypatch, "body", failure)
    with pytest.raises(type(failure)) as caught:
        asyncio.run(request(app))
    assert caught.value is failure
    assert trace[-2:] == [("response_close", failure), ("client_close", failure)]
    assert capsys.readouterr() == ("", "")


def test_success_keeps_wire_and_cleanup_without_diagnostic(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    trace = inject_client(monkeypatch, "none", None)
    result = asyncio.run(request(app))
    assert result.json() == {
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": "e30=",
    }
    assert trace[-2:] == [("response_close", None), ("client_close", None)]
    assert capsys.readouterr() == ("", "")


def test_invalid_target_cannot_reach_client_or_diagnostic(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    trace = inject_client(monkeypatch, "client_create", httpx.ReadTimeout("private"))
    with pytest.raises(ValueError, match="Exact ephemeral loopback origin required"):
        asyncio.run(request(app, "https://private.example/api/v1/auth/session"))
    assert trace == []
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("operation", ["serialize", "output"])
@pytest.mark.parametrize("secondary", [RuntimeError("private"), asyncio.CancelledError()])
def test_diagnostic_failures_preserve_primary_and_never_retry_output(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    operation: str,
    secondary: BaseException,
) -> None:
    primary = httpx.ReadTimeout("private primary")
    inject_client(monkeypatch, "body", primary)
    attempts = []

    def refuse(*args: Any, **kwargs: Any) -> None:
        attempts.append(1)
        raise secondary

    if operation == "serialize":
        monkeypatch.setattr(relay, "json", SimpleNamespace(loads=json.loads, dumps=refuse))
    else:
        monkeypatch.setattr(relay, "print", refuse, raising=False)
    for _ in range(2):
        with pytest.raises(httpx.ReadTimeout) as caught:
            asyncio.run(request(app))
        assert caught.value is primary
    assert attempts == [1]
    assert capsys.readouterr() == ("", "")


def test_concurrent_failures_latch_one_complete_tuple_before_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    diagnostics = relay.RelayDiagnostics()
    pairs: list[tuple[relay.RelayRoute, relay.RelayPhase]] = [
        ("job_events", "response_open"),
        ("auth", "client_open"),
        ("export_download", "response_enter"),
        ("static", "response_open"),
    ]
    barrier = threading.Barrier(len(pairs))
    serialize = json.dumps
    records = []

    def check_latched(value: dict[str, str], **kwargs: Any) -> str:
        assert diagnostics.first == (value["route"], value["last_phase"], value["error"])
        records.append(value)
        return serialize(value, **kwargs)

    monkeypatch.setattr(relay, "json", SimpleNamespace(dumps=check_latched))

    def capture(pair: tuple[relay.RelayRoute, relay.RelayPhase]) -> None:
        barrier.wait(timeout=3)
        diagnostics.capture(httpx.ReadTimeout("private"), *pair)

    with ThreadPoolExecutor(max_workers=len(pairs)) as pool:
        futures = [pool.submit(capture, pair) for pair in pairs]
        for future in futures:
            future.result(timeout=3)
    assert len(records) == 1
    assert diagnostics.first is not None and diagnostics.first[:2] in pairs
    first = diagnostics.first
    diagnostics.capture(httpx.ReadTimeout("later private"), "other_api", "client_open")
    assert diagnostics.first is first
    captured = capsys.readouterr()
    assert captured.out == "" and len(captured.err.splitlines()) == 1
    assert json.loads(captured.err) == records[0]


class StringSubclass(str):
    pass


@pytest.mark.parametrize("field", ["route", "phase"])
@pytest.mark.parametrize(
    "value",
    ["private cookie/state", 1, None, StringSubclass("auth"), StringSubclass("response_open")],
)
def test_record_rejects_nonfinite_values_without_output(
    capsys: pytest.CaptureFixture[str],
    field: str,
    value: Any,
) -> None:
    diagnostics = relay.RelayDiagnostics()
    route: Any = value if field == "route" else "auth"
    phase: Any = value if field == "phase" else "response_open"
    with pytest.raises(ValueError, match="Closed installed relay diagnostic required"):
        diagnostics.capture(httpx.ReadTimeout("private"), route, phase)
    assert diagnostics.first is None
    assert capsys.readouterr() == ("", "")


def test_concurrent_actual_handlers_keep_their_own_route_and_phase(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def exercise() -> None:
        ready = [asyncio.Event(), asyncio.Event()]
        failures = [httpx.ReadTimeout("private headers"), httpx.ReadTimeout("private body")]

        class Response:
            headers = httpx.Headers({"content-type": "text/event-stream"})
            status_code = 200

            async def aiter_bytes(self) -> AsyncIterator[bytes]:
                ready[1].set()
                await ready[0].wait()
                raise failures[1]
                yield b""  # pragma: no cover -- defines the authored async iterator.

        class Client:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "Client":
                return self

            async def __aexit__(self, *args: Any) -> None:
                pass

            @asynccontextmanager
            async def stream(
                self, method: str, target: str, **kwargs: Any
            ) -> AsyncIterator[Response]:
                if target.endswith("/session"):
                    ready[0].set()
                    await ready[1].wait()
                    raise failures[0]
                yield Response()

        monkeypatch.setattr(
            relay, "httpx", SimpleNamespace(AsyncClient=Client, ReadTimeout=httpx.ReadTimeout)
        )
        results = await asyncio.gather(
            request(app),
            request(app, API + SCOPE + f"/jobs/{RESOURCE}/events"),
            return_exceptions=True,
        )
        assert all(result is failure for result, failure in zip(results, failures, strict=True))

    asyncio.run(exercise())
    captured = capsys.readouterr()
    assert captured.out == "" and len(captured.err.splitlines()) == 1
    record = json.loads(captured.err)
    assert (record["route"], record["last_phase"]) in {
        ("auth", "response_enter"),
        ("job_events", "response_open"),
    }
    assert set(record) == {"diagnostic", "route", "last_phase", "error"}
    assert record["error"] == "read_timeout" and "private" not in captured.err


def test_exact_read_timeout_never_formats_exception_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Secret:
        def __str__(self) -> str:
            raise AssertionError("Exception data must not be inspected")

        def __repr__(self) -> str:
            raise AssertionError("Exception data must not be inspected")

    error = httpx.ReadTimeout("unused")
    error.args = (Secret(),)
    diagnostics = relay.RelayDiagnostics()
    diagnostics.capture(error, "job_events", "response_open")
    assert json.loads(capsys.readouterr().err)["error"] == "read_timeout"


def test_original_http_transaction_ast_and_awaits_are_unchanged() -> None:
    source = ast.parse(Path(relay.__file__).read_text())
    handler = next(
        node
        for node in ast.walk(source)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "relay"
    )
    transaction = next(
        node
        for node in ast.walk(handler)
        if isinstance(node, ast.AsyncWith)
        and ast.unparse(node.items[0].context_expr).startswith("httpx.AsyncClient(")
    )
    # Remove only the two closed, synchronous phase assignments from the original transaction.
    transaction.body = [
        node
        for node in transaction.body
        if not (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "last_phase"
                for target in node.targets
            )
        )
    ]
    stream = transaction.body[0]
    assert isinstance(stream, ast.AsyncWith)
    stream.body = [
        node
        for node in stream.body
        if not (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "last_phase"
                for target in node.targets
            )
        )
    ]
    normalized = ast.dump(transaction, include_attributes=False)
    assert (
        hashlib.sha256(normalized.encode()).hexdigest()
        == "c2ad1559369731f10711508240a1b3d6aab8f83e74d284b00ada42a3d5438a8d"
    )
    assert [
        ast.unparse(node.value) for node in ast.walk(handler) if isinstance(node, ast.Await)
    ] == ["request.body()"]
    assert len([node for node in ast.walk(handler) if isinstance(node, ast.AsyncWith)]) == 3
    assert len([node for node in ast.walk(handler) if isinstance(node, ast.AsyncFor)]) == 1

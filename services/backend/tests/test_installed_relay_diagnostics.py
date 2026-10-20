"""Closed request-local relay diagnostics; no browser or external transport."""

import ast
import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import pytest
from installed_operator_redirects import InstalledDiagnostics, installed_relay_reason
from operator_ui_protocol import ORIGIN, DiagnosticFrame, InstalledReason
from pydantic import ValidationError


@pytest.mark.parametrize(
    "message,reason",
    [
        ("UI diagnostic request cap exceeded", "installed_relay_request_capacity"),
        ("UI diagnostic admission cap exceeded", "installed_relay_admission_capacity"),
        ("UI diagnostic request too large", "installed_relay_request_size"),
    ],
)
def test_only_exact_owned_runtime_guard_messages_get_closed_reasons(
    message: str, reason: str
) -> None:
    error = RuntimeError(message)
    assert installed_relay_reason(error) == reason
    fixed = InstalledDiagnostics().capture(error, reason, None)
    assert fixed == {"error": "RuntimeError", "reason": reason}
    frame = DiagnosticFrame.model_validate({"kind": "failure", "stage": "keyword_worker", **fixed})
    assert frame.reason == reason and frame.installed_login_phase is None
    assert message not in json.dumps(fixed)


class OtherRuntimeError(RuntimeError):
    pass


class OtherString(str):
    pass


@pytest.mark.parametrize(
    "error",
    [
        OtherRuntimeError("UI diagnostic request cap exceeded"),
        ValueError("UI diagnostic request cap exceeded"),
        RuntimeError(OtherString("UI diagnostic request cap exceeded")),
        RuntimeError("UI diagnostic request cap exceeded", "private"),
        RuntimeError("UI diagnostic concurrency/request cap exceeded"),
        RuntimeError("Request.all_headers: UI diagnostic request cap exceeded"),
        RuntimeError(": UI diagnostic admission cap exceeded"),
        RuntimeError("UI diagnostic request too large private cookie/code/state"),
        RuntimeError("private https://example.test/?state=private"),
        RuntimeError({"cookie": "private"}),
        RuntimeError(),
    ],
)
def test_unknown_decorated_secret_or_subclass_exception_is_not_classified(error: Exception) -> None:
    assert installed_relay_reason(error) == "installed_route_relay"
    fixed = InstalledDiagnostics().capture(error, installed_relay_reason(error), None)
    assert "private" not in json.dumps(fixed)
    assert "example.test" not in json.dumps(fixed)


def owned_exchange(channel: Any) -> Any:
    """Compile the actual nested helper, keeping its real per-call wiring."""
    root = Path(__file__).resolve().parents[3]
    source = (root / "scripts/isolation/installed_operator_browser.py").read_text()
    node = next(
        item
        for item in ast.walk(ast.parse(source))
        if isinstance(item, ast.AsyncFunctionDef) and item.name == "exchange"
    )
    namespace: dict[str, Any] = {
        "channel": channel,
        "Any": Any,
        "InstalledReason": InstalledReason,
        "ORIGIN": ORIGIN,
        "json": json,
        "base64": base64,
        "installed_relay_reason": installed_relay_reason,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "owned-exchange", "exec"), namespace)
    return namespace["exchange"]


def test_concurrent_requests_keep_exact_exception_and_local_reason_with_first_capture() -> None:
    async def exercise() -> None:
        ready = [asyncio.Event(), asyncio.Event()]
        failures = [
            RuntimeError("UI diagnostic admission cap exceeded"),
            RuntimeError("private unclassified"),
        ]

        class Channel:
            async def request(self, message: dict[str, Any]) -> dict[str, Any]:
                index = json.loads(message["body"])["index"]
                await ready[index].wait()
                raise failures[index]

        exchange = owned_exchange(Channel())
        operations: list[list[InstalledReason]] = [
            ["installed_route_relay"],
            ["installed_route_relay"],
        ]
        tasks = [
            asyncio.create_task(exchange({"index": index}, operations[index])) for index in range(2)
        ]
        diagnostics = InstalledDiagnostics()
        for index in (1, 0):
            ready[index].set()
            with pytest.raises(RuntimeError) as caught:
                await tasks[index]
            assert caught.value is failures[index]
            diagnostics.capture(caught.value, operations[index][0], None)
        assert operations == [["installed_relay_admission_capacity"], ["installed_route_relay"]]
        assert diagnostics.first is not None
        assert diagnostics.first.reason == "installed_route_relay"

    asyncio.run(exercise())


@pytest.mark.parametrize("status", [200, 400, 422, 500])
def test_outer_status_guard_is_distinct_without_changing_response_or_exception(status: int) -> None:
    async def exercise() -> None:
        class Channel:
            async def request(self, message: dict[str, Any]) -> dict[str, Any]:
                return {"status": status, "body": base64.b64encode(b'{"actual":true}').decode()}

        exchange = owned_exchange(Channel())
        operation: list[InstalledReason] = ["installed_route_relay"]
        if status == 200:
            assert await exchange({}, operation) == {"actual": True}
            assert operation == ["installed_route_relay"]
        else:
            with pytest.raises(RuntimeError, match="^Installed HTTPS relay failed$") as caught:
                await exchange({}, operation)
            assert type(caught.value) is RuntimeError
            assert operation == ["installed_relay_outer_status"]
            fixed = InstalledDiagnostics().capture(caught.value, operation[0], None)
            assert (
                DiagnosticFrame.model_validate(
                    {"kind": "failure", "stage": "keyword_worker", **fixed}
                ).reason
                == "installed_relay_outer_status"
            )

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "reason",
    [
        "installed_relay_request_capacity private",
        "installed_relay_outer_status=500",
        "https://example.test/?state=private",
        "private-cookie",
    ],
)
def test_arbitrary_relay_reasons_or_extra_fields_are_refused(reason: str) -> None:
    with pytest.raises(ValidationError):
        DiagnosticFrame.model_validate(
            {
                "kind": "failure",
                "stage": "keyword_worker",
                "error": "RuntimeError",
                "reason": reason,
            }
        )
    with pytest.raises(ValidationError):
        DiagnosticFrame.model_validate(
            {
                "kind": "failure",
                "stage": "keyword_worker",
                "error": "RuntimeError",
                "reason": "installed_relay_outer_status",
                "message": reason,
            }
        )


def test_static_and_nonstatic_calls_keep_one_existing_request_local_operation_list() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / "scripts/isolation/installed_operator_browser.py").read_text()
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "exchange"
    ]
    assert len(calls) == 2
    assert all(
        len(node.args) == 2 and ast.dump(node.args[1]) == "Name(id='operation', ctx=Load())"
        for node in calls
    )
    assert 'operation: list[InstalledReason] = ["installed_route_headers"]' in source


def test_actual_channel_envelope_guard_keeps_class_and_cleanup() -> None:
    from test_operator_ui_protocol import _owned_channel

    async def exercise() -> None:
        channel = _owned_channel()
        with pytest.raises(RuntimeError, match="^UI diagnostic request too large$") as caught:
            await channel.request({"body": "x" * 32768})
        assert type(caught.value) is RuntimeError
        assert installed_relay_reason(caught.value) == "installed_relay_request_size"
        assert channel.identifier == 1 and channel.admitted == 0
        assert not channel.pending and channel.capacity._value == 8

    asyncio.run(exercise())

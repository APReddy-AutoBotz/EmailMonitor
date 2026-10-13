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

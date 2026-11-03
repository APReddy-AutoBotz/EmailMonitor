"""Owned UI diagnostic transport over the real ASGI app, without a listening server."""

import asyncio
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI
from operator_ui_protocol import MAX_BODY, ORIGIN, RequestFrame, encoded_reply
from starlette.types import Message, Scope


async def collect_replay(app: FastAPI, request: RequestFrame) -> tuple[int, dict[str, str], bytes]:
    """Forward actual frames then disconnect after two seconds; no synthetic events.

    Playwright route.fulfill buffers this diagnostic response. This proves bounded
    real replay/reconnection, not native streaming latency or a sixty-second stream.
    """
    parsed = urlsplit(request.url)
    disconnect = asyncio.Event()
    received = False
    status = 0
    headers: dict[str, str] = {}
    chunks = bytearray()
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "root_path": "",
        "path": parsed.path,
        "raw_path": parsed.path.encode(),
        "query_string": parsed.query.encode(),
        "headers": [(key.encode(), value.encode()) for key, value in request.headers.items()],
        "server": ("app.example.test", 443),
        "client": ("127.0.0.1", 1),
    }

    async def receive() -> Message:
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
            for name, value in message.get("headers", []):
                key = name.decode().lower()
                if key in {"content-type", "cache-control"}:
                    headers[key] = value.decode()
        elif message["type"] == "http.response.body":
            chunks.extend(message.get("body", b""))
            if len(chunks) > MAX_BODY:
                raise ValueError("Actual replay exceeds diagnostic bound")

    task = asyncio.create_task(app(scope, receive, send))
    try:
        done, _ = await asyncio.wait({task}, timeout=2)
        if not done:
            disconnect.set()
        await asyncio.wait_for(task, timeout=3)
    finally:
        disconnect.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    if not status:
        raise ValueError("Missing actual ASGI status")
    body = bytes(chunks)
    if headers.get("content-type", "").startswith("text/event-stream"):
        # The transport may close between chunks. Never manufacture a final event.
        boundary = body.rfind(b"\n\n")
        body = body[: boundary + 2] if boundary >= 0 else b""
    return status, headers, body


async def relay(app: FastAPI, request: RequestFrame) -> dict[str, object]:
    if request.method == "GET" and urlsplit(request.url).path.endswith("/events"):
        status, headers, body = await collect_replay(app, request)
    else:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=ORIGIN,
            follow_redirects=False,
            timeout=5,
        ) as client:
            response = await asyncio.wait_for(
                client.request(
                    request.method, request.url, headers=request.headers, content=request.body
                ),
                timeout=6,
            )
        status, body = response.status_code, response.content
        headers = {
            key: value
            for key, value in response.headers.items()
            if key in {"content-type", "cache-control"}
        }
    return encoded_reply(request.identifier, status, headers, body)

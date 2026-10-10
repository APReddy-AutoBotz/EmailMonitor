"""Synchronous facade over actual HTTPX ASGI transport, without deprecated TestClient."""

import asyncio
from typing import Any

import httpx
from fastapi import FastAPI


class APIClient:
    def __init__(self, app: FastAPI, base_url: str) -> None:
        self.app = app
        self.base_url = base_url
        self.cookies = httpx.Cookies()

    def __enter__(self) -> "APIClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async def invoke() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url=self.base_url,
                cookies=self.cookies,
            ) as client:
                response = await client.request(method, url, **kwargs)
                self.cookies = client.cookies
                return response

        return asyncio.run(invoke())

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", url, **kwargs)

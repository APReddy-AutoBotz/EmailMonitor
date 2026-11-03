"""Test-only byte transport. No socket, DNS, fallback, extraction or script execution."""

from pathlib import Path

import httpx
from emailmonitor.config import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "html"
HOST = "synthetic.publisher.example"
PATHS = {f"/{path.name}": path for path in FIXTURES.glob("*.html")}


def fixture_transport(settings: Settings) -> httpx.MockTransport:
    if settings.environment != "test" or not settings.fixture_mode:
        raise ValueError("Explicit test fixture configuration required")

    def respond(request: httpx.Request) -> httpx.Response:
        url = request.url
        if (
            request.method != "GET"
            or url.scheme != "https"
            or url.host != HOST
            or url.port not in (None, 443)
            or url.username
            or url.password
            or url.query
        ):
            raise ValueError("Fixture request denied")
        path = PATHS.get(url.path)
        if path is None:
            raise ValueError("Unknown fixture path; no network fallback")
        return httpx.Response(
            200,
            content=path.read_bytes(),
            headers={"content-type": "text/html; charset=utf-8"},
        )

    return httpx.MockTransport(respond)

"""Progress availability and strict identifier-only API contract without a database."""

from typing import cast
from uuid import uuid4

import pytest
from api_client import APIClient
from emailmonitor.config import Settings
from emailmonitor.organizations.database import Database
from emailmonitor.progress.api import progress_router
from fastapi import FastAPI, Request


def unavailable_token(request: Request) -> str:
    raise AssertionError("Unavailable fixture route must refuse before reading credentials")


@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("POST", "start", {"expected_revision": 1}),
        ("POST", "retry", {"expected_revision": 1}),
        ("GET", "progress", None),
        ("GET", "events", None),
    ],
)
def test_production_refuses_before_database_or_credentials(
    method: str, suffix: str, body: dict[str, int] | None
) -> None:
    app = FastAPI()
    app.include_router(
        progress_router(cast(Database, object()), unavailable_token, unavailable_token, Settings())
    )
    with APIClient(app, base_url="http://test") as client:
        path = f"/organizations/{uuid4()}/jobs/{uuid4()}/{suffix}"
        response = client.request(method, path, json=body)
        assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"expected_revision": True},
        {"expected_revision": 0},
        {"expected_revision": 1, "html": "untrusted"},
        {"expected_revision": 1, "lease_token": str(uuid4())},
    ],
)
def test_start_rejects_non_identifier_inputs(body: dict[str, object]) -> None:
    app = FastAPI()
    app.include_router(
        progress_router(cast(Database, object()), unavailable_token, unavailable_token, Settings())
    )
    with APIClient(app, base_url="http://test") as client:
        response = client.post(f"/organizations/{uuid4()}/jobs/{uuid4()}/start", json=body)
        assert response.status_code == 422

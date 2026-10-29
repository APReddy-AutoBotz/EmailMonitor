"""Synthetic route wiring; this does not enable reuse or exercise PostgreSQL."""

from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from test_durable_jobs import SETTINGS

from emailmonitor.associations import reuse_materialization
from emailmonitor.associations import service as associations
from emailmonitor.jobs import api

ORG, JOB = UUID(int=1), UUID(int=2)
URL = "https://synthetic.publisher.example/article-a.html"


@pytest.mark.parametrize("reuse", [False, True])
def test_plan_route_materializes_only_explicit_reuse(
    monkeypatch: pytest.MonkeyPatch, reuse: bool
) -> None:
    planned = {
        "plan": {
            "reason": "retained_reuse_authored" if reuse else "supported_fixture",
            "start_url": URL,
        }
    }
    discovery = MagicMock()
    discovery.plan.return_value = planned
    monkeypatch.setattr(api, "Discovery", lambda *_: discovery)
    service, materialize = MagicMock(), MagicMock()
    monkeypatch.setattr(associations, "Associations", lambda *_: service)
    monkeypatch.setattr(reuse_materialization, "materialize_draft", materialize)
    router = api.job_router(MagicMock(), lambda _: "token", lambda _: "session", SETTINGS)
    endpoint = next(
        route.endpoint for route in router.routes if route.path.endswith("/{job_id}/plan")
    )
    result = endpoint(MagicMock(), ORG, JOB, api.Revision(expected_revision=1))
    assert result == planned
    if reuse:
        materialize.assert_called_once_with(service, ORG, JOB, URL)
    else:
        materialize.assert_not_called()


def test_materialization_refusal_propagates_without_returning_fresh_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery = MagicMock()
    discovery.plan.return_value = {"plan": {"reason": "retained_reuse_authored", "start_url": URL}}
    monkeypatch.setattr(api, "Discovery", lambda *_: discovery)
    monkeypatch.setattr(associations, "Associations", lambda *_: MagicMock())
    denied = HTTPException(409, "Synthetic retained source unavailable")
    monkeypatch.setattr(reuse_materialization, "materialize_draft", MagicMock(side_effect=denied))
    router = api.job_router(MagicMock(), lambda _: "token", lambda _: "session", SETTINGS)
    endpoint = next(
        route.endpoint for route in router.routes if route.path.endswith("/{job_id}/plan")
    )
    with pytest.raises(HTTPException) as caught:
        endpoint(MagicMock(), ORG, JOB, api.Revision(expected_revision=1))
    assert caught.value is denied

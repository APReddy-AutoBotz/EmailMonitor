"""Controlled-fake XML/PDF planning; no SQL, acquisition or authority proof."""

import json
from contextlib import nullcontext
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from emailmonitor.administration.models import Entitlements
from emailmonitor.associations import reuse_materialization
from emailmonitor.discovery.service import Discovery
from emailmonitor.discovery.state import DiscoveryState
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.organizations.database import AuthorizationDenied
from fastapi import HTTPException
from test_job_contracts import request_body
from test_source_foundation import policy_body

ORG, JOB = UUID(int=1), UUID(int=2)


def setup(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> tuple[MagicMock, MagicMock, dict[str, object]]:
    body = {
        **request_body(),
        "input": {"type": "url", "url": url},
        "reuse": {"mode": "verified_retained", "fresh_since": "2000-01-01T00:00:00Z"},
    }
    parent: dict[str, object] = {
        "kind": "extraction",
        "state": "draft",
        "row_version": 1,
        "generation": 1,
        "deletion_generation": 1,
        "request": body,
    }
    monkeypatch.setattr(Ledger, "_lock", lambda *_: parent)
    monkeypatch.setattr(
        "emailmonitor.discovery.service.current_policy",
        lambda *_: {
            "version": 1,
            "policy": policy_body(),
        },
    )
    discovery, connection = MagicMock(), MagicMock()
    discovery.token = "synthetic-session"
    discovery._tenant.return_value = nullcontext((connection, object()))
    discovery._plan.side_effect = lambda *args, **kwargs: Discovery._plan(
        discovery, *args, **kwargs
    )
    discovery._row.return_value = {"job_id": JOB, "revision": 1}

    def execute(statement: object, *_: object) -> MagicMock:
        result = MagicMock()
        if "SELECT * FROM emailmonitor.discovery" in str(statement):
            result.mappings.return_value.first.return_value = None
        elif "administration_plan" in str(statement):
            result.scalar_one.return_value = {"entitlements": Entitlements().model_dump()}
        return result

    connection.execute.side_effect = execute
    return discovery, connection, parent


@pytest.mark.parametrize(
    "url",
    [
        "https://synthetic.publisher.example/article-a.pdf",
        "https://synthetic.publisher.example/article-xml.xml",
        "https://synthetic.publisher.example/provider-doi.xml",
    ],
)
def test_staged_plan_uses_existing_policy_and_budget_without_fresh_transport(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    discovery, connection, _ = setup(monkeypatch, url)
    assert Discovery._plan_bound_reuse(discovery, ORG, JOB, 1) == {"job_id": JOB, "revision": 1}
    discovery._authorize.assert_called_once_with(connection, ORG, JOB, 1, url, False)
    insert = next(
        call
        for call in connection.execute.call_args_list
        if "INSERT INTO emailmonitor.discovery" in str(call.args[0])
    )
    plan = json.loads(insert.args[1]["plan"])
    checkpoint = json.loads(insert.args[1]["checkpoint"])
    assert plan["reason"] == "retained_reuse_staged" and plan["start_url"] == url
    assert checkpoint["articles"] == [url] and checkpoint["discovery_complete"] is True
    discovery._schedule.assert_not_called()
    discovery._complete.assert_called_once()


@pytest.mark.parametrize("failure", ["stale_revision", "revoked_policy", "quota", "unregistered"])
def test_staged_admission_preserves_refusals_without_writes(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    url = "https://synthetic.publisher.example/article-a.pdf"
    discovery, connection, parent = setup(monkeypatch, url)
    if failure == "stale_revision":
        parent["row_version"] = 2
    elif failure == "revoked_policy":
        discovery._authorize.side_effect = AuthorizationDenied()
    elif failure == "quota":
        original = connection.execute.side_effect

        def execute(statement: object, *args: object) -> MagicMock:
            result: MagicMock = original(statement, *args)
            if "administration_plan" in str(statement):
                result.scalar_one.return_value = {
                    "entitlements": Entitlements(monthly_resolution_units=0).model_dump()
                }
            return result

        connection.execute.side_effect = execute
    else:
        original_request = parent["request"]
        assert isinstance(original_request, dict)
        parent["request"] = {
            **original_request,
            "input": {"type": "url", "url": "https://other.example/article.pdf"},
        }
    if failure == "unregistered":
        assert Discovery._plan_bound_reuse(discovery, ORG, JOB, 1)["persisted"] is False
    else:
        with pytest.raises((AuthorizationDenied, HTTPException)):
            Discovery._plan_bound_reuse(discovery, ORG, JOB, 1)
    assert not any(
        "INSERT INTO emailmonitor.discovery" in str(call.args[0])
        for call in connection.execute.call_args_list
    )
    discovery._schedule.assert_not_called()


@pytest.mark.parametrize(
    "url,adapter",
    [
        ("https://synthetic.publisher.example/article-a.pdf", "pdf"),
        ("https://synthetic.publisher.example/article-xml.xml", "article_xml"),
    ],
)
def test_staged_coordinator_connects_plan_to_the_same_scoped_materializer(
    monkeypatch: pytest.MonkeyPatch, url: str, adapter: str
) -> None:
    discovery, service, database = MagicMock(), MagicMock(), MagicMock()
    discovery.database = service.database = database
    discovery.token = service.token = "synthetic-session"
    discovery.settings = service.settings = object()
    checkpoint = DiscoveryState(
        status="completed",
        reason="single_article",
        articles=[url],
        discovery_complete=True,
        completeness="single_article",
    ).model_dump()
    planned = {
        "plan": {"classification": "article", "reason": "retained_reuse_staged", "start_url": url},
        "checkpoint": checkpoint,
    }
    discovery._plan_bound_reuse.return_value = planned
    materialize = MagicMock(return_value=UUID(int=8))
    monkeypatch.setattr(reuse_materialization, "_materialize_candidate", materialize)
    assert reuse_materialization._stage_bound_reuse(discovery, service, ORG, JOB, 1) == (
        planned,
        UUID(int=8),
    )
    materialize.assert_called_once_with(service, ORG, JOB, url, adapter)


@pytest.mark.parametrize(
    "url,adapter",
    [
        ("https://synthetic.publisher.example/article-a.pdf", "pdf"),
        ("https://synthetic.publisher.example/provider-doi.xml", "article_xml"),
    ],
)
def test_staged_planner_and_materializer_share_the_checked_scope(
    monkeypatch: pytest.MonkeyPatch, url: str, adapter: str
) -> None:
    discovery, connection, _ = setup(monkeypatch, url)
    service = MagicMock()
    service.database = discovery.database
    service.token = discovery.token
    service.settings = discovery.settings
    discovery._plan_bound_reuse.side_effect = lambda *args: Discovery._plan_bound_reuse(
        discovery, *args
    )
    inserted: dict[str, object] = {}
    original = connection.execute.side_effect

    def execute(statement: object, parameters: dict[str, object] | None = None) -> MagicMock:
        result: MagicMock = original(statement, parameters)
        if "INSERT INTO emailmonitor.discovery" in str(statement):
            assert parameters is not None
            inserted.update(parameters)
        return result

    connection.execute.side_effect = execute
    discovery._row.side_effect = lambda *_: {
        "plan": json.loads(str(inserted["plan"])),
        "checkpoint": json.loads(str(inserted["checkpoint"])),
    }
    materialize = MagicMock(return_value=UUID(int=8))
    monkeypatch.setattr(reuse_materialization, "_materialize_candidate", materialize)
    plan, source = reuse_materialization._stage_bound_reuse(discovery, service, ORG, JOB, 1)
    assert plan["plan"]["start_url"] == url  # type: ignore[index]
    assert source == UUID(int=8)
    discovery._authorize.assert_called_once_with(connection, ORG, JOB, 1, url, False)
    discovery._schedule.assert_not_called()
    materialize.assert_called_once_with(service, ORG, JOB, url, adapter)


@pytest.mark.parametrize(
    "failure",
    [
        "other_database",
        "other_session",
        "other_settings",
        "unsupported",
        "wrong_checkpoint",
        "materialization_refusal",
    ],
)
def test_staged_coordinator_fails_closed_without_fresh_fallback(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    url = "https://synthetic.publisher.example/article-a.pdf"
    discovery, service, database = MagicMock(), MagicMock(), MagicMock()
    discovery.database = service.database = database
    discovery.token = service.token = "synthetic-session"
    discovery.settings = service.settings = object()
    checkpoint = DiscoveryState(
        status="completed",
        reason="single_article",
        articles=[url],
        discovery_complete=True,
        completeness="single_article",
    ).model_dump()
    planned = {
        "plan": {"classification": "article", "reason": "retained_reuse_staged", "start_url": url},
        "checkpoint": checkpoint,
    }
    discovery._plan_bound_reuse.return_value = planned
    materialize = MagicMock(return_value=UUID(int=8))
    monkeypatch.setattr(reuse_materialization, "_materialize_candidate", materialize)
    if failure == "other_database":
        service.database = MagicMock()
    elif failure == "other_session":
        service.token = "different-session"
    elif failure == "other_settings":
        service.settings = object()
    elif failure == "unsupported":
        planned["plan"]["reason"] = "retained_reuse_unavailable"
    elif failure == "wrong_checkpoint":
        checkpoint["articles"] = ["https://synthetic.publisher.example/article-b.pdf"]
    else:
        materialize.side_effect = AuthorizationDenied()
    with pytest.raises((AuthorizationDenied, HTTPException)):
        reuse_materialization._stage_bound_reuse(discovery, service, ORG, JOB, 1)
    if failure != "materialization_refusal":
        materialize.assert_not_called()
    discovery._schedule.assert_not_called()

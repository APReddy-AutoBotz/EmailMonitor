"""Synthetic orchestration tests; no actual database or worker authorization."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body

from emailmonitor.associations import reuse_materialization as module
from emailmonitor.associations.service import initial_bundle
from emailmonitor.extraction.fixture import article_bytes
from emailmonitor.extraction.html import parse_article
from emailmonitor.organizations.database import AuthorizationDenied

ORG, SOURCE, TARGET, BATCH = (UUID(int=i) for i in range(1, 5))
URL = "https://synthetic.publisher.example/article-a.html"


def setup(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock, dict[str, object]]:
    service, connection = MagicMock(), MagicMock()
    service._lock = MagicMock()
    service.settings = SETTINGS
    service.discovery._tenant.return_value = nullcontext((connection, object()))
    service.extraction._scope.return_value = {"revision": 1}
    monkeypatch.setattr(module.Admission, "fixture", lambda *_: nullcontext())
    request = {
        **request_body(),
        "input": {"type": "url", "url": URL},
        "reuse": {"mode": "verified_retained", "fresh_since": "2026-10-01T00:00:00Z"},
    }
    target = {"state": "draft", "request": request, "generation": 1, "deletion_generation": 1}
    monkeypatch.setattr(module.Ledger, "_lock", lambda *_: target)
    lineage = SimpleNamespace(
        source_job_id=SOURCE,
        source_revision=1,
        source_id="synthetic-publisher",
        source_policy_version=1,
    )
    monkeypatch.setattr(module, "prepare_reuse", lambda *_: SimpleNamespace(lineage=lineage))
    state: dict[str, object] = {"existing": None, "selected": BATCH, "inserted": []}

    def execute(statement: object, parameters: dict[str, object] | None = None) -> MagicMock:
        query = str(statement)
        result = MagicMock()
        if query.startswith("SELECT reused_from_job"):
            result.mappings.return_value.first.return_value = state["existing"]
        elif "SELECT b.id FROM" in query:
            result.scalar_one_or_none.return_value = state["selected"]
        elif "SELECT a.organization_id" in query:
            result.mappings.return_value.one.return_value = {
                "source_digest": "a" * 64,
                "observation": {"route": "html", "url": URL},
            }
        elif "INSERT INTO emailmonitor.article_observations" in query:
            assert isinstance(state["inserted"], list)
            state["inserted"].append(parameters)
        else:
            raise AssertionError("Unexpected synthetic SQL operation")
        return result

    connection.execute.side_effect = execute
    return service, connection, state


def test_stages_exact_source_lineage_and_rechecks_source(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _, state = setup(monkeypatch)
    assert module.materialize_draft(service, ORG, TARGET, URL) == BATCH
    inserted = state["inserted"]
    assert isinstance(inserted, list) and len(inserted) == 1
    assert inserted[0]["job"] == TARGET and inserted[0]["source_job"] == SOURCE
    assert inserted[0]["source_revision"] == 1 and inserted[0]["source_batch"] == BATCH
    service._lock.assert_called_once()


def test_replay_keeps_original_source_even_if_newer_source_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, connection, state = setup(monkeypatch)
    state["existing"] = {
        "reused_from_job": SOURCE,
        "reused_source_revision": 1,
        "reused_source_batch": BATCH,
    }
    state["selected"] = UUID(int=99)
    assert module.materialize_draft(service, ORG, TARGET, URL) == BATCH
    assert state["inserted"] == []
    assert not any(
        "SELECT b.id FROM" in str(call.args[0]) for call in connection.execute.call_args_list
    )


def test_no_eligible_source_never_falls_back_to_fresh_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, state = setup(monkeypatch)
    state["selected"] = None
    with pytest.raises(HTTPException) as error:
        module.materialize_draft(service, ORG, TARGET, URL)
    assert error.value.status_code == 409 and state["inserted"] == []


def test_missing_explicit_choice_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _, state = setup(monkeypatch)
    monkeypatch.setattr(
        module.Ledger, "_lock", lambda *_: {"state": "draft", "request": request_body()}
    )
    with pytest.raises(AuthorizationDenied):
        module.materialize_draft(service, ORG, TARGET, URL)
    assert state["inserted"] == []


def test_other_routes_are_not_silently_acquired(monkeypatch: pytest.MonkeyPatch) -> None:
    service, connection, _ = setup(monkeypatch)
    with pytest.raises(HTTPException) as error:
        module.materialize_draft(service, ORG, TARGET, "https://synthetic.publisher.example/a.pdf")
    assert error.value.status_code == 409
    connection.execute.assert_not_called()


def test_target_review_starts_unaccepted_without_changing_legacy_mapping() -> None:
    observed = parse_article(SETTINGS, URL, article_bytes("article-a.html"))
    ordinary = initial_bundle(SETTINGS, ORG, TARGET, observed, None)
    reused = initial_bundle(SETTINGS, ORG, TARGET, observed, SOURCE)
    assert ordinary.associations[0].state == "accepted"
    assert reused.associations[0].state == "needs_review"
    assert reused.associations[0].revision == 1
    assert ordinary.associations[0].id != reused.associations[0].id
    assert ordinary.evidence == reused.evidence

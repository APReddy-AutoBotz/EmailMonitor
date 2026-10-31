"""Transient source context, never a durable association or review decision."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from api_client import APIClient
from emailmonitor.associations import api as association_api
from emailmonitor.associations.api import association_router
from emailmonitor.associations.context_view import project_context
from emailmonitor.associations.models import Bundle
from emailmonitor.associations.service import Associations
from emailmonitor.config import Settings
from emailmonitor.organizations.database import (
    AuthorizationDenied,
    Database,
    RevisionConflict,
    TenantContext,
)
from emailmonitor.organizations.roles import Capability, Role
from fastapi import FastAPI, Request
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError
from test_associations import ORG, SETTINGS, html

TARGET = UUID(int=1)
SOURCE = UUID(int=2)
ACTOR = UUID(int=9)
ROOT = Path(__file__).resolve().parents[3]


def fixture() -> tuple[Bundle, Bundle]:
    return html("article-a.html"), html("article-b.html")


def project(target: Bundle, source: Bundle, **change: Any) -> Any:
    args: dict[str, Any] = {
        "org": ORG,
        "target_batch": TARGET,
        "target": target,
        "association_id": target.associations[0].id,
        "revision": target.associations[0].revision,
        "source_batch": SOURCE,
        "source": source,
        "evidence_id": source.evidence[0].id,
    }
    return project_context(**(args | change))


def test_context_retains_original_source_and_never_mutates_reviews() -> None:
    target, source = fixture()
    target_before, source_before = target.model_dump_json(), source.model_dump_json()
    result = project(target, source)
    assert result.kind == "transient_context_only" and result.evidence == source.evidence[0]
    assert result.source_url == source.source_url and result.source_digest == source.content_digest
    assert not result.attached and not result.identity_verified
    assert not result.acceptance_changed and not result.export_changed
    assert target.model_dump_json() == target_before and source.model_dump_json() == source_before


@pytest.mark.parametrize(
    "change",
    [
        {"source_batch": TARGET},
        {"association_id": UUID(int=17)},
        {"evidence_id": UUID(int=19)},
        {"org": UUID(int=20)},
    ],
)
def test_unknown_scope_and_evidence_are_refused(change: dict[str, object]) -> None:
    target, source = fixture()
    with pytest.raises(AuthorizationDenied):
        project(target, source, **change)


def test_cross_tenant_source_and_stale_target_are_refused() -> None:
    target, source = fixture()
    other = html("article-b.html", org=UUID(int=99))
    with pytest.raises(AuthorizationDenied):
        project(target, other, evidence_id=other.evidence[0].id)
    with pytest.raises(RevisionConflict):
        project(target, source, revision=target.associations[0].revision + 1)


def test_target_suppression_cannot_be_overridden() -> None:
    target, source = fixture()
    row = target.associations[0].model_copy(update={"state": "suppressed"})
    target = target.model_copy(update={"associations": (row,)})
    with pytest.raises(AuthorizationDenied):
        project(target, source)


def test_service_uses_review_capability_two_ordered_fences_and_release_recheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, source = fixture()
    service = Associations(cast(Any, object()), "synthetic", SETTINGS)
    events: list[object] = []

    class Connection:
        def execute(self, _query: object, values: dict[str, object]) -> None:
            events.append(("audit", values["actor"], values["action"], values["resource"]))

    @contextmanager
    def tenant(org: UUID, capability: Capability) -> Iterator[tuple[object, object]]:
        events.append((org, capability))
        yield Connection(), TenantContext(org, ACTOR, Role.REVIEWER, "active")

    def lock(_connection: object, _org: UUID, batch: UUID) -> None:
        events.append(("lock", batch))

    def bundle(_connection: object, _org: UUID, batch: UUID) -> Bundle:
        events.append(("read", batch))
        return target if batch == TARGET else source

    monkeypatch.setattr(service.discovery, "_tenant", tenant)
    monkeypatch.setattr(service, "_lock", lock)
    monkeypatch.setattr(service, "_bundle", bundle)
    result = service.context_view(
        ORG, TARGET, target.associations[0].id, 1, SOURCE, source.evidence[0].id
    )
    assert result.source_batch_id == SOURCE
    assert events == [
        (ORG, Capability.REVIEW_ASSOCIATIONS),
        ("lock", TARGET),
        ("lock", SOURCE),
        ("read", TARGET),
        ("read", SOURCE),
        ("read", TARGET),
        ("read", SOURCE),
        ("audit", ACTOR, "association.context_target_viewed", target.associations[0].id),
        ("audit", ACTOR, "association.context_evidence_viewed", source.evidence[0].id),
    ]


def test_service_propagates_source_revocation_before_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, source = fixture()
    service = Associations(cast(Any, object()), "synthetic", SETTINGS)
    reads: list[UUID] = []

    @contextmanager
    def tenant(_org: UUID, _capability: Capability) -> Iterator[tuple[object, object]]:
        yield object(), TenantContext(ORG, ACTOR, Role.REVIEWER, "active")

    def bundle(_connection: object, _org: UUID, batch: UUID) -> Bundle:
        reads.append(batch)
        if batch == SOURCE and reads.count(SOURCE) == 2:
            raise AuthorizationDenied()
        return target if batch == TARGET else source

    monkeypatch.setattr(service.discovery, "_tenant", tenant)
    monkeypatch.setattr(service, "_lock", lambda *_args: None)
    monkeypatch.setattr(service, "_bundle", bundle)
    with pytest.raises(AuthorizationDenied):
        service.context_view(
            ORG, TARGET, target.associations[0].id, 1, SOURCE, source.evidence[0].id
        )


def test_audit_failure_refuses_release(monkeypatch: pytest.MonkeyPatch) -> None:
    target, source = fixture()
    service = Associations(cast(Any, object()), "synthetic", SETTINGS)

    class Connection:
        def execute(self, _query: object, _values: object) -> None:
            raise RuntimeError("audit unavailable")

    @contextmanager
    def tenant(_org: UUID, _capability: Capability) -> Iterator[tuple[object, object]]:
        yield Connection(), TenantContext(ORG, ACTOR, Role.REVIEWER, "active")

    monkeypatch.setattr(service.discovery, "_tenant", tenant)
    monkeypatch.setattr(service, "_lock", lambda *_args: None)
    monkeypatch.setattr(
        service, "_bundle", lambda _c, _o, batch: target if batch == TARGET else source
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        service.context_view(
            ORG, TARGET, target.associations[0].id, 1, SOURCE, source.evidence[0].id
        )


def test_target_revision_change_before_release_is_not_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, source = fixture()
    service = Associations(cast(Any, object()), "synthetic", SETTINGS)
    reads: list[UUID] = []

    @contextmanager
    def tenant(_org: UUID, _capability: Capability) -> Iterator[tuple[object, object]]:
        yield object(), TenantContext(ORG, ACTOR, Role.REVIEWER, "active")

    def bundle(_connection: object, _org: UUID, batch: UUID) -> Bundle:
        reads.append(batch)
        if batch == TARGET and reads.count(TARGET) == 2:
            changed = target.associations[0].model_copy(update={"revision": 2})
            return target.model_copy(update={"associations": (changed,)})
        return target if batch == TARGET else source

    monkeypatch.setattr(service.discovery, "_tenant", tenant)
    monkeypatch.setattr(service, "_lock", lambda *_args: None)
    monkeypatch.setattr(service, "_bundle", bundle)
    with pytest.raises(RevisionConflict):
        service.context_view(
            ORG, TARGET, target.associations[0].id, 1, SOURCE, source.evidence[0].id
        )


def test_api_refuses_production_before_database_or_work() -> None:
    app = FastAPI()

    def session(_request: Request) -> str:
        return "synthetic"

    app.include_router(
        association_router(
            cast(Database, object()), session, session, Settings(environment="production")
        )
    )
    target, source = fixture()
    with APIClient(app, base_url="https://app.example.test") as client:
        response = client.post(
            f"/organizations/{ORG}/review-context/view",
            json={
                "target_batch_id": str(TARGET),
                "target_association_id": str(target.associations[0].id),
                "expected_revision": 1,
                "source_batch_id": str(SOURCE),
                "source_evidence_id": str(source.evidence[0].id),
            },
        )
    assert response.status_code == 404


def test_api_requires_csrf_and_returns_only_explicit_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, source = fixture()
    sessions: list[str] = []

    class SyntheticService:
        def __init__(self, _database: object, session: str, _settings: object) -> None:
            sessions.append(session)

        def context_view(
            self,
            org: UUID,
            target_batch: UUID,
            association: UUID,
            revision: int,
            source_batch: UUID,
            evidence: UUID,
        ) -> object:
            return project_context(
                org, target_batch, target, association, revision, source_batch, source, evidence
            )

    monkeypatch.setattr(association_api, "Associations", SyntheticService)
    app = FastAPI()
    app.include_router(
        association_router(
            cast(Database, object()), lambda _r: "read-session", lambda _r: "csrf-session", SETTINGS
        )
    )
    body = {
        "target_batch_id": str(TARGET),
        "target_association_id": str(target.associations[0].id),
        "expected_revision": 1,
        "source_batch_id": str(SOURCE),
        "source_evidence_id": str(source.evidence[0].id),
    }
    with APIClient(app, base_url="https://app.example.test") as client:
        response = client.post(f"/organizations/{ORG}/review-context/view", json=body)
        invalid = client.post(
            f"/organizations/{ORG}/review-context/view", json={**body, "author_id": str(ACTOR)}
        )
    assert response.status_code == 200 and sessions == ["csrf-session"]
    assert response.json()["kind"] == "transient_context_only"
    assert response.json()["attached"] is False and response.json()["identity_verified"] is False
    assert invalid.status_code == 422


def test_request_schema_matches_bounded_http_input() -> None:
    schema = json.loads((ROOT / "contracts/review-context-view-request.schema.json").read_text())
    valid = json.loads((ROOT / "contracts/examples/review-context-view-request.json").read_text())
    check = Draft202012Validator(schema, format_checker=FormatChecker())
    check.validate(valid)
    association_api.ContextViewInput.model_validate(valid)
    for change in (
        {"source_evidence_id": "urn:uuid:" + valid["source_evidence_id"]},
        {"expected_revision": True},
        {"reason": "new content"},
    ):
        value = valid | change
        assert not check.is_valid(value)
        with pytest.raises(ValidationError):
            association_api.ContextViewInput.model_validate(value)

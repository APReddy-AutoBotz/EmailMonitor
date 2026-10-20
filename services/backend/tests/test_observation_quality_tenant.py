"""Real runtime-role/RLS coverage; service absence is an explicit local skip."""

from uuid import UUID, uuid4

import pytest
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from sqlalchemy import Connection, text
from test_association_tenant import client, prepared, review_request
from test_durable_jobs import SETTINGS
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def test_runtime_quality_read_preserves_stored_snapshot_replay_and_review(
    scenario: Scenario,
) -> None:
    service, job, batch = prepared(scenario)
    org = scenario.organizations[0]
    with service.discovery._tenant(org, Capability.READ_ORGANIZATION) as (c, _):
        before = c.execute(
            text(
                "SELECT snapshot,input_digest FROM emailmonitor.association_batches "
                "WHERE organization_id=:org AND id=:batch"
            ),
            {"org": org, "batch": batch},
        ).first()
    quality = service.quality(org, batch)
    assert quality.reason_availability == "not_recorded" and quality.reasons == ()
    service.review(org, batch, review_request(service, org, batch))
    assert service.quality(org, batch) == quality
    assert (
        service.derive(org, job, "https://synthetic.publisher.example/article-a.html", 1) == batch
    )
    with service.discovery._tenant(org, Capability.READ_ORGANIZATION) as (c, _):
        after = c.execute(
            text(
                "SELECT snapshot,input_digest FROM emailmonitor.association_batches "
                "WHERE organization_id=:org AND id=:batch"
            ),
            {"org": org, "batch": batch},
        ).first()
    assert before == after
    with client(scenario) as c:
        scenario.login(c, "viewer")
        url = f"/api/v1/organizations/{org}/association-batches/{batch}/observation-quality"
        result = c.get(url)
        assert result.status_code == 200, result.text
        assert result.json() == quality.model_dump(mode="json")
        assert c.get(url.replace(str(org), str(scenario.organizations[1]))).status_code == 404
        assert c.get(url.replace(str(batch), str(uuid4()))).status_code == 404


@pytest.mark.parametrize("kind", ["policy", "session", "suppression", "deletion", "expiry"])
def test_quality_current_authority_refuses(scenario: Scenario, kind: str) -> None:
    service, _, batch = prepared(scenario)
    org = scenario.organizations[0]
    assert service.quality(org, batch).scope == "article"
    from sqlalchemy import create_engine

    admin = create_engine(scenario.admin_url)
    try:
        with admin.begin() as c:
            c.execute(text("SET LOCAL ROLE emailmonitor_owner"))
            if kind == "policy":
                c.execute(
                    text(
                        "UPDATE emailmonitor.source_policies SET state='revoked' "
                        "WHERE organization_id=:org"
                    ),
                    {"org": org},
                )
            elif kind == "session":
                c.execute(text("UPDATE emailmonitor.sessions SET revoked_at=clock_timestamp()"))
            elif kind == "deletion":
                c.execute(
                    text(
                        "UPDATE emailmonitor.organizations SET deletion_generation="
                        "deletion_generation+1 WHERE id=:org"
                    ),
                    {"org": org},
                )
            elif kind == "expiry":
                c.execute(text("UPDATE emailmonitor.sessions SET expires_at=clock_timestamp()"))
            else:
                # Exercise the supported suppression service below rather than bypass triggers.
                pass
        if kind == "suppression":
            from emailmonitor.lifecycle.models import SuppressionCreate
            from emailmonitor.lifecycle.service import Lifecycle

            contact = service.detail(org, batch).candidates[0].address.raw_address
            Lifecycle(service.database, service.token, SETTINGS).suppress(
                org, SuppressionCreate(kind="contact", value=contact, reason="privacy_request")
            )
        with pytest.raises(AuthorizationDenied):
            service.quality(org, batch)
    finally:
        admin.dispose()


def test_quality_final_visibility_failure_releases_no_summary(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, batch = prepared(scenario)
    original = service._lock
    calls = 0

    def revoke_at_final(c: Connection, org: UUID, batch: UUID) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise AuthorizationDenied()
        original(c, org, batch)

    monkeypatch.setattr(service, "_lock", revoke_at_final)
    with pytest.raises(AuthorizationDenied):
        service.quality(scenario.organizations[0], batch)


def test_no_contact_batch_quality_is_available_without_contact_row(scenario: Scenario) -> None:
    from emailmonitor.associations.service import Associations
    from test_html_extraction_tenant import ready

    extraction, job = ready(scenario)
    org = scenario.organizations[0]
    url = "https://synthetic.publisher.example/no-contact.html"
    extraction.fixture(org, job, url, 3)
    service = Associations(extraction.database, extraction.token, SETTINGS)
    batch = service.derive(org, job, url, 1)
    assert service.detail(org, batch).candidates == ()
    with client(scenario) as c:
        scenario.login(c, "viewer")
        response = c.get(
            f"/api/v1/organizations/{org}/association-batches/{batch}/observation-quality"
        )
        assert response.status_code == 200, response.text
        assert response.json()["observation_status"] == "no_contact"
        assert response.json()["reason_availability"] == "not_recorded"


def test_quality_final_runtime_join_visibility_is_required(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typing import Any

    service, _, batch = prepared(scenario)
    original = Connection.execute
    reads = 0

    def hide_final_join(c: Connection, statement: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal reads
        if "SELECT source.observation,source.job_id" in str(statement):
            reads += 1
            if reads == 2:
                # Only the second runtime SELECT loses visibility; parent locks still pass.
                return original(c, text("SELECT 1 WHERE false"))
        return original(c, statement, *args, **kwargs)

    monkeypatch.setattr(Connection, "execute", hide_final_join)
    with pytest.raises(AuthorizationDenied):
        service.quality(scenario.organizations[0], batch)
    assert reads == 2


@pytest.mark.parametrize("field", ["excerpt_days", "contact_days"])
def test_quality_respects_current_retention_before_sweep(scenario: Scenario, field: str) -> None:
    from emailmonitor.lifecycle.models import Retention, RetentionUpdate
    from emailmonitor.lifecycle.service import Lifecycle

    service, _, batch = prepared(scenario)
    org = scenario.organizations[0]
    assert service.quality(org, batch).scope == "article"
    lifecycle = Lifecycle(service.database, service.token, SETTINGS)
    current = lifecycle.retention(org)
    lifecycle.update_retention(
        org,
        RetentionUpdate(
            expected_revision=current.revision,
            retention=Retention.model_validate({field: 0}),
        ),
    )
    with pytest.raises(AuthorizationDenied):
        service.quality(org, batch)

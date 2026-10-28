"""Required actual PostgreSQL results/export lifecycle; unavailable service is an explicit skip."""

import hashlib
import io
import time
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from api_client import APIClient
from emailmonitor.api import create_app
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict
from emailmonitor.organizations.roles import Capability
from emailmonitor.results.models import ExportInput, Filters
from emailmonitor.results.render import render
from emailmonitor.results.service import Lease, Results
from sqlalchemy import create_engine, text
from test_durable_jobs import SETTINGS
from test_progress_tenant import drain, planned
from test_source_foundation import source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario


def prepared(s: Scenario, url: str = "article-a.html") -> tuple[Results, UUID]:
    progress, job = planned(s, "https://synthetic.publisher.example/" + url)
    org = s.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    drain(progress, org, job)
    return Results(progress.database, progress.token, SETTINGS), job


def options(job: UUID, **changes: object) -> ExportInput:
    return ExportInput.model_validate(
        {"job_id": str(job), "format": "xlsx", "purpose": "academic_contact_research", **changes}
    )


def lease(results: Results, org: UUID, export: UUID, seconds: int = 30) -> Lease:
    row = next(row for row in results.pending(org) if row["export_id"] == export)
    claimed = results.claim(
        org, export, UUID(str(row["event_id"])), int(str(row["generation"])), seconds
    )
    assert claimed is not None
    return claimed


def ready(results: Results, org: UUID, job: UUID, **changes: object) -> UUID:
    state = results.create(org, options(job, **changes), str(uuid4()))
    assert state.state == "queued" and not state.download_available
    assert results.process(lease(results, org, state.id))
    assert results.state(org, state.id).download_available
    return state.id


def test_real_results_contacts_outcomes_evidence_and_cursor(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    page = results.contacts(org, Filters(job_id=job), limit=1)
    assert len(page.items) == 1 and page.items[0].state == "accepted"
    first = page.items[0]
    assert first.technical_status == "not_checked" and first.outreach_eligibility == "not_assessed"
    assert results.contact(org, first.batch_id, first.association_id) == first
    with pytest.raises(AuthorizationDenied):
        results.contact(org, uuid4(), first.association_id)
    with pytest.raises(AuthorizationDenied):
        results.outcomes(org, uuid4())
    evidence = results.evidence(org, first.batch_id, first.evidence_ids[0])
    assert evidence.citation.id == first.evidence_ids[0] and not evidence.raw_document_available
    if page.next_cursor:
        second = results.contacts(org, Filters(job_id=job), page.next_cursor, 1)
        assert all(item.association_id != first.association_id for item in second.items)
        with pytest.raises(ValueError):
            results.contacts(org, Filters(job_id=job, query="changed"), page.next_cursor)
    assert results.contacts(org, Filters(job_id=job, query="unmatched-literal%")).items == ()
    assert results.outcomes(org, job).items[0].state in {"succeeded", "needs_review"}


def test_real_no_contact_outcomes_do_not_invent_contacts(scenario: Scenario) -> None:
    results, job = prepared(scenario, "no-contact.html")
    org = scenario.organizations[0]
    assert results.contacts(org, Filters(job_id=job)).items == ()
    assert results.outcomes(org, job).items[0].state == "no_contact"
    export = ready(results, org, job)
    with ZipFile(io.BytesIO(results.download(org, export).body)) as archive:
        assert len([name for name in archive.namelist() if name.startswith("xl/worksheets/")]) == 3


def test_real_export_atomic_snapshot_idempotency_private_grants(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    key = str(uuid4())
    first = results.create(org, options(job), key)
    assert results.create(org, options(job), key).id == first.id
    with pytest.raises(RevisionConflict):
        results.create(org, options(job, format="csv"), key)
    with results.database.tenant(results.token, org, Capability.EXPORT_RESULTS) as (c, _):
        for table in (
            "exports",
            "export_members",
            "export_outcomes",
            "export_artifacts",
            "export_requests",
            "export_outbox",
            "export_effects",
        ):
            assert not c.execute(
                text("SELECT has_table_privilege(current_user,:table,'UPDATE')"),
                {"table": "emailmonitor." + table},
            ).scalar_one()
        assert not c.execute(
            text(
                "SELECT has_column_privilege(current_user,'emailmonitor.exports',"
                "'snapshot','SELECT')"
            )
        ).scalar_one()
        assert not c.execute(
            text(
                "SELECT has_table_privilege(current_user,'emailmonitor.export_artifacts','SELECT')"
            )
        ).scalar_one()
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.export_outbox "
                    "WHERE organization_id=:org AND export_id=:id"
                ),
                {"org": org, "id": first.id},
            ).scalar_one()
            == 1
        )
    assert results.process(lease(results, org, first.id))
    artifact = results.download(org, first.id)
    assert artifact.extension == "xlsx" and hashlib.sha256(artifact.body).hexdigest()
    assert first.contacts >= 1 and results.state(org, first.id).state == "ready"


@pytest.mark.parametrize(
    "role,allowed",
    [
        ("owner", True),
        ("admin", True),
        ("data_steward", True),
        ("operator", False),
        ("reviewer", False),
        ("viewer", False),
    ],
)
def test_real_result_read_and_export_role_matrix(
    scenario: Scenario, role: str, allowed: bool
) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    with scenario.client() as client:
        scenario.login(client, role)
        other = Results(results.database, str(client.cookies[COOKIE]), SETTINGS)
        assert other.contacts(org, Filters(job_id=job)).items
        if allowed:
            assert other.create(org, options(job), str(uuid4())).state == "queued"
        else:
            with pytest.raises(AuthorizationDenied):
                other.create(org, options(job), str(uuid4()))


def test_real_revocation_and_old_lease_refuse_late_artifact(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    state = results.create(org, options(job), str(uuid4()))
    work = lease(results, org, state.id)
    running = results.state(org, state.id)
    revoked = results.revoke(org, state.id, running.revision)
    assert revoked.state == "revoked" and revoked.generation == running.generation + 1
    assert not results.finish(work, render(work.snapshot))
    with pytest.raises(AuthorizationDenied):
        results.download(org, state.id)


def test_real_revision_change_invalidates_ready_artifact(scenario: Scenario) -> None:
    from emailmonitor.associations.models import Review
    from emailmonitor.associations.service import Associations

    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = ready(results, org, job)
    contact = results.contacts(org, Filters(job_id=job)).items[0]
    Associations(results.database, results.token, SETTINGS).review(
        org,
        contact.batch_id,
        Review(
            association_id=contact.association_id,
            expected_revision=contact.revision,
            action="reject",
            author_id=None,
            evidence_ids=contact.evidence_ids,
            reason="Synthetic evidence review",
        ),
    )
    assert not results.state(org, export).download_available
    with pytest.raises(AuthorizationDenied):
        results.download(org, export)


def test_real_current_policy_and_cross_tenant_download(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = ready(results, org, job)
    with pytest.raises(AuthorizationDenied):
        results.download(scenario.organizations[1], export)
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        assert (
            client.post(
                source_path(scenario) + "/policy-state",
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
            ).status_code
            == 200
        )
    assert not results.state(org, export).download_available
    with pytest.raises(AuthorizationDenied):
        results.download(org, export)


def test_real_expiry_and_lease_recovery(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    expired = ready(results, org, job, ttl_seconds=2)
    time.sleep(2.1)
    with pytest.raises(AuthorizationDenied):
        results.download(org, expired)
    results.reconcile(org, expired)
    assert results.state(org, expired).state == "expired"
    state = results.create(org, options(job), str(uuid4()))
    old = lease(results, org, state.id, 1)
    time.sleep(1.1)
    results.reconcile(org, state.id)
    fresh = lease(results, org, state.id)
    assert fresh.nonce != old.nonce and not results.finish(old, render(old.snapshot))
    assert results.process(fresh)


def test_real_requester_membership_blocks_artifact(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    with scenario.client() as client:
        scenario.login(client, "admin")
        requester = Results(results.database, str(client.cookies[COOKIE]), SETTINGS)
        export = ready(requester, org, job)
    engine = create_engine(scenario.admin_url)
    try:
        with engine.begin() as c:
            c.execute(
                text(
                    "UPDATE emailmonitor.memberships SET status='revoked' "
                    "WHERE organization_id=:org AND identity_id=:actor"
                ),
                {"org": org, "actor": scenario.identities["admin"]},
            )
        with pytest.raises(AuthorizationDenied):
            results.download(org, export)
    finally:
        engine.dispose()


def test_real_http_export_csrf_auth_download_and_production_refusal(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    with APIClient(
        create_app(SETTINGS.model_copy(update={"identity_stub": True}), scenario.foundation),
        base_url=ORIGIN,
    ) as client:
        csrf = scenario.login(client, "owner")
        path = f"/api/v1/organizations/{org}"
        body = options(job).model_dump(mode="json")
        assert (
            client.post(
                path + "/exports", headers={"Idempotency-Key": "api-test"}, json=body
            ).status_code
            == 403
        )
        response = client.post(
            path + "/exports",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf, "Idempotency-Key": "api-test"},
            json=body,
        )
        assert response.status_code == 201, response.text
        export = UUID(response.json()["id"])
        authenticated = Results(results.database, str(client.cookies[COOKIE]), SETTINGS)
        assert authenticated.process(lease(authenticated, org, export))
        downloaded = client.get(path + f"/exports/{export}/download")
        assert downloaded.status_code == 200 and downloaded.headers["cache-control"] == "no-store"
        assert (
            downloaded.headers["x-content-type-options"] == "nosniff"
            and "attachment" in downloaded.headers["content-disposition"]
        )
        assert (
            client.get(
                f"/api/v1/organizations/{scenario.organizations[1]}/exports/{export}/download"
            ).status_code
            == 404
        )
    with scenario.client() as client:
        scenario.login(client, "owner")
        assert client.get(f"/api/v1/organizations/{org}/contacts").status_code == 404


def test_real_policy_change_while_rendering_refuses_commit_and_cached_key(
    scenario: Scenario,
) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    key = str(uuid4())
    export = results.create(org, options(job), key).id
    work = lease(results, org, export)
    artifact = render(work.snapshot)
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        response = client.post(
            source_path(scenario) + "/policy-state",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
        )
        assert response.status_code == 200, response.text
    with pytest.raises(AuthorizationDenied):
        results.finish(work, artifact)
    with pytest.raises(AuthorizationDenied):
        results.create(org, options(job), key)
    results.reconcile(org, export)
    assert results.state(org, export).reason == "snapshot_changed"


def test_real_deletion_generation_and_current_session_close_download(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = ready(results, org, job)
    engine = create_engine(scenario.admin_url)
    try:
        with engine.begin() as c:
            c.execute(
                text("UPDATE emailmonitor.organizations SET status='offboarding' WHERE id=:org"),
                {"org": org},
            )
        with pytest.raises(AuthorizationDenied):
            results.download(org, export)
    finally:
        engine.dispose()


def test_real_confirmed_pending_and_duplicate_effects_remain_bounded(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = results.create(org, options(job), str(uuid4())).id
    original = results.pending(org)[0]
    results.confirmed(org, export, UUID(str(original["event_id"])))
    assert results.pending(org) == []
    results.reconcile(org, export)
    assert results.pending(org)[0]["event_id"] == original["event_id"]
    work = lease(results, org, export)
    artifact = render(work.snapshot)
    assert results.finish(work, artifact)
    assert not results.finish(work, artifact)
    assert results.claim(org, export, UUID(str(original["event_id"])), 1) is None
    with results.database.tenant(results.token, org, Capability.EXPORT_RESULTS) as (c, _):
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.export_effects "
                    "WHERE organization_id=:org AND export_id=:id"
                ),
                {"org": org, "id": export},
            ).scalar_one()
            == 1
        )
        assert c.execute(
            text(
                "SELECT event_type FROM emailmonitor.export_events "
                "WHERE organization_id=:org AND export_id=:id ORDER BY occurred_at"
            ),
            {"org": org, "id": export},
        ).scalars().all() == ["export.requested", "export.ready"]


def test_real_review_unlink_preserves_evidence_and_invalidates_export(scenario: Scenario) -> None:
    from emailmonitor.associations.models import Review
    from emailmonitor.associations.service import Associations

    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = ready(results, org, job)
    contact = results.contacts(org, Filters(job_id=job)).items[0]
    service = Associations(results.database, results.token, SETTINGS)
    before = service.detail(org, contact.batch_id)
    request = Review(
        association_id=contact.association_id,
        expected_revision=contact.revision,
        action="unlink",
        author_id=None,
        evidence_ids=contact.evidence_ids,
        reason="Synthetic review: unlink this association",
    )
    after = service.review(org, contact.batch_id, request)
    association = next(a for a in after.associations if a.id == contact.association_id)
    assert (association.state, association.author_id, association.reason, association.revision) == (
        "needs_review",
        None,
        "reviewed_unlinked",
        contact.revision + 1,
    )
    assert association.evidence_ids == contact.evidence_ids
    assert after.evidence == before.evidence and after.authors == before.authors
    assert after.candidates == before.candidates
    assert service.history(org, contact.batch_id)[-1]["action"] == "unlink"
    assert not results.state(org, export).download_available
    with pytest.raises(AuthorizationDenied):
        results.download(org, export)
    with pytest.raises(RevisionConflict):
        service.review(org, contact.batch_id, request)
    with pytest.raises(AuthorizationDenied):
        service.review(scenario.organizations[1], contact.batch_id, request)
    assert not results.contacts(org, Filters(job_id=job)).items
    restored = service.review(
        org,
        contact.batch_id,
        Review(
            association_id=contact.association_id,
            expected_revision=association.revision,
            action="correct",
            author_id=contact.author_id,
            evidence_ids=contact.evidence_ids,
            reason="Synthetic review: restore supported association",
        ),
    )
    assert (
        next(a for a in restored.associations if a.id == contact.association_id).state == "accepted"
    )
    assert not results.state(org, export).download_available

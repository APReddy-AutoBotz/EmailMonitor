"""Actual runtime PostgreSQL and identifier-only API acceptance, synthetic only."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from api_client import APIClient
from emailmonitor.api import create_app
from emailmonitor.associations.models import Review
from emailmonitor.associations.service import Associations
from emailmonitor.config import Settings
from emailmonitor.discovery.service import Discovery
from emailmonitor.extraction.service import Extraction
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied, Database, RevisionConflict
from emailmonitor.organizations.roles import Capability
from sqlalchemy import Connection, create_engine, text
from test_durable_jobs import SETTINGS
from test_html_extraction_tenant import approved, extraction_policy, ready
from test_job_contracts import request_body
from test_source_foundation import source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario

URL = "https://synthetic.publisher.example/article-a.html"
TABLES = (
    "association_batches",
    "association_authors",
    "association_candidates",
    "association_evidence",
    "author_email_associations",
    "association_affiliations",
    "association_raw_variants",
    "association_author_evidence",
    "association_candidate_evidence",
    "association_evidence_links",
    "association_reviews",
    "association_review_evidence",
    "association_outbox",
)


def prepared(s: Scenario) -> tuple[Associations, UUID, UUID]:
    extraction, job = ready(s)
    extraction.fixture(s.organizations[0], job, URL, 3)
    service = Associations(extraction.database, extraction.token, SETTINGS)
    batch = service.derive(s.organizations[0], job, URL, 1)
    return service, job, batch


def review_request(service: Associations, org: UUID, batch: UUID, **changes: object) -> Review:
    item = service.detail(org, batch).associations[0]
    body: dict[str, object] = {
        "association_id": item.id,
        "expected_revision": item.revision,
        "action": "accept",
        "evidence_ids": item.evidence_ids,
        "reason": "Synthetic explicit correspondence evidence",
    }
    body.update(changes)
    return Review.model_validate(body)


def client(s: Scenario) -> APIClient:
    return APIClient(
        create_app(SETTINGS.model_copy(update={"identity_stub": True}), s.foundation),
        base_url=ORIGIN,
    )


def test_real_relational_receipts_replay_preserves_review_and_no_contact(
    scenario: Scenario,
) -> None:
    service, job, batch = prepared(scenario)
    org = scenario.organizations[0]
    first = service.detail(org, batch)
    assert first.associations[0].state == "accepted"
    assert [(a.first, a.corresponding) for a in first.authors] == [(True, None), (False, True)]
    revised = service.review(org, batch, review_request(service, org, batch, action="reject"))
    assert revised.associations[0].state == "rejected" and revised.associations[0].revision == 2
    assert service.derive(org, job, URL, 1) == batch
    assert service.detail(org, batch) == revised
    extraction = service.extraction
    empty_url = "https://synthetic.publisher.example/no-contact.html"
    extraction.fixture(org, job, empty_url, 3)
    empty = service.derive(org, job, empty_url, 1)
    assert service.detail(org, empty).observation_status == "no_contact"
    assert service.detail(org, empty).associations == ()
    with service.database.tenant(service.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text(
                    """
SELECT count(*) FROM emailmonitor.association_authors WHERE organization_id=:org AND
batch_id=:batch
                    """
                ),
                {"org": org, "batch": batch},
            ).scalar_one()
            == 2
        )
        assert (
            c.execute(
                text(
                    """
SELECT count(*) FROM emailmonitor.association_candidates WHERE organization_id=:org AND
batch_id=:batch
                    """
                ),
                {"org": org, "batch": batch},
            ).scalar_one()
            == 1
        )
        assert c.execute(
            text(
                """
SELECT count(*) FROM emailmonitor.association_evidence WHERE organization_id=:org AND
batch_id=:batch
                """
            ),
            {"org": org, "batch": batch},
        ).scalar_one() == len(first.evidence)
        assert (
            c.execute(
                text(
                    """
SELECT count(*) FROM emailmonitor.association_outbox WHERE organization_id=:org AND
batch_id=:batch
                    """
                ),
                {"org": org, "batch": batch},
            ).scalar_one()
            == 1
        )
        assert (
            c.execute(
                text(
                    """
SELECT event_type FROM emailmonitor.association_outbox WHERE organization_id=:org AND
batch_id=:batch
                    """
                ),
                {"org": org, "batch": batch},
            ).scalar_one()
            == "association.reviewed"
        )
        assert (
            c.execute(
                text(
                    """
SELECT count(*) FROM emailmonitor.audit_events WHERE organization_id=:org AND
action='association.reviewed'
                    """
                ),
                {"org": org},
            ).scalar_one()
            == 1
        )
    assert len(service.history(org, batch)) == 1


@pytest.mark.parametrize(
    "role,permitted",
    [
        ("owner", True),
        ("admin", True),
        ("data_steward", True),
        ("reviewer", True),
        ("operator", False),
        ("viewer", False),
    ],
)
def test_real_review_role_matrix_api_and_csrf(
    scenario: Scenario, role: str, permitted: bool
) -> None:
    service, job, batch = prepared(scenario)
    org = scenario.organizations[0]
    request = review_request(service, org, batch, action="reject").model_dump(mode="json")
    request["batch_id"] = str(batch)
    with client(scenario) as c:
        csrf = scenario.login(c, role)
        root = f"/api/v1/organizations/{org}"
        assert c.get(root + f"/association-batches/{batch}").status_code == 200
        assert c.get(root + f"/jobs/{job}/associations").status_code == 200
        assert c.post(root + "/reviews", json=request).status_code == 403
        response = c.post(
            root + "/reviews", headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}, json=request
        )
        assert response.status_code == (200 if permitted else 404), response.text
        assert service.detail(org, batch).associations[0].revision == (2 if permitted else 1)


def test_real_cross_tenant_pool_rls_and_catalog_permissions(scenario: Scenario) -> None:
    service, _, batch = prepared(scenario)
    org, other = scenario.organizations
    with client(scenario) as c:
        scenario.login(c, "owner_b")
        token = str(c.cookies[COOKIE])
        foreign = Associations(service.database, token, SETTINGS)
        with pytest.raises(AuthorizationDenied):
            foreign.detail(other, batch)
        with pytest.raises(AuthorizationDenied):
            foreign.detail(org, batch)
        with service.database.tenant(token, other, Capability.READ_ORGANIZATION) as (connection, _):
            for table in TABLES:
                assert (
                    connection.execute(
                        text(
                            f"SELECT count(*) FROM emailmonitor.{table} WHERE organization_id=:org"
                        ),
                        {"org": org},
                    ).scalar_one()
                    == 0
                )
                assert connection.execute(
                    text(
                        """
SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=CAST(:table AS regclass)
                        """
                    ),
                    {"table": "emailmonitor." + table},
                ).scalar_one()
                assert not connection.execute(
                    text("SELECT has_table_privilege(current_user,:table,'UPDATE')"),
                    {"table": "emailmonitor." + table},
                ).scalar_one()
            assert not connection.execute(
                text(
                    """
SELECT
has_function_privilege(current_user,'emailmonitor.association_parent_fence(uuid,uuid,text,bigint,boolean)','EXECUTE')
                    """
                )
            ).scalar_one()
            assert not connection.execute(
                text(
                    """
SELECT has_table_privilege(current_user,'emailmonitor.source_catalog','UPDATE')
                    """
                )
            ).scalar_one()
    assert service.detail(org, batch).organization_id == org


def test_real_correction_history_and_citations_no_free_address(scenario: Scenario) -> None:
    service, _, batch = prepared(scenario)
    org = scenario.organizations[0]
    bundle = service.detail(org, batch)
    cited = tuple(
        dict.fromkeys((*bundle.candidates[0].evidence_ids, *bundle.authors[0].evidence_ids))
    )
    value = service.review(
        org,
        batch,
        review_request(
            service,
            org,
            batch,
            action="correct",
            author_id=bundle.authors[0].id,
            evidence_ids=cited,
        ),
    )
    assert (
        value.associations[0].author_id == value.authors[0].id
        and value.associations[0].revision == 2
    )
    assert value.authors == bundle.authors and value.candidates == bundle.candidates
    assert service.history(org, batch)[0]["expected_revision"] == 1
    with client(scenario) as c:
        csrf = scenario.login(c, "reviewer")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        request = review_request(service, org, batch).model_dump(mode="json")
        request["batch_id"] = str(batch)
        assert (
            c.post(
                f"/api/v1/organizations/{org}/reviews",
                headers=headers,
                json={**request, "raw_address": "unobserved@example.org"},
            ).status_code
            == 422
        )
        assert (
            c.post(
                f"/api/v1/organizations/{org}/reviews",
                headers=headers,
                json={**request, "evidence_ids": [str(uuid4())]},
            ).status_code
            == 422
        )
    assert service.detail(org, batch).associations[0].revision == 2


def test_real_cancel_preserves_permitted_receipts_but_fences_new_ingestion(
    scenario: Scenario,
) -> None:
    service, job, batch = prepared(scenario)
    org = scenario.organizations[0]
    with service.database.tenant(service.token, org, Capability.READ_ORGANIZATION) as (c, _):
        revision: int = c.execute(
            text(
                "SELECT row_version FROM emailmonitor.jobs WHERE organization_id=:org AND id=:job"
            ),
            {"org": org, "job": job},
        ).scalar_one()
    Ledger(service.database, service.token, SETTINGS).control(org, job, "cancel", revision)
    assert service.detail(org, batch).associations[0].state == "accepted"
    assert (
        service.review(org, batch, review_request(service, org, batch, action="reject"))
        .associations[0]
        .state
        == "rejected"
    )
    with pytest.raises(AuthorizationDenied):
        service.derive(org, job, URL, 1)


@pytest.mark.parametrize("action", ["revoke", "expire", "offboard", "membership"])
def test_real_current_source_lifecycle_membership_denials(scenario: Scenario, action: str) -> None:
    service, _, batch = prepared(scenario)
    org = scenario.organizations[0]
    with client(scenario) as c:
        csrf = scenario.login(c, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        if action == "revoke":
            result = c.post(
                source_path(scenario) + "/policy-state",
                headers=headers,
                json={
                    "expected_version": 1,
                    "expected_revision": 2,
                    "state": "revoked",
                },
            )
        elif action == "expire":
            admin = create_engine(scenario.admin_url)
            try:
                with admin.begin() as connection:
                    connection.execute(text("SET LOCAL ROLE emailmonitor_owner"))
                    connection.execute(
                        text(
                            """
UPDATE emailmonitor.source_policies SET state='expired' WHERE organization_id=:org AND
source_id='synthetic-publisher' AND version=1
                            """
                        ),
                        {"org": org},
                    )
            finally:
                admin.dispose()
            result = None
        elif action == "offboard":
            result = c.post(
                f"/api/v1/organizations/{org}/lifecycle",
                headers=headers,
                json={"expected_revision": 1, "status": "offboarding"},
            )
        else:
            scenario.login(c, "reviewer")
            reviewer = Associations(service.database, str(c.cookies[COOKIE]), SETTINGS)
            csrf = scenario.login(c, "owner")
            result = c.patch(
                f"/api/v1/organizations/{org}/members/{scenario.identities['reviewer']}",
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                json={"expected_revision": 1, "role": "reviewer", "status": "revoked"},
            )
            assert result.status_code == 200, result.text
            with pytest.raises(AuthorizationDenied):
                reviewer.detail(org, batch)
            return
        if result is not None:
            assert result.status_code == 200, result.text
    with pytest.raises(AuthorizationDenied):
        service.detail(org, batch)
    with pytest.raises(AuthorizationDenied):
        service.review(
            org,
            batch,
            Review(
                association_id=UUID(int=1),
                expected_revision=1,
                action="reject",
                evidence_ids=(UUID(int=2),),
                reason="Synthetic current fence",
            ),
        )


def test_real_concurrent_reviews_one_revision_and_one_atomic_receipt(scenario: Scenario) -> None:
    service, _, batch = prepared(scenario)
    org = scenario.organizations[0]
    request = review_request(service, org, batch, action="reject")
    other = Database(service.database.engine.url.render_as_string(hide_password=False))
    barrier = Barrier(2)

    def invoke(database: Database) -> str:
        barrier.wait(timeout=10)
        try:
            Associations(database, service.token, SETTINGS).review(org, batch, request)
            return "committed"
        except RevisionConflict:
            return "conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(invoke, database) for database in (service.database, other)]
            assert sorted(f.result(timeout=20) for f in futures) == ["committed", "conflict"]
        assert service.detail(org, batch).associations[0].revision == 2
        assert len(service.history(org, batch)) == 1
    finally:
        other.engine.dispose()


def test_real_production_cannot_read_or_review_synthetic_associations(scenario: Scenario) -> None:
    service, _, batch = prepared(scenario)
    with pytest.raises(FetchDenied):
        Associations(service.database, service.token, Settings(environment="production"))


def test_real_ordinary_operator_derives_with_no_catalog_or_receipt_update_grant(
    scenario: Scenario,
) -> None:
    approved(scenario)
    org = scenario.organizations[0]
    with client(scenario) as c:
        scenario.login(c, "operator")
        token = str(c.cookies[COOKIE])
        body = request_body()
        body["input"] = {"type": "url", "url": URL}
        ledger = Ledger(scenario.foundation.database, token, SETTINGS)
        job = ledger.create(org, JobRequest.model_validate(body), str(uuid4()))
        discovery = Discovery(ledger.database, token, SETTINGS)
        plan = discovery.plan(org, job, 1)
        extraction = Extraction(ledger.database, token, SETTINGS)
        extraction.fixture(org, job, URL, int(str(plan["revision"])))
        service = Associations(ledger.database, token, SETTINGS)
        batch = service.derive(org, job, URL, 1)
        assert service.detail(org, batch).associations[0].state == "accepted"
        with ledger.database.tenant(token, org, Capability.READ_ORGANIZATION) as (connection, _):
            assert not connection.execute(
                text(
                    """
SELECT has_table_privilege(current_user,'emailmonitor.source_catalog','UPDATE')
                    """
                )
            ).scalar_one()


def test_real_new_policy_version_invalidates_old_receipt_without_implicit_reapproval(
    scenario: Scenario,
) -> None:
    service, job, batch = prepared(scenario)
    org = scenario.organizations[0]
    with client(scenario) as c:
        csrf = scenario.login(c, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(scenario)
        assert (
            c.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 1, "policy": extraction_policy()},
            ).status_code
            == 201
        )
        assert (
            c.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 2, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 200
        )
    with pytest.raises(AuthorizationDenied):
        service.detail(org, batch)

    assert service.batches(org, job) == []
    with service.discovery._tenant(org, Capability.READ_ORGANIZATION) as (connection, _):
        for table in TABLES:
            assert (
                connection.execute(
                    text(f"SELECT count(*) FROM emailmonitor.{table} WHERE organization_id=:org"),
                    {"org": org},
                ).scalar_one()
                == 0
            )


def test_real_source_disable_and_clock_expired_session_refuse_current_read(
    scenario: Scenario,
) -> None:
    service, _, batch = prepared(scenario)
    org = scenario.organizations[0]
    admin = create_engine(scenario.admin_url)
    try:
        with admin.begin() as connection:
            connection.execute(text("SET LOCAL ROLE emailmonitor_owner"))
            connection.execute(
                text(
                    """
UPDATE emailmonitor.source_catalog SET enabled=false WHERE source_id='synthetic-publisher'
                    """
                )
            )
        with pytest.raises(AuthorizationDenied):
            service.detail(org, batch)
        with admin.begin() as connection:
            connection.execute(text("SET LOCAL ROLE emailmonitor_owner"))
            connection.execute(
                text(
                    """
UPDATE emailmonitor.source_catalog SET enabled=true WHERE source_id='synthetic-publisher'
                    """
                )
            )
        assert service.detail(org, batch).associations[0].state == "accepted"
        from emailmonitor.organizations.database import digest

        with admin.begin() as connection:
            connection.execute(
                text(
                    """
UPDATE emailmonitor.sessions SET expires_at=clock_timestamp() WHERE token_hash=:token
                    """
                ),
                {"token": digest(service.token)},
            )
        with pytest.raises(AuthorizationDenied):
            service.detail(org, batch)
    finally:
        with admin.begin() as connection:
            connection.execute(text("SET LOCAL ROLE emailmonitor_owner"))
            connection.execute(
                text(
                    """
UPDATE emailmonitor.source_catalog SET enabled=true WHERE source_id='synthetic-publisher'
                    """
                )
            )
        admin.dispose()


def test_real_atomic_derivation_and_review_rollback(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    extraction, job = ready(scenario)
    org = scenario.organizations[0]
    extraction.fixture(org, job, URL, 3)
    service = Associations(extraction.database, extraction.token, SETTINGS)
    original = Associations._bundle

    def refuse_release(self: Associations, *args: object, **kwargs: object) -> None:
        raise ValueError("Synthetic post-write release failure")

    monkeypatch.setattr(Associations, "_bundle", refuse_release)
    with pytest.raises(ValueError, match="post-write"):
        service.derive(org, job, URL, 1)
    monkeypatch.setattr(Associations, "_bundle", original)
    assert service.batches(org, job) == []
    batch = service.derive(org, job, URL, 1)
    before = service.detail(org, batch)
    request = review_request(service, org, batch, action="reject")
    calls = 0

    def fail_second_release(
        self: Associations, connection: Connection, organization: UUID, batch_id: UUID
    ) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("Synthetic post-write release failure")
        return original(self, connection, organization, batch_id)

    monkeypatch.setattr(Associations, "_bundle", fail_second_release)
    with pytest.raises(ValueError, match="post-write"):
        service.review(org, batch, request)
    monkeypatch.setattr(Associations, "_bundle", original)
    assert service.detail(org, batch) == before
    assert service.history(org, batch) == []
    with service.discovery._tenant(org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text("SELECT count(*) FROM emailmonitor.association_outbox WHERE batch_id=:batch"),
                {"batch": batch},
            ).scalar_one()
            == 0
        )

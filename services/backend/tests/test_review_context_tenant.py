"""Real disposable PostgreSQL tests for transient review context."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from uuid import UUID, uuid4

import pytest
from emailmonitor.associations.models import Bundle
from emailmonitor.associations.service import Associations
from emailmonitor.discovery.fixture import step_fixture
from emailmonitor.discovery.service import Discovery
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.lifecycle.models import DeletionRequest
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied, Database
from emailmonitor.results.models import Filters
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError
from test_association_tenant import client
from test_durable_jobs import SETTINGS
from test_html_extraction_tenant import ready
from test_job_contracts import request_body
from test_results_tenant import prepared as results_prepared
from test_results_tenant import ready as ready_export
from test_source_foundation import source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario

A = "https://synthetic.publisher.example/article-a.html"
B = "https://synthetic.publisher.example/article-b.html"


def prepared(s: Scenario) -> tuple[Associations, UUID, UUID, UUID, UUID]:
    extraction, target_job = ready(s)
    org = s.organizations[0]
    extraction.fixture(org, target_job, A, 3)
    service = Associations(extraction.database, extraction.token, SETTINGS)
    target = service.derive(org, target_job, A, 1)
    source_job, source = make_source(service, org)
    return service, target_job, target, source_job, source


def make_source(service: Associations, org: UUID) -> tuple[UUID, UUID]:
    body = request_body()
    body["input"] = {
        "type": "keyword",
        "source_id": "synthetic-publisher",
        "original_query": "Myocardial Infarction",
    }
    body["options"] = {"max_articles": 500, "max_search_pages": 100, "author_target": "both"}
    ledger = Ledger(service.database, service.token, SETTINGS)
    source_job = ledger.create(org, JobRequest.model_validate(body), str(uuid4()))
    discovery = Discovery(service.database, service.token, SETTINGS)
    discovery.plan(org, source_job, 1)
    step_fixture(discovery, org, source_job, 1)
    step_fixture(discovery, org, source_job, 2)
    service.extraction.fixture(org, source_job, B, 3)
    source = service.derive(org, source_job, B, 1)
    return source_job, source


def test_real_context_audits_without_mutating_either_review_or_evidence(scenario: Scenario) -> None:
    service, _, target, _, source = prepared(scenario)
    org = scenario.organizations[0]
    before_target, before_source = service.detail(org, target), service.detail(org, source)
    selected, citation = before_target.associations[0], before_source.evidence[0]
    view = service.context_view(org, target, selected.id, selected.revision, source, citation.id)
    assert view.evidence == citation and not view.attached and not view.identity_verified
    assert not view.acceptance_changed and not view.export_changed
    assert (
        service.detail(org, target) == before_target
        and service.detail(org, source) == before_source
    )
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.connect() as c:
            rows = c.execute(
                text("""SELECT action,resource_id FROM emailmonitor.audit_events
                WHERE organization_id=:org AND action IN
                ('association.context_target_viewed','association.context_evidence_viewed')"""),
                {"org": org},
            ).all()
        assert set(rows) == {
            ("association.context_target_viewed", selected.id),
            ("association.context_evidence_viewed", citation.id),
        }
    finally:
        admin.dispose()


def test_real_context_does_not_change_existing_export(scenario: Scenario) -> None:
    results, target_job = results_prepared(scenario)
    org = scenario.organizations[0]
    contact = results.contacts(org, Filters(job_id=target_job)).items[0]
    service = Associations(results.database, results.token, SETTINGS)
    _, source = make_source(service, org)
    evidence = service.detail(org, source).evidence[0]
    export = ready_export(results, org, target_job)
    before = results.download(org, export).body
    service.context_view(
        org, contact.batch_id, contact.association_id, contact.revision, source, evidence.id
    )
    assert results.download(org, export).body == before
    assert results.contacts(org, Filters(job_id=target_job)).items[0] == contact


def test_real_context_uses_reviewer_capability_and_rejects_cross_tenant(scenario: Scenario) -> None:
    service, _, target, _, source = prepared(scenario)
    org = scenario.organizations[0]
    target_record, source_record = service.detail(org, target), service.detail(org, source)
    association, citation = target_record.associations[0], source_record.evidence[0]
    with pytest.raises(AuthorizationDenied):
        service.context_view(
            scenario.organizations[1], target, association.id, 1, source, citation.id
        )
    with client(scenario) as browser:
        csrf = scenario.login(browser, "viewer")
        response = browser.post(
            f"/api/v1/organizations/{org}/review-context/view",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={
                "target_batch_id": str(target),
                "target_association_id": str(association.id),
                "expected_revision": association.revision,
                "source_batch_id": str(source),
                "source_evidence_id": str(citation.id),
            },
        )
        assert response.status_code in (403, 404)
    with client(scenario) as browser:
        csrf = scenario.login(browser, "reviewer")
        response = browser.post(
            f"/api/v1/organizations/{org}/review-context/view",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={
                "target_batch_id": str(target),
                "target_association_id": str(association.id),
                "expected_revision": association.revision,
                "source_batch_id": str(source),
                "source_evidence_id": str(citation.id),
            },
        )
        assert response.status_code == 200 and response.json()["attached"] is False


def test_real_foreign_source_batch_cannot_be_read_from_valid_target(scenario: Scenario) -> None:
    service, _, target, _, _ = prepared(scenario)
    org, foreign_org = scenario.organizations
    selected = service.detail(org, target).associations[0]
    identities = dict(scenario.identities)
    identities["owner"], identities["owner_b"] = identities["owner_b"], identities["owner"]
    foreign = replace(scenario, organizations=(foreign_org, org), identities=identities)
    foreign_service, _, _, _, foreign_batch = prepared(foreign)
    foreign_evidence = foreign_service.detail(foreign_org, foreign_batch).evidence[0]
    with pytest.raises(AuthorizationDenied):
        service.context_view(
            org, target, selected.id, selected.revision, foreign_batch, foreign_evidence.id
        )


def test_real_audit_failure_rolls_back_both_events_and_does_not_change_reviews(
    scenario: Scenario,
) -> None:
    service, _, target, _, source = prepared(scenario)
    org = scenario.organizations[0]
    before_target, before_source = service.detail(org, target), service.detail(org, source)
    association, citation = before_target.associations[0], before_source.evidence[0]
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.begin() as c:
            c.execute(
                text("""CREATE FUNCTION emailmonitor.test_context_audit_refusal()
                RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                IF NEW.action='association.context_evidence_viewed' THEN
                 RAISE EXCEPTION 'synthetic_audit_refusal'; END IF;
                RETURN NEW; END $$""")
            )
            c.execute(
                text("""CREATE TRIGGER test_context_audit_refusal BEFORE INSERT ON
                emailmonitor.audit_events FOR EACH ROW EXECUTE FUNCTION
                emailmonitor.test_context_audit_refusal()""")
            )
        with pytest.raises(DBAPIError):
            service.context_view(org, target, association.id, 1, source, citation.id)
        with admin.connect() as c:
            assert (
                c.execute(
                    text("""SELECT count(*) FROM emailmonitor.audit_events
                WHERE organization_id=:org AND action IN
                ('association.context_target_viewed','association.context_evidence_viewed')"""),
                    {"org": org},
                ).scalar_one()
                == 0
            )
        assert (
            service.detail(org, target) == before_target
            and service.detail(org, source) == before_source
        )
    finally:
        with admin.begin() as c:
            c.execute(
                text(
                    "DROP TRIGGER IF EXISTS test_context_audit_refusal ON emailmonitor.audit_events"
                )
            )
            c.execute(text("DROP FUNCTION IF EXISTS emailmonitor.test_context_audit_refusal()"))
        admin.dispose()


def test_real_source_deletion_fences_context_and_purge_has_no_cross_batch_reference(
    scenario: Scenario,
) -> None:
    service, _, target, source_job, source = prepared(scenario)
    org = scenario.organizations[0]
    original = service.detail(org, target)
    selected = original.associations[0]
    citation = service.detail(org, source).evidence[0]
    service.context_view(org, target, selected.id, selected.revision, source, citation.id)
    lifecycle = Lifecycle(service.database, service.token, SETTINGS)
    staged = lifecycle.stage(org, DeletionRequest(job_id=source_job, reason="owner_request"))
    with pytest.raises(AuthorizationDenied):
        service.context_view(org, target, selected.id, selected.revision, source, citation.id)
    assert lifecycle.purge(org, staged.id).stage == "purged"
    assert service.detail(org, target) == original


def test_real_source_deletion_refuses_during_context_fence(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, target, source_job, source = prepared(scenario)
    org = scenario.organizations[0]
    selected = service.detail(org, target).associations[0]
    citation = service.detail(org, source).evidence[0]
    second = Database(os.environ["EM_TEST_DATABASE_URL"])
    lifecycle = Lifecycle(second, service.token, SETTINGS)
    locked, release = Event(), Event()
    original = service._bundle

    def held(c: Connection, organization: UUID, batch: UUID) -> Bundle:
        result = original(c, organization, batch)
        if batch == source and not locked.is_set():
            locked.set()
            if not release.wait(5):
                raise TimeoutError("synthetic barrier timed out")
        return result

    monkeypatch.setattr(service, "_bundle", held)
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(
                service.context_view,
                org,
                target,
                selected.id,
                selected.revision,
                source,
                citation.id,
            )
            assert locked.wait(5)
            try:
                with pytest.raises(DBAPIError) as failure:
                    lifecycle.stage(org, DeletionRequest(job_id=source_job, reason="owner_request"))
                args = getattr(failure.value.orig, "args", ())
                assert args and isinstance(args[0], dict) and args[0].get("C") == "55P03"
            finally:
                release.set()
            assert future.result(timeout=5).attached is False
        assert (
            lifecycle.stage(org, DeletionRequest(job_id=source_job, reason="owner_request")).stage
            == "fenced"
        )
    finally:
        release.set()
        second.engine.dispose()


def test_real_source_policy_revocation_refuses_later_context(scenario: Scenario) -> None:
    service, _, target, _, source = prepared(scenario)
    org = scenario.organizations[0]
    target_row = service.detail(org, target).associations[0]
    evidence = service.detail(org, source).evidence[0]
    assert (
        service.context_view(org, target, target_row.id, 1, source, evidence.id).attached is False
    )
    with client(scenario) as browser:
        csrf = scenario.login(browser, "owner")
        response = browser.post(
            source_path(scenario) + "/policy-state",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
        )
        assert response.status_code == 200
    with pytest.raises(AuthorizationDenied):
        service.context_view(org, target, target_row.id, 1, source, evidence.id)


def test_real_reviewer_revocation_cannot_cross_active_context_read(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _, target, _, source = prepared(scenario)
    org = scenario.organizations[0]
    selected = service.detail(org, target).associations[0]
    evidence = service.detail(org, source).evidence[0]
    with client(scenario) as reviewer_browser, client(scenario) as owner_browser:
        scenario.login(reviewer_browser, "reviewer")
        reviewer = Associations(service.database, str(reviewer_browser.cookies[COOKIE]), SETTINGS)
        owner_csrf = scenario.login(owner_browser, "owner")
        admin = create_engine(scenario.admin_url, hide_parameters=True)
        locked, release = Event(), Event()
        original = reviewer._bundle

        def held(c: Connection, organization: UUID, batch: UUID) -> Bundle:
            result = original(c, organization, batch)
            if batch == source and not locked.is_set():
                locked.set()
                if not release.wait(5):
                    raise TimeoutError("synthetic barrier timed out")
            return result

        monkeypatch.setattr(reviewer, "_bundle", held)
        try:
            with ThreadPoolExecutor(max_workers=1) as workers:
                future = workers.submit(
                    reviewer.context_view,
                    org,
                    target,
                    selected.id,
                    selected.revision,
                    source,
                    evidence.id,
                )
                assert locked.wait(5)
                try:
                    with pytest.raises(DBAPIError) as failure:
                        with admin.begin() as c:
                            c.execute(
                                text("""SELECT identity_id FROM emailmonitor.memberships
                                WHERE organization_id=:org AND identity_id=:identity
                                FOR UPDATE NOWAIT"""),
                                {"org": org, "identity": scenario.identities["reviewer"]},
                            )
                    args = getattr(failure.value.orig, "args", ())
                    assert args and isinstance(args[0], dict) and args[0].get("C") == "55P03"
                finally:
                    release.set()
                assert future.result(timeout=5).attached is False
            response = owner_browser.patch(
                f"/api/v1/organizations/{org}/members/{scenario.identities['reviewer']}",
                headers={"Origin": ORIGIN, "X-CSRF-Token": owner_csrf},
                json={"expected_revision": 1, "role": "reviewer", "status": "revoked"},
            )
            assert response.status_code == 200
            with pytest.raises(AuthorizationDenied):
                reviewer.context_view(
                    org, target, selected.id, selected.revision, source, evidence.id
                )
        finally:
            release.set()
            admin.dispose()

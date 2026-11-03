"""Connected lifecycle fixture contracts; real database, no new runtime authority."""

from collections.abc import Sequence
from time import monotonic
from typing import Literal
from uuid import UUID, uuid4

import pytest
from emailmonitor.administration.service import Administration
from emailmonitor.discovery.service import Discovery
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.service import Progress, Work
from emailmonitor.results.models import ExportInput, Filters
from emailmonitor.results.service import Results
from sqlalchemy import text
from test_association_tenant import review_request
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_progress_tenant import claim, drain, planned
from test_results_tenant import lease
from test_selection_handoff_tenant import rows
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def article_work(progress: Progress, org: UUID, job: UUID, name: str) -> Work:
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        item: UUID = c.execute(
            text(
                "SELECT id FROM emailmonitor.execution_items WHERE organization_id=:org "
                "AND job_id=:job AND input_url=:url AND work_kind='article'"
            ),
            {"org": org, "job": job, "url": "https://synthetic.publisher.example/" + name},
        ).scalar_one()
    row = next(row for row in progress.pending(org) if row["item_id"] == item)
    work = progress.claim(org, job, item, UUID(str(row["event_id"])))
    assert work is not None
    return work


def retained_job(s: Scenario, existing: Progress | None = None) -> tuple[Progress, UUID]:
    if existing is None:
        progress, job = planned(s)
    else:
        progress = existing
        body = request_body()
        body["input"] = {
            "type": "keyword",
            "source_id": "synthetic-publisher",
            "original_query": "Myocardial Infarction",
        }
        body["options"] = {"max_articles": 500, "max_search_pages": 100, "author_target": "both"}
        ledger = Ledger(progress.database, progress.token, SETTINGS)
        job = ledger.create(s.organizations[0], JobRequest.model_validate(body), str(uuid4()))
        Discovery(progress.database, progress.token, SETTINGS).plan(s.organizations[0], job, 1)
    org = s.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    progress.process_fixture(claim(progress, org, job))
    progress.process_fixture(article_work(progress, org, job, "article-a.html"))
    assert progress.snapshot(org, job).accepted_associations == 1
    return progress, job


def failed_job(s: Scenario, existing: Progress | None = None) -> tuple[Progress, UUID]:
    progress, job = retained_job(s, existing)
    org = s.organizations[0]
    for attempt in range(3):
        outcome = progress.finish(
            article_work(progress, org, job, "article-b.html"), failure="worker_failure"
        )
        assert outcome == ("failed" if attempt == 2 else "retry_wait")
    drain(progress, org, job)
    assert progress.snapshot(org, job).state == "completed_partial"
    return progress, job


@pytest.mark.parametrize("format", ["csv", "xlsx"])
def test_confirmed_cancel_preserves_review_export_and_refuses_retry(
    scenario: Scenario, format: Literal["csv", "xlsx"]
) -> None:
    progress, job = retained_job(scenario)
    org = scenario.organizations[0]
    old = article_work(progress, org, job, "article-b.html")
    before = progress.snapshot(org, job)
    started = monotonic()
    progress.control(org, job, before.revision, "pause")
    assert monotonic() - started <= 2
    paused = progress.snapshot(org, job)
    assert paused.generation == before.generation + 1 and paused.state == "paused"
    assert not [r for r in progress.pending(org) if r["job_id"] == job]
    with pytest.raises(AuthorizationDenied):
        progress.finish(old)
    with pytest.raises(RevisionConflict):
        progress.control(org, job, before.revision, "resume")
    progress.control(org, job, paused.revision, "resume")
    active = article_work(progress, org, job, "article-b.html")
    current = progress.snapshot(org, job)
    started = monotonic()
    progress.control(org, job, current.revision, "cancel")
    assert monotonic() - started <= 2
    cancelled = progress.snapshot(org, job)
    assert cancelled.state == "cancelled" and cancelled.generation == current.generation + 1
    assert not [r for r in progress.pending(org) if r["job_id"] == job]
    with pytest.raises(AuthorizationDenied):
        progress.finish(active)
    with pytest.raises(AuthorizationDenied):
        progress.retry(org, job, cancelled.revision)
    progress.reconcile(org, job)
    assert progress.snapshot(org, job) == cancelled
    results = Results(progress.database, progress.token, SETTINGS)
    contacts = results.contacts(org, Filters(job_id=job)).items
    assert len(contacts) == 1
    batch = contacts[0].batch_id
    detail = progress.associations.detail(org, batch)
    progress.associations.review(org, batch, review_request(progress.associations, org, batch))
    assert progress.associations.detail(org, batch).evidence == detail.evidence
    request = ExportInput(format=format, purpose="academic_contact_research", job_id=job)
    assert results.preview(org, request).contacts == 1
    key = str(uuid4())
    export = results.create(org, request, key)
    assert results.create(org, request, key).id == export.id
    assert results.process(lease(results, org, export.id))
    artifact = rows(results.download(org, export.id).body, format, False)
    assert len(artifact) == 2 and contacts[0].raw_address in artifact[1]
    with pytest.raises(AuthorizationDenied):
        results.preview(scenario.organizations[1], request)
    usage = Administration(progress.database, progress.token, SETTINGS).usage(org)
    assert usage.settled_resolution_units == 1 and usage.reserved_resolution_units == 0


def test_continuation_only_failed_work_and_original_immutable(scenario: Scenario) -> None:
    progress, job = failed_job(scenario)
    org = scenario.organizations[0]
    original = progress.snapshot(org, job)
    retained = progress.extraction.read(org, job)
    with pytest.raises(RevisionConflict):
        progress.retry(org, job, original.revision - 1)
    child = progress.retry(org, job, original.revision)
    assert child != job and progress.retry(org, job, original.revision) == child
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        urls: Sequence[str] = (
            c.execute(
                text(
                    "SELECT input_url FROM emailmonitor.execution_items "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": child},
            )
            .scalars()
            .all()
        )
        assert urls == ["https://synthetic.publisher.example/article-b.html"]
    drain(progress, org, child)
    assert progress.snapshot(org, child).state == "completed"
    assert progress.snapshot(org, job) == original
    assert progress.extraction.read(org, job) == retained
    assert progress.retry(org, job, original.revision) == child


@pytest.mark.parametrize("refusal", ["viewer", "session", "source", "tenant"])
def test_continuation_current_authority_refusal_does_not_create_child(
    scenario: Scenario, refusal: str
) -> None:
    from emailmonitor.identity.foundation import COOKIE
    from sqlalchemy import create_engine
    from test_source_foundation import source_path
    from test_tenant_foundation import ORIGIN

    progress, job = failed_job(scenario)
    org = scenario.organizations[0]
    original = progress.snapshot(org, job)
    with scenario.client() as client:
        nonce = scenario.login(client, "viewer" if refusal == "viewer" else "owner")
        current = Progress(progress.database, str(client.cookies[COOKIE]), SETTINGS)
        headers = {"Origin": ORIGIN, "X-CSRF-Token": nonce}
        if refusal == "session":
            assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
        elif refusal == "source":
            response = client.post(
                source_path(scenario) + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
            )
            assert response.status_code == 200
        with pytest.raises(AuthorizationDenied):
            current.retry(
                scenario.organizations[1] if refusal == "tenant" else org, job, original.revision
            )
    engine = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with engine.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.execution_runs "
                        "WHERE organization_id=:org AND retry_from=:job"
                    ),
                    {"org": org, "job": job},
                ).scalar_one()
                == 0
            )
            row = c.execute(
                text(
                    "SELECT state,generation,row_version FROM emailmonitor.jobs "
                    "WHERE organization_id=:org AND id=:job"
                ),
                {"org": org, "job": job},
            ).one()
            assert tuple(row) == (original.state, original.generation, original.revision)
    finally:
        engine.dispose()


def test_independent_lifecycle_fixtures_share_existing_policy_without_new_approval(
    scenario: Scenario,
) -> None:
    progress, cancelled_candidate = retained_job(scenario)
    old = article_work(progress, scenario.organizations[0], cancelled_candidate, "article-b.html")
    _, failed = failed_job(scenario, progress)
    assert progress.snapshot(scenario.organizations[0], cancelled_candidate).state == "running"
    assert progress.snapshot(scenario.organizations[0], failed).state == "completed_partial"
    assert old.lease.job == cancelled_candidate

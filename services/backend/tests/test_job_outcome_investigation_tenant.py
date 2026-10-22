"""Actual authorized outcome paging; fixed authored routes, no widened source grants."""

from typing import Literal
from uuid import UUID, uuid4

import pytest
from emailmonitor.associations.service import Associations
from emailmonitor.discovery.service import Discovery
from emailmonitor.jobs.models import JobRequest
from emailmonitor.progress.service import Progress
from emailmonitor.results.models import Filters
from emailmonitor.results.service import Results
from test_association_tenant import client
from test_durable_jobs import SETTINGS
from test_html_extraction_tenant import approved
from test_job_contracts import request_body
from test_progress_tenant import drain
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def test_actual_more_than_100_outcomes_have_no_omissions_or_duplicates(scenario: Scenario) -> None:
    # A job has at most seven allowed authored article routes. Exercise 104 actual
    # outcomes across 26 jobs rather than bypassing that production constraint.
    ledger = approved(scenario)
    org = scenario.organizations[0]
    discovery = Discovery(ledger.database, ledger.token, SETTINGS)
    progress = Progress(ledger.database, ledger.token, SETTINGS)
    results = Results(ledger.database, ledger.token, SETTINGS)
    body = request_body()
    body["input"] = {
        "type": "keyword",
        "source_id": "synthetic-publisher",
        "original_query": "Myocardial Infarction",
    }
    expected: set[tuple[UUID, UUID]] = set()
    jobs = []
    for _ in range(26):
        job = ledger.create(org, JobRequest.model_validate(body), str(uuid4()))
        discovery.plan(org, job, 1)
        progress.start(org, job, progress.snapshot(org, job).revision)
        drain(progress, org, job)
        jobs.append(job)
        rows = results.outcomes(org, job, limit=25)
        assert len(rows.items) == 4 and rows.next_cursor is None
        assert {row.state for row in rows.items} >= {"no_contact", "unsupported"}
        expected.update((row.job_id, row.item_id) for row in rows.items)
    assert len(expected) == 104
    with client(scenario) as api:
        scenario.login(api, "viewer")
        path = f"/api/v1/organizations/{org}/article-outcomes"
        cursor = None
        seen: list[tuple[str, str]] = []
        sizes = []
        for _ in range(5):
            params = {"limit": 25}
            if cursor:
                params["cursor"] = cursor
            response = api.get(path, params=params)
            assert response.status_code == 200, response.text
            data = response.json()
            sizes.append(len(data["items"]))
            seen.extend((row["job_id"], row["item_id"]) for row in data["items"])
            cursor = data["next_cursor"]
        assert sizes == [25, 25, 25, 25, 4] and cursor is None
        assert len(seen) == len(set(seen)) == 104
        assert set(seen) == {(str(job), str(item)) for job, item in expected}
        assert seen == sorted(seen)
        first = api.get(path, params={"job_id": str(jobs[0]), "limit": 1}).json()
        scoped = first["next_cursor"]
        assert scoped is not None
        assert api.get(path, params={"job_id": str(jobs[1]), "cursor": scoped}).status_code == 422
        assert api.get(path, params={"cursor": scoped}).status_code == 422
        other = path.replace(str(org), str(scenario.organizations[1]))
        assert api.get(other, params={"job_id": str(jobs[0]), "cursor": scoped}).status_code in {
            404,
            422,
        }
        # Results never need a contact row to identify a retained no-contact batch.
        empty = next(
            row for row in results.outcomes(org, jobs[0]).items if row.state == "no_contact"
        )
        assert empty.batch_id is not None
        assert results.contacts(org, Filters(job_id=jobs[0], query="Leena Shah")).items == ()
        detail = Associations(ledger.database, ledger.token, SETTINGS).detail(org, empty.batch_id)
        assert detail.candidates == ()
        quality = api.get(
            f"/api/v1/organizations/{org}/association-batches/{empty.batch_id}/observation-quality"
        )
        assert quality.status_code == 200
        assert quality.json()["observation_status"] == "no_contact"


@pytest.mark.parametrize(
    "failure,state", [("worker_failure", "failed"), ("source_policy_changed", "policy_blocked")]
)
def test_actual_failed_or_blocked_outcome_without_batch_is_retained(
    scenario: Scenario, failure: Literal["worker_failure", "source_policy_changed"], state: str
) -> None:
    from test_progress_tenant import claim, planned

    progress, job = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    for _ in range(3 if failure == "worker_failure" else 1):
        progress.finish(claim(progress, org, job), failure=failure)
    results = Results(progress.database, progress.token, SETTINGS)
    outcome = results.outcomes(org, job, limit=25).items[0]
    assert outcome.state == state and outcome.batch_id is None
    assert outcome.observation_status is None
    assert results.contacts(org, Filters(job_id=job)).items == ()


@pytest.mark.parametrize("fence", ["policy", "session", "deletion", "excerpt_days", "contact_days"])
def test_actual_retained_outcome_and_batch_recheck_current_fences(
    scenario: Scenario, fence: str
) -> None:
    from emailmonitor.lifecycle.models import DeletionRequest, Retention, RetentionUpdate
    from emailmonitor.lifecycle.service import Lifecycle
    from emailmonitor.organizations.database import AuthorizationDenied
    from sqlalchemy import create_engine, text
    from test_results_tenant import prepared

    results, job = prepared(scenario)
    org = scenario.organizations[0]
    associations = Associations(results.database, results.token, SETTINGS)
    before = results.outcomes(org, job, limit=25)
    assert len(before.items) == 1 and before.items[0].batch_id is not None
    batch = before.items[0].batch_id
    assert associations.quality(org, batch).scope == "article"
    with client(scenario) as api:
        scenario.login(api, "viewer")
        path = f"/api/v1/organizations/{org}/article-outcomes"
        assert api.get(path, params={"job_id": str(job), "limit": 25}).status_code == 200
        assert (
            api.get(
                path.replace(str(org), str(scenario.organizations[1])), params={"job_id": str(job)}
            ).status_code
            == 404
        )
    lifecycle = Lifecycle(results.database, results.token, SETTINGS)
    if fence in {"excerpt_days", "contact_days"}:
        retention = lifecycle.retention(org)
        lifecycle.update_retention(
            org,
            RetentionUpdate(
                expected_revision=retention.revision,
                retention=Retention.model_validate({fence: 0}),
            ),
        )
    elif fence == "deletion":
        assert (
            lifecycle.stage(org, DeletionRequest(job_id=job, reason="privacy_request")).stage
            == "fenced"
        )
    else:
        admin = create_engine(scenario.admin_url)
        try:
            with admin.begin() as c:
                c.execute(text("SET LOCAL ROLE emailmonitor_owner"))
                if fence == "policy":
                    c.execute(
                        text(
                            "UPDATE emailmonitor.source_policies SET state='revoked' "
                            "WHERE organization_id=:org"
                        ),
                        {"org": org},
                    )
                else:
                    c.execute(text("UPDATE emailmonitor.sessions SET revoked_at=clock_timestamp()"))
        finally:
            admin.dispose()
    with pytest.raises(AuthorizationDenied):
        results.outcomes(org, job, limit=25)
    with pytest.raises(AuthorizationDenied):
        associations.quality(org, batch)

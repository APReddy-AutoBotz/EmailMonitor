"""Real disposable PostgreSQL proof; no synthetic parser output is acceptance."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from emailmonitor.discovery.service import Discovery
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.lifecycle.models import DeletionRequest, Retention, RetentionUpdate
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.service import Progress, Work
from emailmonitor.results.models import ExportInput, ExportSnapshot, Filters
from emailmonitor.results.service import Results
from sqlalchemy import create_engine, text
from test_association_tenant import client, review_request
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_progress_tenant import claim, drain, planned
from test_results_tenant import lease
from test_retained_article_filters_tenant import additional_job
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario

DOI = "10.9999/synthetic.article-a"
URL = "https://synthetic.publisher.example/article-a.html"


def pair(s: Scenario) -> tuple[Progress, Results, UUID, UUID]:
    progress, first = planned(s, URL)
    org = s.organizations[0]
    progress.start(org, first, progress.snapshot(org, first).revision)
    drain(progress, org, first)
    second = additional_job(progress, org, URL)
    return progress, Results(progress.database, progress.token, SETTINGS), first, second


def request(**changes: object) -> ExportInput:
    return ExportInput.model_validate(
        {"format": "xlsx", "purpose": "academic_contact_research", "paper_doi": DOI, **changes}
    )


def test_actual_cross_job_paper_pages_reviews_and_exact_item_intersection(
    scenario: Scenario,
) -> None:
    progress, results, first, second = pair(scenario)
    org = scenario.organizations[0]
    selected = Filters(paper_doi=DOI)
    page = results.contacts(org, selected, limit=1)
    assert len(page.items) == 1 and page.next_cursor
    other = results.contacts(org, selected, page.next_cursor, 1)
    assert len(other.items) == 1 and other.next_cursor is None
    contacts = page.items + other.items
    assert {c.job_id for c in contacts} == {first, second}
    assert len({c.batch_id for c in contacts}) == 2
    outcomes = results.outcomes(org, paper_doi=DOI, limit=1)
    assert outcomes.next_cursor
    last = results.outcomes(org, cursor=outcomes.next_cursor, paper_doi=DOI, limit=1)
    assert len(last.items) == 1 and last.next_cursor is None
    item = results.outcomes(org, first, paper_doi=DOI).items[0]
    assert results.contacts(org, Filters(job_id=first, item_id=item.item_id, paper_doi=DOI)).items
    assert results.contacts(org, Filters(paper_doi="10.9999/unknown")).items == ()
    assert results.outcomes(org, paper_doi="10.9999/unknown").items == ()
    assert results.contacts(org, Filters(job_id=first, paper_doi="10.9999/unknown")).items == ()
    with pytest.raises(AuthorizationDenied):
        results.contacts(org, Filters(job_id=second, item_id=item.item_id, paper_doi=DOI))
    with pytest.raises(ValueError):
        results.contacts(org, Filters(), page.next_cursor)
    assert item.batch_id is not None
    progress.associations.review(
        org,
        item.batch_id,
        review_request(progress.associations, org, item.batch_id, action="reject"),
    )
    remaining = results.contacts(org, selected).items
    assert len(remaining) == 1 and remaining[0].job_id == second
    assert len(results.outcomes(org, paper_doi=DOI).items) == 2
    assert results.contacts(org, Filters(job_id=first, paper_doi=DOI, states=("rejected",))).items
    # Replay of the original retained derivation cannot copy another batch's acceptance.
    with pytest.raises(AuthorizationDenied):
        progress.associations.derive(org, first, URL, 1)
    assert results.contacts(org, Filters(job_id=first, paper_doi=DOI)).items == ()


@pytest.mark.parametrize("format", ["csv", "xlsx"])
def test_actual_paper_preview_immutable_snapshot_and_key_conflict(
    scenario: Scenario, format: str
) -> None:
    progress, results, first, second = pair(scenario)
    org = scenario.organizations[0]
    preview = results.preview(org, request(format=format))
    assert (preview.contacts, preview.article_outcomes) == (2, 2)
    key = str(uuid4())
    state = results.create(org, request(format=format), key)
    assert results.create(org, request(format=format, paper_doi=DOI.upper()), key).id == state.id
    with pytest.raises(RevisionConflict):
        results.create(org, request(format=format, paper_doi="10.9999/different"), key)
    third = additional_job(progress, org, URL)
    work = lease(results, org, state.id)
    assert {c.job_id for c in work.snapshot.contacts} == {first, second}
    assert third not in {o.job_id for o in work.snapshot.article_outcomes}
    assert len(work.snapshot.article_filter_bindings) == 2
    assert ExportSnapshot.model_validate_json(work.snapshot.model_dump_json()) == work.snapshot
    assert results.process(work) and results.download(org, state.id).body
    assert results.preview(org, request(format=format)).contacts == 3
    contacts_only = results.create(
        org, request(format=format, include_article_outcomes=False), str(uuid4())
    )
    work = lease(results, org, contacts_only.id)
    assert len(work.snapshot.contacts) == 3 and not work.snapshot.article_outcomes
    assert results.process(work)
    assert results.download(org, contacts_only.id).body


@pytest.mark.parametrize("change", ["deletion", "retention", "session", "source"])
@pytest.mark.parametrize("stage", ["claim_finish", "ready_download"])
def test_actual_paper_exports_keep_current_authority(
    scenario: Scenario, change: str, stage: str
) -> None:
    _, results, first, _ = pair(scenario)
    org = scenario.organizations[0]
    state = results.create(org, request(), str(uuid4()))
    work = lease(results, org, state.id)
    if stage == "ready_download":
        assert results.process(work)
    lifecycle = Lifecycle(results.database, results.token, SETTINGS)
    if change == "deletion":
        lifecycle.stage(org, DeletionRequest(job_id=first, reason="privacy_request"))
    elif change == "retention":
        current = lifecycle.retention(org)
        lifecycle.update_retention(
            org,
            RetentionUpdate(
                expected_revision=current.revision, retention=Retention(contact_days=0)
            ),
        )
    else:
        # Owned disposable fixture control mutations; runtime authority remains unchanged.
        engine = create_engine(scenario.admin_url)
        with engine.begin() as c:
            if change == "session":
                c.execute(
                    text(
                        "UPDATE emailmonitor.sessions SET revoked_at=clock_timestamp() "
                        "WHERE identity_id=:id"
                    ),
                    {"id": scenario.identities["owner"]},
                )
            else:
                c.execute(
                    text(
                        "UPDATE emailmonitor.source_policies SET state='revoked' "
                        "WHERE organization_id=:org AND state='approved'"
                    ),
                    {"org": org},
                )
        engine.dispose()
    if stage == "claim_finish":
        if change == "session":
            with pytest.raises(AuthorizationDenied):
                results.process(work)
        else:
            assert not results.process(work)
    else:
        with pytest.raises(AuthorizationDenied):
            results.download(org, state.id)


def test_actual_paper_api_tenant_and_private_helper_boundaries(scenario: Scenario) -> None:
    _, results, _, _ = pair(scenario)
    org = scenario.organizations[0]
    with client(scenario) as api:
        scenario.login(api, "viewer")
        for endpoint in ("contacts", "article-outcomes"):
            path = f"/api/v1/organizations/{org}/{endpoint}"
            assert len(api.get(path, params={"paper_doi": DOI}).json()["items"]) == 2
            assert api.get(path, params={"paper_doi": "https://doi.org/" + DOI}).status_code == 422
            assert (
                api.get(
                    path.replace(str(org), str(scenario.organizations[1])),
                    params={"paper_doi": DOI},
                ).status_code
                == 404
            )
    with results.database.tenant(results.token, org, Capability.READ_ORGANIZATION) as (c, _):
        for signature in (
            "normalized_paper_doi(text)",
            "observed_paper_doi(jsonb)",
            "guard_retained_paper_doi()",
            "retained_paper_batch_matches(uuid,uuid,text)",
        ):
            assert not c.execute(
                text("SELECT has_function_privilege(current_user,:name,'EXECUTE')"),
                {"name": "emailmonitor." + signature},
            ).scalar_one()


def test_actual_observed_identity_requires_consistent_evidenced_facts(scenario: Scenario) -> None:
    engine = create_engine(scenario.admin_url)
    fact = {"field": "doi", "value": DOI, "evidence": {"locator": "head/meta[2]"}}
    valid = {"preferred_metadata": {"doi": DOI.upper()}, "metadata": [fact]}
    invalid = [
        {"preferred_metadata": {"doi": DOI}},
        {"preferred_metadata": {"doi": DOI}, "metadata": []},
        {"preferred_metadata": {"doi": DOI}, "metadata": [{**fact, "value": "10.9999/conflict"}]},
        {
            "preferred_metadata": {"doi": DOI},
            "metadata": [fact, {**fact, "value": "10.9999/conflict"}],
        },
        {"preferred_metadata": {"doi": DOI}, "metadata": [{**fact, "evidence": {}}]},
        {"preferred_metadata": {"doi": "https://doi.org/" + DOI}, "metadata": [fact]},
    ]
    with engine.connect() as c:
        for document in [valid, *invalid]:
            found: object = c.execute(
                text("SELECT emailmonitor.observed_paper_doi(CAST(:doc AS jsonb))"),
                {"doc": json.dumps(document)},
            ).scalar_one()
            assert found == (DOI if document is valid else None)
    engine.dispose()


def test_actual_concurrent_jobs_keep_distinct_observations_and_stale_work_refuses(
    scenario: Scenario,
) -> None:
    progress, first = planned(scenario, URL)
    org = scenario.organizations[0]
    body = request_body()
    body["input"] = {"type": "url", "url": URL}
    second = Ledger(progress.database, progress.token, SETTINGS).create(
        org, JobRequest.model_validate(body), str(uuid4())
    )
    Discovery(progress.database, progress.token, SETTINGS).plan(org, second, 1)
    works = []
    for job in (first, second):
        progress.start(org, job, progress.snapshot(org, job).revision)
        works.append(claim(progress, org, job))
    barrier = Barrier(2)

    def run(work: Work) -> str:
        barrier.wait(timeout=5)
        return progress.process_fixture(work)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, works)) == ["succeeded", "succeeded"]
    results = Results(progress.database, progress.token, SETTINGS)
    assert {c.job_id for c in results.contacts(org, Filters(paper_doi=DOI)).items} == {
        first,
        second,
    }
    before = results.contacts(org, Filters(paper_doi=DOI)).items
    for work in works:
        with pytest.raises(AuthorizationDenied):
            progress.process_fixture(work)
    assert results.contacts(org, Filters(paper_doi=DOI)).items == before


def test_actual_same_doi_in_two_tenants_has_no_shared_rows_or_visibility(
    scenario: Scenario,
) -> None:
    _, results, first, second = pair(scenario)
    other = replace(
        scenario,
        organizations=(scenario.organizations[1], scenario.organizations[0]),
        identities={**scenario.identities, "owner": scenario.identities["owner_b"]},
    )
    _, other_results, third, fourth = pair(other)
    for service, org, expected in [
        (results, scenario.organizations[0], {first, second}),
        (other_results, other.organizations[0], {third, fourth}),
    ]:
        rows = service.contacts(org, Filters(paper_doi=DOI)).items
        assert {row.job_id for row in rows} == expected
        assert {row.organization_id for row in rows} == {org}
        assert {row.job_id for row in service.outcomes(org, paper_doi=DOI).items} == expected
    with pytest.raises(AuthorizationDenied):
        results.contacts(other.organizations[0], Filters(paper_doi=DOI))
    with pytest.raises(AuthorizationDenied):
        other_results.contacts(scenario.organizations[0], Filters(paper_doi=DOI))

"""OA-030 (document 92): Europe PMC is its own fixture-only, tenant-approved source.

Real PostgreSQL (disposable, synthetic), two tenants. Each source needs its own
approved policy; results and exports name one source per request (default
synthetic-publisher, unchanged); revoking one source hides only that source; new
synthetic-labelled Open Access rows are refused while 0027-era rows stay valid.
"""

from __future__ import annotations

import io
from typing import Any, Final
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from emailmonitor.associations.models import Review
from emailmonitor.discovery import planning
from emailmonitor.discovery.planning import plan_input
from emailmonitor.discovery.service import Discovery
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.lifecycle.models import SuppressionCreate
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.progress.service import Progress
from emailmonitor.results.models import Filters
from emailmonitor.results.service import Results
from emailmonitor.sources import open_access_documents as registry
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_oa_persistence_tenant import (
    PLOS,
    PLOS_ADDRESS,
    _insert,
    _retained_document,
    host_parser,
    running,
)
from test_progress_tenant import drain
from test_results_tenant import ready
from test_source_foundation import policy_body, source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario

EPMC: Final = "europe-pmc"
SYNTHETIC: Final = "synthetic-publisher"
HTML_ARTICLE = "https://synthetic.publisher.example/article-a.html"
DENIED = (AuthorizationDenied, HTTPException, DBAPIError)
OPERATIONS = {
    EPMC: ["fetch_xml", "extract_contacts", "export_contacts", "retain_excerpt"],
    SYNTHETIC: [
        "search",
        "fetch_html",
        "fetch_xml",
        "extract_contacts",
        "retain_excerpt",
        "export_contacts",
    ],
}


def approve(s: Scenario, source: str, tenant: int = 0) -> None:
    with s.client() as client:
        csrf = s.login(client, "owner" if tenant == 0 else "owner_b")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(s, tenant, source)
        body = policy_body(allowed_operations=OPERATIONS[source])
        response = client.post(
            path + "/policies", headers=headers, json={"expected_version": 0, "policy": body}
        )
        assert response.status_code == 201, response.text
        response = client.post(
            path + "/policy-state",
            headers=headers,
            json={"expected_version": 1, "expected_revision": 1, "state": "approved"},
        )
        assert response.status_code == 200, response.text


def revoke(s: Scenario, source: str) -> None:
    with s.client() as client:
        csrf = s.login(client, "owner")
        response = client.post(
            source_path(s, 0, source) + "/policy-state",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
        )
        assert response.status_code == 200, response.text


def ledger(s: Scenario, role: str = "owner") -> Ledger:
    with s.client() as client:
        s.login(client, role)
        return Ledger(s.foundation.database, str(client.cookies[COOKIE]), SETTINGS)


def job_for(
    s: Scenario, url: str, source_id: str | None = None, tenant: int = 0
) -> tuple[Ledger, UUID]:
    book = ledger(s, "owner" if tenant == 0 else "owner_b")
    body: dict[str, Any] = request_body()
    body["input"] = {"type": "url", "url": url}
    if source_id is not None:
        body["input"]["source_id"] = source_id
    job = book.create(s.organizations[tenant], JobRequest.model_validate(body), str(uuid4()))
    return book, job


def plan(
    s: Scenario, url: str, source_id: str | None = None, tenant: int = 0
) -> tuple[Progress, UUID]:
    book, job = job_for(s, url, source_id, tenant)
    Discovery(book.database, book.token, SETTINGS).plan(s.organizations[tenant], job, 1)
    return Progress(book.database, book.token, SETTINGS), job


def accept_all(progress: Progress, org: UUID, job: UUID) -> None:
    for item in progress.items(org, job):
        if item.batch_id is None:
            continue
        bundle = progress.associations.detail(org, item.batch_id)
        for association in bundle.associations:
            if association.state == "needs_review" and association.author_id:
                progress.associations.review(
                    org,
                    item.batch_id,
                    Review(
                        association_id=association.id,
                        expected_revision=association.revision,
                        action="accept",
                        evidence_ids=association.evidence_ids,
                        reason="Inspected retained evidence",
                    ),
                )


def open_access_contacts(s: Scenario) -> tuple[Results, UUID]:
    progress, job = plan(s, PLOS.source_url)
    org = s.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    for _ in range(5):
        if progress.snapshot(org, job).state in {"completed", "completed_partial", "failed"}:
            break
        rows = [row for row in progress.pending(org) if row["job_id"] == job]
        work = progress.claim(
            org, job, UUID(str(rows[0]["item_id"])), UUID(str(rows[0]["event_id"]))
        )
        assert work is not None
        progress.process_fixture(work, jats_parser=host_parser)
    accept_all(progress, org, job)
    return Results(progress.database, progress.token, SETTINGS), job


def html_contacts(s: Scenario) -> tuple[Results, UUID]:
    progress, job = plan(s, HTML_ARTICLE)
    org = s.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    drain(progress, org, job)
    return Results(progress.database, progress.token, SETTINGS), job


def exported(results: Results, org: UUID, export: UUID) -> bytes:
    with ZipFile(io.BytesIO(results.download(org, export).body)) as archive:
        return archive.read("contacts.csv")


def admin_scalar(s: Scenario, sql: str, **params: object) -> object:
    engine = create_engine(s.admin_url)
    try:
        with engine.connect() as c:
            return c.execute(text(sql), params).scalar_one()
    finally:
        engine.dispose()


# ----------------------------------------------------------------- planning


def test_planning_chooses_the_source_and_refuses_a_contradicting_client_source() -> None:
    def planned(url: str, source_id: str | None = None) -> planning.InputPlan:
        body: dict[str, Any] = request_body()
        body["input"] = {"type": "url", "url": url}
        if source_id is not None:
            body["input"]["source_id"] = source_id
        return plan_input(JobRequest.model_validate(body))

    assert planned(PLOS.source_url).source_id == EPMC
    assert planned(PLOS.source_url, EPMC).source_id == EPMC
    refused = planned(PLOS.source_url, SYNTHETIC)
    assert (refused.classification, refused.reason) == ("unsupported", "source_onboarding_required")
    assert planned(HTML_ARTICLE).source_id == SYNTHETIC
    assert planned(HTML_ARTICLE, EPMC).classification == "unsupported"
    assert planned(PLOS.source_url, "elsevier_sciencedirect_v2").classification == "unsupported"
    # The source is not part of the persisted plan document (byte-identical history).
    from dataclasses import asdict

    assert "source_id" not in asdict(planned(PLOS.source_url))


def test_each_source_needs_its_own_policy_to_plan(scenario: Scenario) -> None:
    approve(scenario, SYNTHETIC)
    with pytest.raises(DENIED):
        plan(scenario, PLOS.source_url)
    approve(scenario, EPMC, tenant=1)
    with pytest.raises(DENIED):
        plan(scenario, HTML_ARTICLE, tenant=1)
    _, job = plan(scenario, PLOS.source_url, tenant=1)
    assert (
        admin_scalar(
            scenario,
            "SELECT source_id FROM emailmonitor.discovery "
            "WHERE organization_id=:org AND job_id=:job",
            org=scenario.organizations[1],
            job=job,
        )
        == EPMC
    )
    # Tenant A's synthetic approval never authorizes tenant B, and B's job is invisible to A.
    with pytest.raises(DENIED):
        plan(scenario, HTML_ARTICLE, tenant=1)
    a = ledger(scenario)
    with pytest.raises(DENIED):
        Progress(a.database, a.token, SETTINGS).snapshot(scenario.organizations[1], job)


def test_database_refuses_a_europe_pmc_discovery_outside_the_registry(scenario: Scenario) -> None:
    approve(scenario, EPMC)
    book, job = job_for(scenario, PLOS.source_url)
    org = scenario.organizations[0]
    # A server-chosen plan that names europe-pmc for a non-registered start URL is refused.
    original = planning.InputPlan.source_id
    try:
        planning.InputPlan.source_id = property(lambda self: EPMC)  # type: ignore[method-assign,assignment]
        other, html_job = job_for(scenario, HTML_ARTICLE)
        with pytest.raises(DENIED):
            Discovery(other.database, other.token, SETTINGS).plan(org, html_job, 1)
    finally:
        planning.InputPlan.source_id = original  # type: ignore[method-assign]
    Discovery(book.database, book.token, SETTINGS).plan(org, job, 1)


# ------------------------------------------------------------ results scope


def test_europe_pmc_results_need_their_source_and_defaults_are_unchanged(
    scenario: Scenario,
) -> None:
    approve(scenario, EPMC)
    results, job = open_access_contacts(scenario)
    org = scenario.organizations[0]
    # Default results and exports are the synthetic source; this tenant has no such policy.
    with pytest.raises(DENIED):
        results.contacts(org, Filters(job_id=job))
    contacts = results.contacts(org, Filters(job_id=job, source_id=EPMC)).items
    assert [c.raw_address for c in contacts] == [PLOS_ADDRESS]
    assert contacts[0].source_id == EPMC
    # Article-scoped reads derive the source from the row.
    assert results.contact(org, contacts[0].batch_id, contacts[0].association_id) == contacts[0]
    evidence = results.evidence(org, contacts[0].batch_id, contacts[0].evidence_ids[0])
    assert evidence.source_url == PLOS.source_url
    outcomes = results.outcomes(org, job, source_id=EPMC).items
    assert len(outcomes) == 1
    export = ready(results, org, job, format="csv", source_id=EPMC)
    assert PLOS_ADDRESS.encode() in exported(results, org, export)
    with pytest.raises(DENIED):
        ready(results, org, job, format="csv")

    # Tenant B (no policy at all) sees nothing of tenant A's Europe PMC work.
    with scenario.client() as client:
        scenario.login(client, "owner_b")
        other = Results(results.database, str(client.cookies[COOKIE]), SETTINGS)
        for target in scenario.organizations:
            with pytest.raises(DENIED):
                other.contacts(target, Filters(job_id=job, source_id=EPMC))
        with pytest.raises(DENIED):
            other.download(org, export)


def test_revoking_one_source_hides_only_that_source(scenario: Scenario) -> None:
    approve(scenario, SYNTHETIC)
    approve(scenario, EPMC)
    org = scenario.organizations[0]
    results, html_job = html_contacts(scenario)
    _, oa_job = open_access_contacts(scenario)
    synthetic = results.contacts(org, Filters()).items
    europe = results.contacts(org, Filters(source_id=EPMC)).items
    assert synthetic and all(c.source_id == SYNTHETIC for c in synthetic)
    assert {c.source_id for c in europe} == {EPMC}
    # One source per request: neither listing ever contains the other source's rows.
    assert not {c.association_id for c in synthetic} & {c.association_id for c in europe}
    assert results.contacts(org, Filters(source_id=SYNTHETIC)).items == synthetic
    europe_export = ready(results, org, oa_job, format="csv", source_id=EPMC)
    synthetic_export = ready(results, org, html_job, format="csv")

    revoke(scenario, EPMC)
    assert results.contacts(org, Filters()).items == synthetic
    with pytest.raises(AuthorizationDenied):
        results.contacts(org, Filters(source_id=EPMC))
    with pytest.raises(AuthorizationDenied):
        results.contact(org, europe[0].batch_id, europe[0].association_id)
    with pytest.raises(DENIED):
        results.download(org, europe_export)
    with pytest.raises(DENIED):
        ready(results, org, oa_job, format="csv", source_id=EPMC)
    assert PLOS_ADDRESS.encode() not in exported(results, org, synthetic_export)
    assert results.contact(org, synthetic[0].batch_id, synthetic[0].association_id)


def test_revoked_source_cannot_run_queued_work(scenario: Scenario) -> None:
    approve(scenario, SYNTHETIC)
    approve(scenario, EPMC)
    progress, job = plan(scenario, PLOS.source_url)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    rows = [row for row in progress.pending(org) if row["job_id"] == job]
    assert len(rows) == 1
    revoke(scenario, EPMC)
    # Revoking the Europe PMC policy withdraws its queued work; a stale delivery of the
    # original event cannot claim or commit anything.
    assert not [row for row in progress.pending(org) if row["job_id"] == job]
    try:
        work = progress.claim(
            org, job, UUID(str(rows[0]["item_id"])), UUID(str(rows[0]["event_id"]))
        )
    except DENIED:
        work = None
    if work is not None:
        with pytest.raises(DENIED):
            progress.process_fixture(work, jats_parser=host_parser)
    assert (
        admin_scalar(
            scenario,
            "SELECT count(*) FROM emailmonitor.article_observations WHERE job_id=:job",
            job=job,
        )
        == 0
    )
    # The synthetic source is unaffected.
    html_contacts(scenario)


def test_europe_pmc_source_suppression_hides_only_europe_pmc(scenario: Scenario) -> None:
    approve(scenario, SYNTHETIC)
    approve(scenario, EPMC)
    org = scenario.organizations[0]
    results, _ = html_contacts(scenario)
    open_access_contacts(scenario)
    synthetic = results.contacts(org, Filters()).items
    assert results.contacts(org, Filters(source_id=EPMC)).items
    Lifecycle(results.database, results.token, SETTINGS).suppress(
        org, SuppressionCreate(kind="source", value=EPMC, reason="source_restriction")
    )
    with pytest.raises(DENIED):
        results.contacts(org, Filters(source_id=EPMC))
    assert results.contacts(org, Filters()).items == synthetic


# ----------------------------------------------------------------- history


def test_new_synthetic_labelled_open_access_rows_are_refused(scenario: Scenario) -> None:
    assert (
        admin_scalar(
            scenario,
            "SELECT emailmonitor.registered_open_access_document('synthetic-publisher',:url)",
            url=PLOS.source_url,
        )
        is None
    )
    assert (
        admin_scalar(
            scenario,
            "SELECT emailmonitor.registered_open_access_document('europe-pmc',:url)->>'source_id'",
            url=PLOS.source_url,
        )
        == EPMC
    )
    approve(scenario, SYNTHETIC)
    progress, job, work = running(scenario)  # approves the europe-pmc policy too
    org = scenario.organizations[0]
    document = _retained_document(progress, work, org, job)
    # The database guard refuses a synthetic-labelled Open Access row for this job...
    with pytest.raises(DBAPIError, match="ARTICLE_OBSERVATION_FENCE"):
        _insert(progress, work, org, job, document, source=SYNTHETIC)
    # ...and the Python writer refuses a job whose source is not europe-pmc.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(registry, "SOURCE", SYNTHETIC)
        with pytest.raises(DENIED):
            progress.process_fixture(work, jats_parser=host_parser)
    assert (
        admin_scalar(
            scenario,
            "SELECT count(*) FROM emailmonitor.article_observations WHERE job_id=:job",
            job=job,
        )
        == 0
    )


def test_0027_era_synthetic_open_access_rows_stay_visible(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Author a row exactly as 0027 did (registry under synthetic), then restore 0028."""
    import json

    approve(scenario, SYNTHETIC)
    org = scenario.organizations[0]
    engine = create_engine(scenario.admin_url)
    legacy = json.dumps(registry.catalog_entries(registry.LEGACY_SOURCE))
    try:
        with engine.begin() as c:
            c.execute(
                text(
                    "UPDATE emailmonitor.source_catalog SET support=jsonb_set(support,"
                    "'{open_access_documents}',CAST(:entries AS jsonb)) "
                    "WHERE source_id='synthetic-publisher'"
                ),
                {"entries": legacy},
            )
        monkeypatch.setattr(planning, "OPEN_ACCESS_SOURCE", SYNTHETIC)
        monkeypatch.setattr(registry, "SOURCE", SYNTHETIC)
        results, job = open_access_contacts(scenario)
    finally:
        with engine.begin() as c:
            c.execute(
                text(
                    "UPDATE emailmonitor.source_catalog "
                    "SET support=support-'open_access_documents' "
                    "WHERE source_id='synthetic-publisher'"
                )
            )
        engine.dispose()
    monkeypatch.undo()
    assert (
        admin_scalar(
            scenario,
            "SELECT source_id FROM emailmonitor.article_observations WHERE job_id=:job",
            job=job,
        )
        == SYNTHETIC
    )
    contacts = results.contacts(org, Filters(job_id=job)).items
    assert [c.raw_address for c in contacts] == [PLOS_ADDRESS]
    assert contacts[0].source_id == SYNTHETIC and contacts[0].license_category == "unknown"
    assert results.contact(org, contacts[0].batch_id, contacts[0].association_id) == contacts[0]
    export = ready(results, org, job, format="csv")
    assert PLOS_ADDRESS.encode() in exported(results, org, export)
    with pytest.raises(DENIED):
        results.contacts(org, Filters(job_id=job, source_id=EPMC))

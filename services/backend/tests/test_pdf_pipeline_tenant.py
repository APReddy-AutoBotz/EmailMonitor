"""Real SQL and actual isolated authored-PDF worker; unavailable infrastructure skips explicitly."""

import json
import os
from uuid import UUID, uuid4

import pytest
from emailmonitor.associations.models import Review
from emailmonitor.discovery.service import Discovery
from emailmonitor.extraction.pdf import parse_pdf
from emailmonitor.extraction.pdf_fixture import DIGESTS, pdf_bytes
from emailmonitor.extraction.pdf_retained import RetainedPdf, retain_pdf
from emailmonitor.extraction.pdf_service import PdfExtraction, PdfParser
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.progress.binding import bound
from emailmonitor.progress.service import Progress
from emailmonitor.results.models import Filters
from emailmonitor.results.presence import observation_presence
from emailmonitor.results.service import Results
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_progress_tenant import claim
from test_results_tenant import ready
from test_source_foundation import policy_body, source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario
from test_xml_pipeline_tenant import mutate_authority


def planned_pdf(
    s: Scenario, name: str, *, opt_in: bool = True, enabled: bool = True
) -> tuple[Progress, UUID]:
    with s.client() as client:
        csrf = s.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        path = source_path(s)
        operations = [
            "parse_fixture_pdf" if opt_in else "fetch_html",
            "extract_contacts",
            "retain_excerpt",
            "export_contacts",
        ]
        response = client.post(
            path + "/policies",
            headers=headers,
            json={"expected_version": 0, "policy": policy_body(allowed_operations=operations)},
        )
        assert response.status_code == 201, response.text
        assert (
            client.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 200
        )
        ledger = Ledger(s.foundation.database, str(client.cookies[COOKIE]), SETTINGS)
    body = request_body()
    body["input"] = {"type": "url", "url": "https://synthetic.publisher.example/" + name}
    options = body["options"]
    assert isinstance(options, dict)
    options["allow_pdf"] = enabled
    job = ledger.create(s.organizations[0], JobRequest.model_validate(body), str(uuid4()))
    discovery = Discovery(ledger.database, ledger.token, SETTINGS)
    plan = discovery.plan(s.organizations[0], job, 1)
    if not enabled or name not in DIGESTS:
        assert plan["persisted"] is False
    return Progress(ledger.database, ledger.token, SETTINGS), job


@pytest.fixture
def actual_pdf() -> None:
    if os.environ.get("EM_REQUIRE_XML_ISOLATION") != "true":
        pytest.skip("Actual network-none parser image required for durable PDF acceptance")


def assert_durable_journey(
    scenario: Scenario, name: str, *, sql_only: bool, parser: PdfParser | None = None
) -> None:
    progress, job = planned_pdf(scenario, name)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)
    replayed: list[bool] = []

    def replay() -> None:
        before = progress.extraction.read(org, job)[0]
        retained = RetainedPdf.model_validate_json(json.dumps(before["observation"]))
        after = PdfExtraction(progress.database, progress.token, SETTINGS).commit_pdf(
            org, job, retained
        )
        assert before == after
        replayed.append(True)

    if sql_only:
        # Independent SQL proof with authored observations. Never an isolation substitute.
        service = PdfExtraction(progress.database, progress.token, SETTINGS)
        with bound(work.lease):
            context = service.prepare(org, job, work.url)
            parsed = parse_pdf(SETTINGS, work.url, pdf_bytes(name))
            value = retain_pdf(
                parsed,
                service.binding(org, job, work.url, context),
                permit_excerpts=bool(context["permit_excerpts"]),
            )
            service.commit_pdf(org, job, value)
            replay()
            derived = progress.associations.derive(org, job, work.url, 1)
            progress.finish(work, derived)
    else:
        progress.process_fixture(work, after_observation=replay, pdf_parser=parser)
    assert replayed == [True]
    item = progress.items(org, job)[0]
    assert item.batch_id is not None
    batch = item.batch_id
    stored = progress.extraction.read(org, job)[0]
    retained = RetainedPdf.model_validate_json(json.dumps(stored["observation"]))
    assert retained.binding.item == work.lease.item and retained.content_digest == DIGESTS[name]
    bundle = progress.associations.detail(org, batch)
    quality = progress.associations.quality(org, batch)
    assert quality.observation_route == "pdf" and quality.observation_status == retained.status
    assert quality.reason_availability == "recorded"
    assert quality.reasons == (() if retained.reason == "complete" else (retained.reason,))
    for association in bundle.associations:
        if association.state == "needs_review" and association.author_id is not None:
            progress.associations.review(
                org,
                batch,
                Review(
                    association_id=association.id,
                    expected_revision=association.revision,
                    action="accept",
                    evidence_ids=association.evidence_ids,
                    reason="Inspected authored PDF page evidence",
                ),
            )
    results = Results(progress.database, progress.token, SETTINGS)
    page = results.outcomes(org, job, article_outcome_presence=observation_presence(retained))
    assert len(page.items) == 1 and page.items[0].batch_id == batch
    for contact in results.contacts(org, Filters(job_id=job)).items:
        assert contact.source_url == work.url
        for evidence_id in contact.evidence_ids:
            evidence = results.evidence(org, batch, evidence_id).citation
            assert evidence.method == "pdf_text" and evidence.page is not None
            assert evidence.region_precision == "full_cropbox_not_glyph_bbox"
    for format in ("csv", "xlsx"):
        export = ready(results, org, job, format=format)
        assert results.download(org, export).body
    with pytest.raises(AuthorizationDenied):
        progress.associations.detail(scenario.organizations[1], batch)
    with progress.database.engine.connect() as c:
        # RLS cannot be bypassed by an unbound ordinary runtime connection.
        assert (
            c.execute(text("SELECT count(*) FROM emailmonitor.article_observations")).scalar_one()
            == 0
        )


@pytest.mark.parametrize("name", sorted(DIGESTS))
def test_actual_pdf_durable_journey(scenario: Scenario, actual_pdf: None, name: str) -> None:
    assert_durable_journey(scenario, name, sql_only=False)


@pytest.mark.parametrize("name", sorted(DIGESTS))
def test_sql_pdf_retention_review_and_export(scenario: Scenario, name: str) -> None:
    assert_durable_journey(scenario, name, sql_only=True)


def test_existing_policy_does_not_gain_pdf_access(scenario: Scenario) -> None:
    with pytest.raises(AuthorizationDenied):
        planned_pdf(scenario, "article-a.pdf", opt_in=False)


@pytest.mark.parametrize("name,enabled", [("article-a.pdf", False), ("unknown.pdf", True)])
def test_disabled_or_unknown_pdf_does_not_plan(
    scenario: Scenario, name: str, enabled: bool
) -> None:
    planned_pdf(scenario, name, enabled=enabled)


@pytest.mark.parametrize(
    "kind",
    [
        "cancel",
        "pause",
        "delete",
        "retention",
        "expired_lease",
        "lost_lease",
        "revoked_policy",
        "expired_session",
        "revoked_session",
    ],
)
def test_pdf_current_fences_reject_commit_after_parser(
    scenario: Scenario, actual_pdf: None, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    from emailmonitor.extraction import pdf_service

    progress, job = planned_pdf(scenario, "article-a.pdf")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)
    from emailmonitor.parsing.pdf_channel import parse_isolated

    original = parse_isolated

    def invalidate(*args: object, **kwargs: object) -> object:
        observed = original(*args, **kwargs)  # type: ignore[arg-type]
        mutate_authority(scenario, progress, job, kind)
        return observed

    monkeypatch.setattr(pdf_service, "parse_isolated", invalidate)
    with pytest.raises((AuthorizationDenied, HTTPException, DBAPIError, ValueError)):
        progress.process_fixture(work)


@pytest.mark.parametrize(
    "kind",
    [
        "cancel",
        "pause",
        "delete",
        "retention",
        "expired_lease",
        "lost_lease",
        "revoked_policy",
        "expired_session",
        "revoked_session",
    ],
)
def test_sql_pdf_commit_rechecks_current_authority(scenario: Scenario, kind: str) -> None:
    progress, job = planned_pdf(scenario, "article-a.pdf")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)
    service = PdfExtraction(progress.database, progress.token, SETTINGS)
    with bound(work.lease):
        context = service.prepare(org, job, work.url)
        retained = retain_pdf(
            parse_pdf(SETTINGS, work.url, pdf_bytes("article-a.pdf")),
            service.binding(org, job, work.url, context),
            permit_excerpts=True,
        )
    mutate_authority(scenario, progress, job, kind)
    with (
        bound(work.lease),
        pytest.raises((AuthorizationDenied, HTTPException, DBAPIError, ValueError)),
    ):
        service.commit_pdf(org, job, retained)

    admin = create_engine(scenario.admin_url)
    try:
        with admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": job},
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()

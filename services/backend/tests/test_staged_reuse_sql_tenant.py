"""Disposable PostgreSQL bound-reuse checks; not parser-isolation acceptance."""

import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from emailmonitor.associations.models import Review
from emailmonitor.associations.reuse_materialization import _stage_bound_reuse, materialize_draft
from emailmonitor.associations.reuse_preparation import prepare_reuse
from emailmonitor.discovery.service import Discovery
from emailmonitor.extraction.pdf import parse_pdf
from emailmonitor.extraction.pdf_fixture import pdf_bytes
from emailmonitor.extraction.pdf_retained import retain_pdf
from emailmonitor.extraction.pdf_service import PdfExtraction
from emailmonitor.extraction.sciencedirect import parse_article
from emailmonitor.extraction.xml_retained import XML_IDENTIFIER, retain_xml
from emailmonitor.extraction.xml_service import XmlExtraction, fixture_bytes
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.lifecycle.models import DeletionRequest, SuppressionCreate
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied, Database, TenantContext
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import bound
from emailmonitor.progress.execution import ExecutionDispatcher
from emailmonitor.progress.service import Progress
from emailmonitor.results.models import Filters
from emailmonitor.results.service import Results
from emailmonitor.sources import provider_documents as catalog
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from test_association_tenant import client as fixture_client
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_pdf_pipeline_tenant import planned_pdf
from test_progress_tenant import claim
from test_provider_journey import registry, xml_bytes
from test_provider_journey_tenant import planned_provider
from test_results_tenant import ready
from test_source_foundation import source_path
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario
from test_xml_pipeline_tenant import mutate_authority, planned_xml


def source_target(scenario: Scenario, route: str) -> tuple[Progress, UUID, UUID, UUID, str]:
    # Host parsing is used solely to construct authored SQL fixtures. It is not
    # evidence of the separately required network-none parser acceptance.
    progress, source = (
        planned_pdf(scenario, "article-a.pdf")
        if route == "pdf"
        else planned_provider(scenario, url=catalog.DOI_URL)
        if route == "provider"
        else planned_xml(scenario)
    )
    org = scenario.organizations[0]
    progress.start(org, source, progress.snapshot(org, source).revision)
    batch, url = finish_source(progress, org, source, route)
    target = uuid4()
    body = {
        **request_body(),
        "input": {"type": "url", "url": url},
        "reuse": {"mode": "verified_retained", "fresh_since": "2000-01-01T00:00:00Z"},
    }
    if route == "pdf":
        options = body["options"]
        assert isinstance(options, dict)
        options["allow_pdf"] = True
    with progress.database.tenant(progress.token, org, Capability.ACQUIRE_SOURCE) as (c, ctx):
        assert isinstance(ctx, TenantContext)
        c.execute(
            text(
                "INSERT INTO emailmonitor.jobs (organization_id,id,created_by,kind,request,state) "
                "VALUES(:org,:job,:actor,'extraction',CAST(:body AS jsonb),'draft')"
            ),
            {"org": org, "job": target, "actor": ctx.identity_id, "body": json.dumps(body)},
        )
    return progress, source, target, batch, url


def finish_source(progress: Progress, org: UUID, source: UUID, route: str) -> tuple[UUID, str]:
    """Commit authored source facts through SQL; this is not parser-isolation proof."""
    work = claim(progress, org, source)
    with bound(work.lease):
        if route == "pdf":
            extraction = PdfExtraction(progress.database, progress.token, SETTINGS)
            context = extraction.prepare(org, source, work.url)
            observed = parse_pdf(SETTINGS, work.url, pdf_bytes("article-a.pdf"))
            retained = retain_pdf(
                observed,
                extraction.binding(org, source, work.url, context),
                permit_excerpts=bool(context["permit_excerpts"]),
            )
            extraction.commit_pdf(org, source, retained)
        else:
            extraction_xml = XmlExtraction(progress.database, progress.token, SETTINGS)
            binding, excerpts = extraction_xml.binding(org, source, 1, work.url)
            if route == "provider":
                document = registry()[0]
                observed_xml = parse_article(xml_bytes(document), document.identifier)
                retained_xml = retain_xml(observed_xml, binding, excerpts, registered=document)
            else:
                observed_xml = parse_article(fixture_bytes(), XML_IDENTIFIER)
                retained_xml = retain_xml(observed_xml, binding, excerpts)
            extraction_xml.commit_xml(org, source, retained_xml)
        batch = progress.associations.derive(org, source, work.url, 1)
        progress.finish(work, batch)
    expected_route = "article_xml" if route == "provider" else route
    assert progress.associations.detail(org, batch).observation_route == expected_route
    return batch, work.url


@pytest.mark.parametrize("route", ["pdf", "article_xml", "provider"])
def test_bound_non_html_copy_keeps_original_binding_and_replays(
    scenario: Scenario, route: str
) -> None:
    progress, source, target, batch, url = source_target(scenario, route)
    org = scenario.organizations[0]
    discovery = Discovery(progress.database, progress.token, SETTINGS)
    _, selected = _stage_bound_reuse(discovery, progress.associations, org, target, 1)
    assert selected == batch
    with pytest.raises(HTTPException) as stale:
        _stage_bound_reuse(discovery, progress.associations, org, target, 1)
    assert stale.value.status_code == 409
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        revision: int = c.execute(
            text(
                "SELECT row_version FROM emailmonitor.jobs WHERE organization_id=:org AND id=:job"
            ),
            {"org": org, "job": target},
        ).scalar_one()
    _, replay = _stage_bound_reuse(discovery, progress.associations, org, target, revision)
    assert replay == batch
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        rows = (
            c.execute(
                text(
                    "SELECT job_id,observation,observed_at,reused_from_job,reused_source_batch "
                    "FROM emailmonitor.article_observations WHERE organization_id=:org "
                    "AND job_id IN (:source,:target) AND article_url=:url"
                ),
                {"org": org, "source": source, "target": target, "url": url},
            )
            .mappings()
            .all()
        )
        assert len(rows) == 2
        original = next(row for row in rows if row["job_id"] == source)
        reused = next(row for row in rows if row["job_id"] == target)
        assert reused["observation"] == original["observation"]
        assert reused["observed_at"] == original["observed_at"]
        assert reused["reused_from_job"] == source and reused["reused_source_batch"] == batch
    assert progress.associations.detail(org, batch).observation_route == (
        "article_xml" if route == "provider" else route
    )


@pytest.mark.parametrize("route", ["pdf", "article_xml", "provider"])
def test_source_fence_serializes_item_read_with_deletion(scenario: Scenario, route: str) -> None:
    progress, source, target, batch, url = source_target(scenario, route)
    org = scenario.organizations[0]
    Discovery(progress.database, progress.token, SETTINGS)._plan_bound_reuse(org, target, 1)
    other = Database(os.environ["EM_TEST_DATABASE_URL"])
    lifecycle = Lifecycle(other, progress.token, SETTINGS)
    request = DeletionRequest(job_id=source, reason="privacy_request")
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            with progress.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
                privileges = c.execute(
                    text(
                        "SELECT has_table_privilege(current_user,"
                        "'emailmonitor.execution_items','SELECT'),"
                        "has_table_privilege(current_user,'emailmonitor.execution_items','UPDATE'),"
                        "has_function_privilege(current_user,"
                        "'emailmonitor.execution_read_fence(uuid,uuid)','EXECUTE')"
                    )
                ).one()
                assert tuple(privileges) == (True, False, True)
                proposal = prepare_reuse(c, progress.associations, org, target, url, batch)
                assert proposal.evidence.source_item is not None
                with pytest.raises(DBAPIError) as blocked:
                    workers.submit(lifecycle.stage, org, request).result(timeout=5)
                original = blocked.value.orig
                assert original is not None and original.args and isinstance(original.args[0], dict)
                assert original.args[0].get("C") == "55P03"
        assert lifecycle.stage(org, request).stage == "fenced"
        with pytest.raises(AuthorizationDenied):
            with progress.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
                prepare_reuse(c, progress.associations, org, target, url, batch)
    finally:
        other.engine.dispose()


@pytest.mark.parametrize("route", ["pdf", "article_xml", "provider"])
@pytest.mark.parametrize(
    "change", ["revoked_policy", "retention", "suppression", "deleted", "expired"]
)
def test_bound_source_authority_changes_refuse_before_copy(
    scenario: Scenario, route: str, change: str
) -> None:
    progress, source, target, batch, url = source_target(scenario, route)
    org = scenario.organizations[0]
    Discovery(progress.database, progress.token, SETTINGS)._plan_bound_reuse(org, target, 1)
    if change == "revoked_policy":
        with scenario.client() as client:
            csrf = scenario.login(client, "owner")
            response = client.post(
                source_path(scenario) + "/policy-state",
                headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
            )
            assert response.status_code == 200
    elif change == "suppression":
        bundle = progress.associations.detail(org, batch)
        assert bundle.candidates
        Lifecycle(progress.database, progress.token, SETTINGS).suppress(
            org,
            SuppressionCreate(
                kind="contact",
                value=bundle.candidates[0].address.raw_address,
                reason="privacy_request",
            ),
        )
    elif change == "deleted":
        Lifecycle(progress.database, progress.token, SETTINGS).stage(
            org, DeletionRequest(job_id=source, reason="privacy_request")
        )
    elif change == "expired":
        admin = create_engine(scenario.admin_url, hide_parameters=True)
        try:
            with admin.begin() as c:
                result = c.execute(
                    text(
                        "UPDATE emailmonitor.lifecycle_job_deadlines "
                        "SET contact_deadline=clock_timestamp()-interval '1 second' "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": source},
                )
                assert result.rowcount == 1
        finally:
            admin.dispose()
    else:
        mutate_authority(scenario, progress, source, "retention")
    with pytest.raises(AuthorizationDenied):
        with progress.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            prepare_reuse(c, progress.associations, org, target, url, batch)
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND job_id=:job"
                    ),
                    {"org": org, "job": target},
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()


@pytest.mark.parametrize("route", ["pdf", "article_xml", "provider"])
def test_bound_reuse_respects_user_cutoff(scenario: Scenario, route: str) -> None:
    progress, _, _, _, url = source_target(scenario, route)
    org = scenario.organizations[0]
    body = {
        **request_body(),
        "input": {"type": "url", "url": url},
        "reuse": {
            "mode": "verified_retained",
            "fresh_since": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
        },
    }
    if route == "pdf":
        options = body["options"]
        assert isinstance(options, dict)
        options["allow_pdf"] = True
    ledger = Ledger(progress.database, progress.token, SETTINGS)
    target = ledger.create(org, JobRequest.model_validate(body), str(uuid4()))
    Discovery(progress.database, progress.token, SETTINGS).plan(org, target, 1)
    with pytest.raises(HTTPException) as denied:
        materialize_draft(progress.associations, org, target, url)
    assert denied.value.status_code == 409
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.article_observations "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": target},
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize("route", ["pdf", "article_xml", "provider"])
def test_bound_reuse_never_resolves_foreign_tenant_batch(scenario: Scenario, route: str) -> None:
    _, _, _, foreign_batch, url = source_target(scenario, route)
    identities = dict(scenario.identities)
    identities["owner"], identities["owner_b"] = identities["owner_b"], identities["owner"]
    other = replace(
        scenario,
        organizations=(scenario.organizations[1], scenario.organizations[0]),
        identities=identities,
    )
    progress, _, target, _, other_url = source_target(other, route)
    assert other_url == url
    org = other.organizations[0]
    Discovery(progress.database, progress.token, SETTINGS)._plan_bound_reuse(org, target, 1)
    with pytest.raises(AuthorizationDenied):
        with progress.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            prepare_reuse(c, progress.associations, org, target, url, foreign_batch)


@pytest.mark.parametrize("route", ["pdf", "article_xml", "provider"])
def test_public_bound_reuse_review_export_and_source_deletion(
    scenario: Scenario, route: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress, source, _, source_batch, url = source_target(scenario, route)
    org = scenario.organizations[0]
    source_bundle = progress.associations.detail(org, source_batch)
    source_association = next(
        a
        for a in source_bundle.associations
        if a.state in {"accepted", "needs_review"} and a.author_id is not None and a.evidence_ids
    )
    if source_association.state == "needs_review":
        progress.associations.review(
            org,
            source_batch,
            Review(
                association_id=source_association.id,
                expected_revision=source_association.revision,
                action="accept",
                evidence_ids=source_association.evidence_ids,
                reason="Reviewed authored source evidence",
            ),
        )
    body = {
        **request_body(),
        "input": {"type": "url", "url": url},
        "reuse": {"mode": "verified_retained", "fresh_since": "2000-01-01T00:00:00Z"},
    }
    if route == "pdf":
        options = body["options"]
        assert isinstance(options, dict)
        options["allow_pdf"] = True
    with fixture_client(scenario) as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf, "Idempotency-Key": str(uuid4())}
        root = f"/api/v1/organizations/{org}/jobs"
        created = client.post(root, headers=headers, json=body)
        assert created.status_code == 201
        target = UUID(created.json()["id"])
        assert client.post(root, headers=headers, json=body).json()["id"] == str(target)
        planned = client.post(
            root + f"/{target}/plan", headers=headers, json={"expected_revision": 1}
        )
        assert planned.status_code == 200
        assert planned.json()["plan"]["reason"] == "retained_reuse_authored"

    def no_acquisition(*_: object, **__: object) -> None:
        raise AssertionError("Retained reuse must never acquire fresh data")

    monkeypatch.setattr(PdfExtraction, "isolated_fixture", no_acquisition)
    monkeypatch.setattr(XmlExtraction, "isolated_fixture", no_acquisition)
    monkeypatch.setattr(progress.extraction, "fixture", no_acquisition)
    progress.start(org, target, progress.snapshot(org, target).revision)
    work = claim(progress, org, target)
    outcome = ExecutionDispatcher(progress).process(work)
    assert outcome == "needs_review"
    target_batch = progress.items(org, target)[0].batch_id
    assert target_batch is not None and target_batch != source_batch
    target_bundle = progress.associations.detail(org, target_batch)
    assert target_bundle.associations and all(
        a.state != "accepted" for a in target_bundle.associations
    )
    assert progress.associations.quality(org, target_batch).observation_route == (
        "article_xml" if route == "provider" else route
    )
    target_association = next(
        a
        for a in target_bundle.associations
        if a.state == "needs_review" and a.author_id is not None and a.evidence_ids
    )
    results = Results(progress.database, progress.token, SETTINGS)
    assert results.contacts(org, Filters(job_id=target)).items == ()
    progress.associations.review(
        org,
        target_batch,
        Review(
            association_id=target_association.id,
            expected_revision=target_association.revision,
            action="accept",
            evidence_ids=target_association.evidence_ids,
            reason="Reviewed independent target evidence",
        ),
    )
    contacts = results.contacts(org, Filters(job_id=target)).items
    assert len(contacts) == 1 and contacts[0].observation_origin == "reused"
    synthetic_address = contacts[0].raw_address.encode()
    exports = []
    for format in ("csv", "xlsx"):
        export = ready(results, org, target, format=format)
        with ZipFile(io.BytesIO(results.download(org, export).body)) as archive:
            files = (
                ["contacts.csv"]
                if format == "csv"
                else [name for name in archive.namelist() if name.startswith("xl/worksheets/")]
            )
            assert any(synthetic_address in archive.read(name) for name in files)
        exports.append(export)
    lifecycle = Lifecycle(progress.database, progress.token, SETTINGS)
    marker = lifecycle.stage(org, DeletionRequest(job_id=source, reason="privacy_request"))
    for export in exports:
        with pytest.raises(AuthorizationDenied):
            results.download(org, export)
    assert lifecycle.purge(org, marker.id).stage == "purged"
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with admin.connect() as c:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations "
                        "WHERE organization_id=:org AND job_id IN (:source,:target)"
                    ),
                    {"org": org, "source": source, "target": target},
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()

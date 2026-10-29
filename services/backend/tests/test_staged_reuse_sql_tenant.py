"""Disposable PostgreSQL bound-reuse checks; not parser-isolation acceptance."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_pdf_pipeline_tenant import planned_pdf
from test_progress_tenant import claim
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario
from test_xml_pipeline_tenant import planned_xml

from emailmonitor.associations.reuse_materialization import _stage_bound_reuse
from emailmonitor.associations.reuse_preparation import prepare_reuse
from emailmonitor.discovery.service import Discovery
from emailmonitor.extraction.pdf import parse_pdf
from emailmonitor.extraction.pdf_fixture import pdf_bytes
from emailmonitor.extraction.pdf_retained import retain_pdf
from emailmonitor.extraction.pdf_service import PdfExtraction
from emailmonitor.extraction.sciencedirect import parse_article
from emailmonitor.extraction.xml_retained import XML_IDENTIFIER, retain_xml
from emailmonitor.extraction.xml_service import XmlExtraction, fixture_bytes
from emailmonitor.lifecycle.models import DeletionRequest
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied, Database, TenantContext
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import bound
from emailmonitor.progress.service import Progress


def source_target(scenario: Scenario, route: str) -> tuple[Progress, UUID, UUID, UUID, str]:
    # Host parsing is used solely to construct authored SQL fixtures. It is not
    # evidence of the separately required network-none parser acceptance.
    progress, source = (
        planned_pdf(scenario, "article-a.pdf") if route == "pdf" else planned_xml(scenario)
    )
    org = scenario.organizations[0]
    progress.start(org, source, progress.snapshot(org, source).revision)
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
            binding, excerpts = extraction_xml.binding(org, source, 1)
            observed_xml = parse_article(fixture_bytes(), XML_IDENTIFIER)
            extraction_xml.commit_xml(org, source, retain_xml(observed_xml, binding, excerpts))
        batch = progress.associations.derive(org, source, work.url, 1)
        progress.finish(work, batch)
    assert progress.associations.detail(org, batch).observation_route == route

    target = uuid4()
    body = {
        **request_body(),
        "input": {"type": "url", "url": work.url},
        "reuse": {"mode": "verified_retained", "fresh_since": "2000-01-01T00:00:00Z"},
    }
    if route == "pdf":
        body["options"]["allow_pdf"] = True
    with progress.database.tenant(progress.token, org, Capability.ACQUIRE_SOURCE) as (c, ctx):
        assert isinstance(ctx, TenantContext)
        c.execute(
            text(
                "INSERT INTO emailmonitor.jobs (organization_id,id,created_by,kind,request,state) "
                "VALUES(:org,:job,:actor,'extraction',CAST(:body AS jsonb),'draft')"
            ),
            {"org": org, "job": target, "actor": ctx.identity_id, "body": json.dumps(body)},
        )
    return progress, source, target, batch, work.url


@pytest.mark.parametrize("route", ["pdf", "article_xml"])
def test_bound_non_html_copy_keeps_original_binding_and_replays(
    scenario: Scenario, route: str
) -> None:
    progress, source, target, batch, url = source_target(scenario, route)
    org = scenario.organizations[0]
    discovery = Discovery(progress.database, progress.token, SETTINGS)
    _, selected = _stage_bound_reuse(discovery, progress.associations, org, target, 1)
    assert selected == batch
    _, replay = _stage_bound_reuse(discovery, progress.associations, org, target, 1)
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
    assert progress.associations.detail(org, batch).observation_route == route


@pytest.mark.parametrize("route", ["pdf", "article_xml"])
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

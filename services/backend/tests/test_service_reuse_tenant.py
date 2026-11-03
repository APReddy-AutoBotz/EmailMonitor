"""Authored CI-only service-principal proof for target-owned retained reuse.

The existing service fixture's exact genuine-CI guard runs before provisioning
roles or synthetic state. Local collection/skips are not service acceptance.
"""

from uuid import UUID, uuid4

import pytest
from emailmonitor.associations.reuse_materialization import materialize_draft
from emailmonitor.associations.service import Associations
from emailmonitor.discovery.service import Discovery
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.execution import ExecutionDispatcher
from emailmonitor.progress.service import Progress
from emailmonitor.runtime.authority import ServiceWork
from sqlalchemy import text
from test_association_tenant import URL
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_progress_tenant import claim, drain
from test_service_authority_tenant import ServiceCase
from test_service_authority_tenant import _service_ci_guard as _service_ci_guard
from test_service_authority_tenant import service_case as service_case
from test_tenant_foundation import scenario as scenario


def prepare_service_reuse(case: ServiceCase, route: str = "html") -> tuple[UUID, UUID]:
    org, source = case.scope.organization, case.scope.resource
    if route == "html":
        drain(case.progress, org, source)
        url = URL
    else:
        from test_staged_reuse_sql_tenant import finish_source

        _, url = finish_source(case.progress, org, source, route)
    human = Associations(case.progress.database, case.progress.token, SETTINGS)
    with human.database.tenant(human.token, org, Capability.READ_ORGANIZATION) as (c, _):
        source_batch: UUID = c.execute(
            text(
                "SELECT id FROM emailmonitor.association_batches "
                "WHERE organization_id=:org AND job_id=:job AND article_url=:url"
            ),
            {"org": org, "job": source, "url": url},
        ).scalar_one()
    body = {
        **request_body(),
        "input": {"type": "url", "url": url},
        "reuse": {"mode": "verified_retained", "fresh_since": "2000-01-01T00:00:00Z"},
    }
    if route == "pdf":
        options = body["options"]
        assert isinstance(options, dict)
        options["allow_pdf"] = True
    request = JobRequest.model_validate(body)
    target = Ledger(human.database, human.token, SETTINGS).create(org, request, str(uuid4()))
    Discovery(human.database, human.token, SETTINGS).plan(org, target, 1)
    assert materialize_draft(human, org, target, url) == source_batch
    owner = Progress(human.database, human.token, SETTINGS)
    owner.start(org, target, owner.snapshot(org, target).revision)
    with human.database.tenant(human.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
        c.execute(
            text(
                "SELECT emailmonitor.delegate_service_work(:org,:principal,:job,'extraction',21600)"
            ),
            {"org": org, "principal": case.principal, "job": target},
        )
    return target, source_batch


@pytest.mark.parametrize("service_case", ["html", "pdf", "article_xml", "provider"], indirect=True)
def test_service_worker_reads_only_its_target_and_never_acquires_fresh_bytes(
    service_case: ServiceCase, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    case = service_case
    org, source = case.scope.organization, case.scope.resource
    route = request.node.callspec.params["service_case"]
    target, source_batch = prepare_service_reuse(case, route)
    human = Associations(case.progress.database, case.progress.token, SETTINGS)
    owner = Progress(human.database, human.token, SETTINGS)
    scope = ServiceWork(organization=org, resource=target, purpose="extraction", generation=1)
    worker = Progress(case.database, scope, SETTINGS)
    with case.database.tenant(scope, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.article_observations "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": source},
            ).scalar_one()
            == 0
        )
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.article_observations "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": target},
            ).scalar_one()
            == 1
        )
    with pytest.raises(AuthorizationDenied):
        Associations(case.database, scope, SETTINGS).detail(org, source_batch)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Retained reuse cannot acquire a fresh fixture")

    monkeypatch.setattr(worker.extraction, "fixture", forbidden)
    from emailmonitor.extraction.pdf_service import PdfExtraction
    from emailmonitor.extraction.xml_service import XmlExtraction

    monkeypatch.setattr(PdfExtraction, "isolated_fixture", forbidden)
    monkeypatch.setattr(XmlExtraction, "isolated_fixture", forbidden)
    work = claim(worker, org, target)
    assert ExecutionDispatcher(worker).process(work) == "needs_review"
    assert owner.snapshot(org, target).state == "completed"
    with human.database.tenant(human.token, org, Capability.READ_ORGANIZATION) as (c, _):
        target_batch: UUID = c.execute(
            text(
                "SELECT id FROM emailmonitor.association_batches "
                "WHERE organization_id=:org AND job_id=:job AND article_url=:url"
            ),
            {"org": org, "job": target, "url": work.url},
        ).scalar_one()
    assert human.detail(org, target_batch).associations[0].state == "needs_review"

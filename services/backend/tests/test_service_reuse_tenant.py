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


def prepare_service_reuse(case: ServiceCase) -> tuple[UUID, UUID]:
    org, source = case.scope.organization, case.scope.resource
    drain(case.progress, org, source)
    human = Associations(case.progress.database, case.progress.token, SETTINGS)
    with human.database.tenant(human.token, org, Capability.READ_ORGANIZATION) as (c, _):
        source_batch: UUID = c.execute(
            text(
                "SELECT id FROM emailmonitor.association_batches "
                "WHERE organization_id=:org AND job_id=:job AND article_url=:url"
            ),
            {"org": org, "job": source, "url": URL},
        ).scalar_one()
    request = JobRequest.model_validate(
        {
            **request_body(),
            "input": {"type": "url", "url": URL},
            "reuse": {"mode": "verified_retained", "fresh_since": "2000-01-01T00:00:00Z"},
        }
    )
    target = Ledger(human.database, human.token, SETTINGS).create(org, request, str(uuid4()))
    Discovery(human.database, human.token, SETTINGS).plan(org, target, 1)
    assert materialize_draft(human, org, target, URL) == source_batch
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


def test_service_worker_reads_only_its_target_and_never_acquires_fresh_bytes(
    service_case: ServiceCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = service_case
    org, source = case.scope.organization, case.scope.resource
    target, source_batch = prepare_service_reuse(case)
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
    work = claim(worker, org, target)
    assert worker.process_fixture(work) == "needs_review"
    assert owner.snapshot(org, target).state == "completed"
    with human.database.tenant(human.token, org, Capability.READ_ORGANIZATION) as (c, _):
        target_batch: UUID = c.execute(
            text(
                "SELECT id FROM emailmonitor.association_batches "
                "WHERE organization_id=:org AND job_id=:job AND article_url=:url"
            ),
            {"org": org, "job": target, "url": URL},
        ).scalar_one()
    assert human.detail(org, target_batch).associations[0].state == "needs_review"

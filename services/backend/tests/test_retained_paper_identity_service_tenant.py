"""Narrow service export proof, restricted to the unchanged genuine-CI fixture."""

from uuid import UUID, uuid4

import pytest
from emailmonitor.lifecycle.models import DeletionRequest
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.results.models import ExportInput
from emailmonitor.results.service import Results
from sqlalchemy import text
from test_durable_jobs import SETTINGS
from test_progress_tenant import drain
from test_retained_article_filters_service_tenant import export_worker
from test_retained_article_filters_tenant import additional_job
from test_service_authority_tenant import ServiceCase
from test_service_authority_tenant import _service_ci_guard as _service_ci_guard
from test_service_authority_tenant import service_case as service_case
from test_tenant_foundation import scenario as scenario


@pytest.mark.parametrize("outcomes", [False, True])
@pytest.mark.parametrize("delete", [False, True])
def test_paper_export_worker_rechecks_exact_members_without_read_expansion(
    service_case: ServiceCase, outcomes: bool, delete: bool
) -> None:
    case = service_case
    org, first = case.scope.organization, case.scope.resource
    drain(case.progress, org, first)
    second = additional_job(
        case.progress, org, "https://synthetic.publisher.example/article-a.html"
    )
    human = Results(case.progress.database, case.progress.token, SETTINGS)
    request = ExportInput(
        format="xlsx",
        purpose="academic_contact_research",
        paper_doi="10.9999/synthetic.article-a",
        include_article_outcomes=outcomes,
    )
    worker, export, _ = export_worker(case, human, request)
    message = next(row for row in human.pending(org) if row["export_id"] == export)
    work = worker.claim(org, export, UUID(str(message["event_id"])), 1)
    assert work is not None
    assert {c.job_id for c in work.snapshot.contacts} == {first, second}
    assert len(work.snapshot.article_outcomes) == (2 if outcomes else 0)
    with case.database.tenant(worker.token, org, Capability.EXPORT_RESULTS) as (c, _):
        assert (
            c.execute(text("SELECT count(*) FROM emailmonitor.article_observations")).scalar_one()
            == 0
        )
        assert not c.execute(
            text(
                "SELECT has_function_privilege(current_user,"
                "'emailmonitor.retained_paper_batch_matches(uuid,uuid,text)','EXECUTE')"
            )
        ).scalar_one()
    other = human.create(org, request, str(uuid4()))
    with pytest.raises(AuthorizationDenied):
        worker.claim(org, other.id, uuid4(), 1)
    if delete:
        Lifecycle(human.database, human.token, SETTINGS).stage(
            org, DeletionRequest(job_id=second, reason="privacy_request")
        )
        assert not worker.process(work)
        with pytest.raises(AuthorizationDenied):
            human.download(org, export)
    else:
        assert worker.process(work)
        assert human.download(org, export).body
        assert worker.claim(org, export, UUID(str(message["event_id"])), 1) is None
    with pytest.raises(AuthorizationDenied):
        worker.download(org, export)

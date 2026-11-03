"""Actual narrow export-worker execution; no added service read grants or members."""

from uuid import UUID, uuid4

import pytest
from emailmonitor.lifecycle.models import DeletionRequest, Retention, RetentionUpdate
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.results.models import ExportInput
from emailmonitor.results.service import Results
from emailmonitor.runtime.authority import ServiceWork
from sqlalchemy import text
from test_durable_jobs import SETTINGS
from test_progress_tenant import drain
from test_results_tenant import options
from test_retained_article_filters_tenant import inherited_twice
from test_service_authority_tenant import ServiceCase
from test_service_authority_tenant import _service_ci_guard as _service_ci_guard
from test_service_authority_tenant import service_case as service_case
from test_tenant_foundation import scenario as scenario


def filtered_request(case: ServiceCase, inherited: bool) -> tuple[Results, ExportInput, UUID]:
    org, original = case.scope.organization, case.scope.resource
    human = Results(case.progress.database, case.progress.token, SETTINGS)
    if inherited:
        _, selected = inherited_twice(case.progress, org, original)
        item = human.outcomes(org, selected, article_outcome_presence="observed_candidate").items[0]
        request = options(selected, item_id=str(item.item_id), include_article_outcomes=False)
    else:
        drain(case.progress, org, original)
        selected = original
        item = human.outcomes(
            org, selected, article_outcome_presence="completed_without_candidate"
        ).items[0]
        request = options(
            selected,
            item_id=str(item.item_id),
            article_outcome_presence="completed_without_candidate",
        )
    return human, request, selected


def export_worker(
    case: ServiceCase, human: Results, request: ExportInput
) -> tuple[Results, UUID, UUID]:
    org = case.scope.organization
    state = human.create(org, request, str(uuid4()))
    with human.database.tenant(human.token, org, Capability.EXPORT_RESULTS) as (c, _):
        grant: UUID = c.execute(
            text("SELECT emailmonitor.delegate_service_work(:org,:principal,:id,'export',21600)"),
            {"org": org, "principal": case.principal, "id": state.id},
        ).scalar_one()
    return (
        Results(
            case.database,
            ServiceWork(organization=org, resource=state.id, purpose="export", generation=1),
            SETTINGS,
        ),
        state.id,
        grant,
    )


@pytest.mark.parametrize("inherited", [False, True])
def test_actual_worker_filtered_no_contact_and_inherited_contacts_only(
    service_case: ServiceCase, inherited: bool
) -> None:
    case = service_case
    org = case.scope.organization
    human, request, selected = filtered_request(case, inherited)
    selected_batch = human.outcomes(org, selected, item_id=request.item_id).items[0].batch_id
    preview = human.preview(org, request)
    worker, export, _ = export_worker(case, human, request)
    message = next(row for row in human.pending(org) if row["export_id"] == export)
    claimed = worker.claim(org, export, UUID(str(message["event_id"])), 1)
    assert claimed is not None
    assert len(claimed.snapshot.contacts) == preview.contacts
    assert len(claimed.snapshot.article_outcomes) == preview.article_outcomes
    if inherited:
        assert claimed.snapshot.contacts and claimed.snapshot.article_outcomes == ()
        assert all(row.job_id == case.scope.resource for row in claimed.snapshot.contacts)
    else:
        assert claimed.snapshot.contacts == () and len(claimed.snapshot.article_outcomes) == 1
    with case.database.tenant(worker.token, org, Capability.EXPORT_RESULTS) as (c, _):
        # New validation never becomes new batch/job read authority.
        assert (
            c.execute(text("SELECT count(*) FROM emailmonitor.article_observations")).scalar_one()
            == 0
        )
        assert (
            c.execute(text("SELECT count(*) FROM emailmonitor.association_candidates")).scalar_one()
            == 0
        )
        for role in (
            "emailmonitor_runtime",
            "emailmonitor_worker",
            "emailmonitor_publisher",
            "emailmonitor_authenticator",
        ):
            for function in (
                "retained_article_binding(uuid,uuid,uuid,uuid,boolean)",
                "retained_export_article_valid(uuid,uuid)",
            ):
                assert (
                    c.execute(
                        text("SELECT has_function_privilege(:role,:function,'EXECUTE')"),
                        {"role": role, "function": "emailmonitor." + function},
                    ).scalar_one()
                    is False
                )
        if inherited:
            assert (
                c.execute(
                    text("SELECT emailmonitor.execution_read_allowed(:org,:job)"),
                    {"org": org, "job": selected},
                ).scalar_one()
                is False
            )
        else:
            assert (
                c.execute(
                    text("SELECT emailmonitor.service_batch_visible(:org,:batch)"),
                    {"org": org, "batch": selected_batch},
                ).scalar_one()
                is False
            )
    with pytest.raises(AuthorizationDenied):
        with case.database.tenant(worker.token, org, Capability.EXPORT_RESULTS) as (c, _):
            c.execute(
                text("SELECT emailmonitor.retained_export_article_valid(:org,:export)"),
                {"org": org, "export": export},
            )
    assert worker.process(claimed)
    assert human.download(org, export).body
    assert worker.claim(org, export, UUID(str(message["event_id"])), 1) is None
    other = human.create(org, request, str(uuid4()))
    with pytest.raises(AuthorizationDenied):
        worker.claim(org, other.id, uuid4(), 1)
    with pytest.raises(AuthorizationDenied):
        worker.download(org, export)
    with case.admin.connect() as c:
        if not inherited:
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.export_members "
                        "WHERE organization_id=:org AND export_id=:id"
                    ),
                    {"org": org, "id": export},
                ).scalar_one()
                == 0
            )


@pytest.mark.parametrize(
    "change", ["selected_deletion", "source_deletion", "retention", "revocation"]
)
def test_actual_worker_filtered_authority_changes_between_claim_and_finish(
    service_case: ServiceCase, change: str
) -> None:
    case = service_case
    org = case.scope.organization
    human, request, selected = filtered_request(case, True)
    worker, export, grant = export_worker(case, human, request)
    message = next(row for row in human.pending(org) if row["export_id"] == export)
    claimed = worker.claim(org, export, UUID(str(message["event_id"])), 1)
    assert claimed is not None
    lifecycle = Lifecycle(human.database, human.token, SETTINGS)
    if change.endswith("deletion"):
        lifecycle.stage(
            org,
            DeletionRequest(
                job_id=selected if change == "selected_deletion" else case.scope.resource,
                reason="privacy_request",
            ),
        )
        if change == "source_deletion":
            assert (
                human.outcomes(org, selected, article_outcome_presence="observed_candidate").items
                == ()
            )
            unresolved = human.outcomes(
                org, selected, item_id=request.item_id, article_outcome_presence="unresolved"
            )
            assert len(unresolved.items) == 1
    elif change == "retention":
        before = lifecycle.retention(org)
        lifecycle.update_retention(
            org,
            RetentionUpdate(expected_revision=before.revision, retention=Retention(contact_days=0)),
        )
    else:
        with human.database.tenant(human.token, org, Capability.EXPORT_RESULTS) as (c, _):
            c.execute(
                text("SELECT emailmonitor.revoke_service_work(:org,:grant)"),
                {"org": org, "grant": grant},
            )
    try:
        assert not worker.process(claimed)
    except AuthorizationDenied:
        pass  # Revoked authority may also prevent recording the failed attempt.
    with pytest.raises(AuthorizationDenied):
        human.download(org, export)

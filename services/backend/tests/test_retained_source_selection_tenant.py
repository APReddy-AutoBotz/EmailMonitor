"""Existing single-source PostgreSQL selection; no new source or acquisition grants."""

import json
from typing import Final
from uuid import uuid4

import pytest
from emailmonitor.lifecycle.models import DeletionRequest, Retention, RetentionUpdate
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict
from emailmonitor.results.models import ExportInput, Filters
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from test_association_tenant import client
from test_durable_jobs import SETTINGS
from test_results_tenant import lease
from test_retained_paper_identity_tenant import DOI, pair
from test_selection_handoff_tenant import rows
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario

SOURCE: Final = "synthetic-publisher"


def test_actual_source_pages_combined_selectors_and_legacy_cursors(scenario: Scenario) -> None:
    _, results, first, second = pair(scenario)
    org = scenario.organizations[0]
    selected = Filters(source_id=SOURCE, paper_doi=DOI)
    page = results.contacts(org, selected, limit=1)
    assert page.next_cursor
    other = results.contacts(org, selected, page.next_cursor, 1)
    assert {row.job_id for row in page.items + other.items} == {first, second}
    assert not other.next_cursor
    assert (
        results.contacts(org, Filters(paper_doi=DOI)).items == results.contacts(org, selected).items
    )
    with pytest.raises(ValueError):
        results.contacts(org, Filters(paper_doi=DOI), page.next_cursor)
    outcomes = results.outcomes(org, source_id=SOURCE, paper_doi=DOI, limit=1)
    assert outcomes.next_cursor
    last = results.outcomes(
        org, cursor=outcomes.next_cursor, source_id=SOURCE, paper_doi=DOI, limit=1
    )
    assert len(last.items) == 1 and not last.next_cursor
    with pytest.raises(ValueError):
        results.outcomes(org, cursor=outcomes.next_cursor, paper_doi=DOI)
    item = results.outcomes(org, first, source_id=SOURCE).items[0]
    filters = Filters(
        source_id=SOURCE,
        job_id=first,
        item_id=item.item_id,
        paper_doi=DOI,
        query="alex.chen",
        author_target="corresponding",
    )
    assert len(results.contacts(org, filters).items) == 1
    assert not results.contacts(org, filters.model_copy(update={"query": "absent"})).items
    with pytest.raises(AuthorizationDenied):
        results.contacts(org, filters.model_copy(update={"job_id": second}))
    with pytest.raises(AuthorizationDenied):
        results.contacts(scenario.organizations[1], filters)


@pytest.mark.parametrize("format", ["csv", "xlsx"])
def test_actual_source_export_membership_replay_and_default_compatibility(
    scenario: Scenario, format: str
) -> None:
    _, results, first, _ = pair(scenario)
    org = scenario.organizations[0]
    item = results.outcomes(org, first).items[0]
    request = ExportInput.model_validate(
        dict(
            format=format,
            purpose="academic_contact_research",
            source_id=SOURCE,
            job_id=str(first),
            item_id=str(item.item_id),
            paper_doi=DOI,
            query="alex.chen",
            author_target="corresponding",
            article_outcome_presence="observed_candidate",
        )
    )
    preview = results.preview(org, request)
    assert (preview.contacts, preview.article_outcomes) == (1, 1)
    key = str(uuid4())
    state = results.create(org, request, key)
    assert results.create(org, request, key).id == state.id
    with pytest.raises(RevisionConflict):
        results.create(org, request.model_copy(update={"source_id": None}), key)
    work = lease(results, org, state.id)
    assert work.snapshot.filters.source_id == SOURCE
    assert len(work.snapshot.contacts) == len(work.snapshot.article_outcomes) == 1
    assert {row.job_id for row in work.snapshot.contacts} == {first}
    assert results.process(work)
    artifact = results.download(org, state.id).body
    assert len(rows(artifact, format, False)) == len(rows(artifact, format, True)) == 2
    legacy = request.model_copy(update={"source_id": None})
    legacy_key = str(uuid4())
    original = results.create(org, legacy, legacy_key)
    assert (
        results.create(
            org, ExportInput.model_validate({**legacy.model_dump(), "source_id": None}), legacy_key
        ).id
        == original.id
    )


def test_actual_source_api_and_sql_refuse_unsupported_identity(scenario: Scenario) -> None:
    _, results, _, _ = pair(scenario)
    org = scenario.organizations[0]
    with client(scenario) as api:
        scenario.login(api, "viewer")
        for endpoint in ("contacts", "article-outcomes"):
            path = f"/api/v1/organizations/{org}/{endpoint}"
            assert len(api.get(path, params={"source_id": SOURCE}).json()["items"]) == 2
            for source in (
                "",
                "elsevier_sciencedirect_v2",
                "https://synthetic.publisher.example",
                "pdf",
            ):
                assert api.get(path, params={"source_id": source}).status_code == 422
            assert (
                api.get(
                    f"/api/v1/organizations/{scenario.organizations[1]}/{endpoint}",
                    params={"source_id": SOURCE},
                ).status_code
                == 404
            )
    invalid_values: tuple[object, ...] = ("", "other", "pdf", True, [])
    for value in invalid_values:
        filters = {**Filters().model_dump(mode="json"), "source_id": value}
        with pytest.raises(DBAPIError), results._tenant(org) as c:
            c.execute(
                text(
                    "SELECT emailmonitor.result_contacts(:org,CAST(:filters AS jsonb),NULL,NULL,10)"
                ),
                {"org": org, "filters": json.dumps(filters)},
            ).all()


@pytest.mark.parametrize("change", ["deletion", "retention", "source", "session"])
@pytest.mark.parametrize("ready", [False, True])
def test_actual_source_selected_exports_keep_lifecycle_fences(
    scenario: Scenario, change: str, ready: bool
) -> None:
    _, results, first, _ = pair(scenario)
    org = scenario.organizations[0]
    request = ExportInput(
        format="xlsx", purpose="academic_contact_research", source_id=SOURCE, paper_doi=DOI
    )
    key = str(uuid4())
    state = results.create(org, request, key)
    work = lease(results, org, state.id)
    if ready:
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
    if ready:
        with pytest.raises(AuthorizationDenied):
            results.download(org, state.id)
    elif change == "session":
        with pytest.raises(AuthorizationDenied):
            results.process(work)
    else:
        assert not results.process(work)

"""Required hosted SQL acceptance for retained selection; local skips are not proof."""

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from emailmonitor.discovery.service import Discovery
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.lifecycle.models import (
    DeletionRequest,
    Retention,
    RetentionUpdate,
    SuppressionCreate,
)
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.service import Progress
from emailmonitor.results.models import ArticleOutcomePresence, Filters
from emailmonitor.results.service import Results
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from test_association_tenant import client, review_request
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_progress_tenant import claim, drain, planned
from test_results_tenant import lease, options, prepared
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario

PRESENCES: tuple[ArticleOutcomePresence, ...] = (
    "observed_candidate",
    "completed_without_candidate",
    "unresolved",
)


def complete_search(s: Scenario) -> tuple[Progress, Results, UUID]:
    progress, job = planned(s)
    org = s.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    drain(progress, org, job)
    return progress, Results(progress.database, progress.token, SETTINGS), job


def additional_job(progress: Progress, org: UUID, url: str) -> UUID:
    body = request_body()
    body["input"] = {"type": "url", "url": url}
    job = Ledger(progress.database, progress.token, SETTINGS).create(
        org, JobRequest.model_validate(body), str(uuid4())
    )
    Discovery(progress.database, progress.token, SETTINGS).plan(org, job, 1)
    progress.start(org, job, progress.snapshot(org, job).revision)
    drain(progress, org, job)
    return job


def inherited_twice(progress: Progress, org: UUID, job: UUID) -> tuple[UUID, UUID]:
    """Real failed-page continuations; no invented identity or altered route policy."""
    progress.process_fixture(claim(progress, org, job))
    for item in progress.items(org, job):
        if item.work_kind != "article":
            continue
        message = next(row for row in progress.pending(org) if row["item_id"] == item.id)
        work = progress.claim(org, job, item.id, UUID(str(message["event_id"])))
        assert work is not None
        progress.process_fixture(work)
    children = []
    for _ in range(2):
        for _ in range(3):
            work = claim(progress, org, job)
            assert work.kind == "discover"
            progress.finish(work, failure="worker_failure")
        job = progress.retry(org, job, progress.snapshot(org, job).revision)
        children.append(job)
    return children[0], children[1]


def test_actual_presence_pages_partition_before_limit_and_item_is_exact(scenario: Scenario) -> None:
    progress, results, job = complete_search(scenario)
    org = scenario.organizations[0]
    original = results.outcomes(org, job).items
    expected = {row.item_id for row in original}
    groups: dict[str, set[UUID]] = {}
    for presence in PRESENCES:
        seen: list[UUID] = []
        cursor = None
        for _ in range(5):
            page = results.outcomes(org, job, cursor, 1, article_outcome_presence=presence)
            seen.extend(row.item_id for row in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
        assert cursor is None and len(seen) == len(set(seen))
        groups[presence] = set(seen)
    assert {key: len(value) for key, value in groups.items()} == {
        "observed_candidate": 2,
        "completed_without_candidate": 1,
        "unresolved": 1,
    }
    assert set.union(*groups.values()) == expected
    for row in original:
        selected = Filters(
            job_id=job,
            item_id=row.item_id,
            states=("accepted", "needs_review", "unmatched", "rejected"),
        )
        assert results.outcomes(org, job, item_id=row.item_id).items == (row,)
        contacts = results.contacts(org, selected).items
        assert all(contact.batch_id == row.batch_id for contact in contacts)
        if row.state in {"no_contact", "unsupported"}:
            assert contacts == ()
    positive = next(row for row in original if row.item_id in groups["observed_candidate"])
    unrelated = additional_job(progress, org, positive.source_url)
    assert results.outcomes(org, unrelated).items[0].batch_id != positive.batch_id
    with pytest.raises(AuthorizationDenied):
        results.contacts(org, Filters(job_id=unrelated, item_id=positive.item_id))
    with pytest.raises(AuthorizationDenied):
        results.outcomes(org, unrelated, item_id=positive.item_id)


def test_actual_item_api_foreign_missing_nonarticle_and_legacy_sql_acl(scenario: Scenario) -> None:
    progress, results, job = complete_search(scenario)
    org = scenario.organizations[0]
    item = results.outcomes(org, job).items[0]
    nonarticle = next(row.id for row in progress.items(org, job) if row.work_kind == "discover")
    with client(scenario) as api:
        scenario.login(api, "viewer")
        path = f"/api/v1/organizations/{org}"
        for endpoint in ("contacts", "article-outcomes"):
            assert (
                api.get(path + "/" + endpoint, params={"item_id": str(item.item_id)}).status_code
                == 422
            )
            for bad in (uuid4(), nonarticle):
                assert (
                    api.get(
                        path + "/" + endpoint, params={"job_id": str(job), "item_id": str(bad)}
                    ).status_code
                    == 404
                )
            assert (
                api.get(
                    path.replace(str(org), str(scenario.organizations[1])) + "/" + endpoint,
                    params={"job_id": str(job), "item_id": str(item.item_id)},
                ).status_code
                == 404
            )
    with results.database.tenant(results.token, org, Capability.READ_ORGANIZATION) as (c, _):
        legacy: Sequence[object] = (
            c.execute(
                text("SELECT emailmonitor.result_outcomes(:org,NULL,NULL,NULL,200)"), {"org": org}
            )
            .scalars()
            .all()
        )
        assert len(legacy) == 4
        for name in (
            "retained_article_job_current(uuid,uuid)",
            "retained_article_batch_current(uuid,uuid)",
            "retained_article_binding(uuid,uuid,uuid,uuid,boolean)",
            "retained_export_article_valid(uuid,uuid)",
            "retained_observation_presence(jsonb,bigint)",
        ):
            assert (
                c.execute(
                    text("SELECT has_function_privilege(current_user,:name,'EXECUTE')"),
                    {"name": "emailmonitor." + name},
                ).scalar_one()
                is False
            )
    with pytest.raises(DBAPIError):
        with results.database.tenant(results.token, org, Capability.READ_ORGANIZATION) as (c, _):
            c.execute(
                text("SELECT emailmonitor.retained_article_binding(:org,:job,:item,NULL,false)"),
                {"org": org, "job": job, "item": item.item_id},
            )
    admin = create_engine(scenario.admin_url)
    try:
        for role in ("emailmonitor_worker", "emailmonitor_publisher", "emailmonitor_authenticator"):
            with pytest.raises(DBAPIError):
                with admin.begin() as c:
                    c.exec_driver_sql("SET LOCAL ROLE " + role)
                    assert c.execute(text("SELECT current_user")).scalar_one() == role
                    c.execute(
                        text("SELECT emailmonitor.retained_export_article_valid(:org,:export)"),
                        {"org": org, "export": uuid4()},
                    )
    finally:
        admin.dispose()


def test_actual_review_rejection_does_not_remove_observed_candidate(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    progress = Progress(results.database, results.token, SETTINGS)
    item = results.outcomes(org, job).items[0]
    assert item.batch_id is not None
    progress.associations.review(
        org,
        item.batch_id,
        review_request(progress.associations, org, item.batch_id, action="reject"),
    )
    assert results.contacts(org, Filters(job_id=job, item_id=item.item_id)).items == ()
    assert results.contacts(
        org, Filters(job_id=job, item_id=item.item_id, states=("rejected",))
    ).items
    assert results.outcomes(org, job, article_outcome_presence="observed_candidate").items == (
        item,
    )
    assert (
        results.outcomes(org, job, article_outcome_presence="completed_without_candidate").items
        == ()
    )


def test_actual_export_preview_membership_filter_idempotency_and_legacy_defaults(
    scenario: Scenario,
) -> None:
    _, results, job = complete_search(scenario)
    org = scenario.organizations[0]
    contact_count = len(results.contacts(org, Filters(job_id=job)).items)
    for presence in PRESENCES:
        request = options(job, article_outcome_presence=presence)
        preview = results.preview(org, request)
        state = results.create(org, request, str(uuid4()))
        claimed = lease(results, org, state.id)
        assert len(claimed.snapshot.contacts) == preview.contacts == contact_count
        assert len(claimed.snapshot.article_outcomes) == preview.article_outcomes
        assert claimed.snapshot.filters.article_outcome_presence == presence
        assert results.process(claimed)
        assert results.download(org, state.id).body
    selected = results.outcomes(org, job).items[0]
    key = str(uuid4())
    request = options(job, item_id=str(selected.item_id))
    first = results.create(org, request, key)
    assert results.create(org, request, key).id == first.id
    for changed in (
        options(job),
        options(job, item_id=str(selected.item_id), article_outcome_presence="unresolved"),
    ):
        with pytest.raises(RevisionConflict):
            results.create(org, changed, key)
    key = str(uuid4())
    legacy = results.create(org, options(job), key)
    assert (
        results.create(org, options(job, item_id=None, article_outcome_presence="all"), key).id
        == legacy.id
    )
    claimed = lease(results, org, legacy.id)
    assert claimed.snapshot.article_filter_bindings == ()
    assert results.process(claimed)


def test_actual_second_continuation_uses_original_batch_and_child_authority(
    scenario: Scenario,
) -> None:
    progress, original = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, original, progress.snapshot(org, original).revision)
    predecessor, child = inherited_twice(progress, org, original)
    results = Results(progress.database, progress.token, SETTINGS)
    item = results.outcomes(org, child, article_outcome_presence="observed_candidate").items[0]
    assert item.inherited_job_id == predecessor and item.batch_id is not None
    contacts = results.contacts(org, Filters(job_id=child, item_id=item.item_id)).items
    assert contacts and all(
        contact.job_id == original and contact.batch_id == item.batch_id for contact in contacts
    )
    request = options(child, item_id=str(item.item_id), include_article_outcomes=False)
    state = results.create(org, request, str(uuid4()))
    claimed = lease(results, org, state.id)
    assert claimed.snapshot.contacts == contacts and claimed.snapshot.article_outcomes == ()
    assert results.process(claimed)
    lifecycle = Lifecycle(results.database, results.token, SETTINGS)
    lifecycle.stage(org, DeletionRequest(job_id=child, reason="privacy_request"))
    with pytest.raises(AuthorizationDenied):
        results.download(org, state.id)
    assert results.contacts(org, Filters(job_id=original)).items


@pytest.mark.parametrize("stage", ["preview_create", "claim_finish", "ready_download"])
@pytest.mark.parametrize("change", ["deletion", "retention", "suppression"])
def test_actual_filter_export_current_authority_races(
    scenario: Scenario, stage: str, change: str
) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    item = results.outcomes(org, job).items[0]
    request = options(job, item_id=str(item.item_id), article_outcome_presence="observed_candidate")
    assert results.preview(org, request).contacts > 0
    state = None
    claimed = None
    if stage != "preview_create":
        state = results.create(org, request, str(uuid4()))
        claimed = lease(results, org, state.id)
        if stage == "ready_download":
            assert results.process(claimed)
    lifecycle = Lifecycle(results.database, results.token, SETTINGS)
    if change == "deletion":
        lifecycle.stage(org, DeletionRequest(job_id=job, reason="privacy_request"))
    elif change == "retention":
        before = lifecycle.retention(org)
        lifecycle.update_retention(
            org,
            RetentionUpdate(expected_revision=before.revision, retention=Retention(contact_days=0)),
        )
    else:
        address = results.contacts(org, Filters(job_id=job)).items[0].raw_address
        lifecycle.suppress(
            org, SuppressionCreate(kind="contact", value=address, reason="privacy_request")
        )
    if stage == "preview_create":
        if change == "suppression":
            # Suppression fences the selected job, rather than exposing an empty preview.
            with pytest.raises(AuthorizationDenied):
                results.preview(org, request)
        with pytest.raises(AuthorizationDenied):
            results.create(org, request, str(uuid4()))
    elif stage == "claim_finish":
        assert claimed is not None
        assert not results.process(claimed)
    else:
        assert state is not None
        with pytest.raises(AuthorizationDenied):
            results.download(org, state.id)


@contextmanager
def changed_row(
    s: Scenario, table: str, row: Mapping[str, object], changes: Mapping[str, object]
) -> Iterator[None]:
    """Synthetic corruption probe; restore exact owned rows, never alter source allowlists."""
    admin = create_engine(s.admin_url)
    where = " AND ".join(f"{key}=:{key}" for key in row)
    try:
        with admin.begin() as c:
            previous = dict(
                c.execute(text(f"SELECT * FROM emailmonitor.{table} WHERE {where}"), row)
                .mappings()
                .one()
            )
            c.execute(text("SET LOCAL session_replication_role=replica"))
            c.execute(
                text(
                    f"UPDATE emailmonitor.{table} SET "
                    + ",".join(
                        f"{key}=CAST(:new_{key} AS jsonb)"
                        if isinstance(value, (dict, list))
                        else f"{key}=:new_{key}"
                        for key, value in changes.items()
                    )
                    + f" WHERE {where}"
                ),
                {
                    **row,
                    **{
                        "new_" + key: json.dumps(value)
                        if isinstance(value, (dict, list))
                        else value
                        for key, value in changes.items()
                    },
                },
            )
        yield
    finally:
        with admin.begin() as c:
            c.execute(text("SET LOCAL session_replication_role=replica"))
            c.execute(
                text(
                    f"UPDATE emailmonitor.{table} SET "
                    + ",".join(
                        f"{key}=CAST(:old_{key} AS jsonb)"
                        if isinstance(previous[key], (dict, list))
                        else f"{key}=:old_{key}"
                        for key in changes
                    )
                    + f" WHERE {where}"
                ),
                {
                    **row,
                    **{
                        "old_" + key: json.dumps(previous[key])
                        if isinstance(previous[key], (dict, list))
                        else previous[key]
                        for key in changes
                    },
                },
            )
        admin.dispose()


def test_actual_missing_unsealed_expired_and_mismatched_binding_is_unresolved(
    scenario: Scenario,
) -> None:
    from datetime import UTC, datetime

    results, job = prepared(scenario)
    org = scenario.organizations[0]
    item = results.outcomes(org, job).items[0]
    assert item.batch_id is not None
    predicates = {"organization_id": org, "id": item.batch_id}
    changes: list[dict[str, object]] = [
        {"sealed": False},
        {"expires_at": datetime(2000, 1, 1, tzinfo=UTC)},
        {"source_revision": 999},
        {"generation": 999},
        {"policy_version": 999},
        {"deletion_generation": 999},
        {"article_url": "https://synthetic.publisher.example/no-contact.html"},
    ]
    for change in changes:
        with changed_row(scenario, "association_batches", predicates, change):
            assert (
                results.outcomes(org, job, article_outcome_presence="observed_candidate").items
                == ()
            )
            assert (
                results.outcomes(
                    org, job, article_outcome_presence="completed_without_candidate"
                ).items
                == ()
            )
            assert len(results.outcomes(org, job, article_outcome_presence="unresolved").items) == 1
            assert results.contacts(org, Filters(job_id=job, item_id=item.item_id)).items == ()
    with changed_row(
        scenario,
        "execution_items",
        {"organization_id": org, "job_id": job, "id": item.item_id},
        {"batch_id": None},
    ):
        assert len(results.outcomes(org, job, article_outcome_presence="unresolved").items) == 1
    progress = Progress(results.database, results.token, SETTINGS)
    other = additional_job(progress, org, item.source_url)
    batch = results.outcomes(org, other).items[0].batch_id
    with changed_row(
        scenario,
        "execution_items",
        {"organization_id": org, "job_id": job, "id": item.item_id},
        {"batch_id": batch},
    ):
        assert results.outcomes(org, job, article_outcome_presence="observed_candidate").items == ()
        assert results.contacts(org, Filters(job_id=job, item_id=item.item_id)).items == ()


@pytest.mark.parametrize(
    "status,has_candidates,presence",
    [
        ("observed", True, "observed_candidate"),
        ("partial", True, "observed_candidate"),
        ("partial", False, "unresolved"),
        ("unsupported", False, "unresolved"),
        ("no_contact", False, "completed_without_candidate"),
    ],
)
def test_actual_bound_xml_presence_independent_of_execution(
    scenario: Scenario, status: str, has_candidates: bool, presence: ArticleOutcomePresence
) -> None:
    """Supplied valid retained facts test SQL semantics, not actual parser/container output."""
    from emailmonitor.extraction.sciencedirect import parse_article
    from emailmonitor.extraction.xml_retained import XML_IDENTIFIER, RetainedXml, retain_xml
    from emailmonitor.extraction.xml_service import XmlExtraction, fixture_bytes
    from emailmonitor.progress.binding import bound
    from test_xml_pipeline_tenant import planned_xml

    progress, job = planned_xml(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)
    xml = XmlExtraction(progress.database, progress.token, SETTINGS)
    with bound(work.lease):
        binding, excerpts = xml.binding(org, job, work.discovery_revision)
        value = retain_xml(parse_article(fixture_bytes(), XML_IDENTIFIER), binding, excerpts)
        document = value.model_dump(mode="json")
        document["status"] = status
        document["reasons"] = (
            ["unsupported_affiliation"] if status in {"partial", "unsupported"} else []
        )
        if not has_candidates:
            document["candidates"] = []
        if status == "unsupported":
            document["authors"] = []
            document["excerpts_retained"] = False
        xml.commit_xml(org, job, RetainedXml.model_validate_json(json.dumps(document)))
        progress.process_fixture(work)  # Recovery consumes the retained observation, never parses.
    results = Results(progress.database, progress.token, SETTINGS)
    item = results.outcomes(org, job).items[0]
    if status == "partial":
        assert item.state == "unsupported" and item.reason == "xml_partial"
    assert results.outcomes(org, job, article_outcome_presence=presence).items == (item,)
    for excluded in set(PRESENCES) - {presence}:
        assert results.outcomes(org, job, article_outcome_presence=excluded).items == ()
    request = options(job, item_id=str(item.item_id), article_outcome_presence=presence)
    assert results.preview(org, request).article_outcomes == 1
    export = results.create(org, request, str(uuid4()))
    claimed = lease(results, org, export.id)
    assert results.process(claimed)
    assert results.download(org, export.id).body
    if status == "observed":
        for field in (
            "organization",
            "job",
            "item",
            "generation",
            "policy_version",
            "deletion_generation",
            "discovery_revision",
        ):
            broken = {
                **document,
                "binding": {
                    **document["binding"],
                    field: str(uuid4()) if field in {"organization", "job", "item"} else 999,
                },
            }
            with changed_row(
                scenario,
                "article_observations",
                {"organization_id": org, "job_id": job, "article_url": item.source_url},
                {"observation": broken},
            ):
                assert (
                    results.outcomes(org, job, article_outcome_presence="observed_candidate").items
                    == ()
                )
                assert (
                    len(results.outcomes(org, job, article_outcome_presence="unresolved").items)
                    == 1
                )
                with pytest.raises(AuthorizationDenied):
                    results.download(org, export.id)


def test_actual_sql_presence_null_and_inconsistent_profiles_fail_closed(scenario: Scenario) -> None:
    admin = create_engine(scenario.admin_url)
    try:
        with admin.connect() as c:
            cases: tuple[tuple[str, list[dict[str, object]], str], ...] = (
                ("observed", [{}], "observed_candidate"),
                ("no_contact", [], "completed_without_candidate"),
            )
            for status, candidates, expected in cases:
                valid = {
                    "route": "html",
                    "parser_version": "synthetic-html-v1",
                    "status": status,
                    "authors": [{}],
                    "candidates": candidates,
                }

                def classify(document: Mapping[str, object], count: int = len(candidates)) -> str:
                    return str(
                        c.execute(
                            text(
                                "SELECT emailmonitor.retained_observation_presence("
                                "CAST(:doc AS jsonb),:count)"
                            ),
                            {"doc": json.dumps(document), "count": count},
                        ).scalar_one()
                    )

                assert classify(valid) == expected
                for key in ("route", "parser_version", "status", "authors", "candidates"):
                    assert classify({**valid, key: None}) == "unresolved"
                    assert (
                        classify({name: value for name, value in valid.items() if name != key})
                        == "unresolved"
                    )
                assert (
                    classify(
                        {
                            **valid,
                            "route": "article_xml",
                            "parser_version": "elsevier-xml-head-v1",
                            "reasons": None,
                        }
                    )
                    == "unresolved"
                )
                assert classify({**valid, "route": "unknown"}) == "unresolved"
                assert classify(valid, 0 if candidates else 1) == "unresolved"
                assert classify({**valid, "status": "requires_browser"}) == "unresolved"
                assert classify({**valid, "authors": []}) == "unresolved"
    finally:
        admin.dispose()


@pytest.mark.parametrize("presence", ["observed_candidate", "completed_without_candidate"])
def test_actual_ready_artifact_loses_its_source_classification(
    scenario: Scenario, presence: ArticleOutcomePresence
) -> None:
    from datetime import UTC, datetime

    _, results, job = complete_search(scenario)
    org = scenario.organizations[0]
    item = results.outcomes(org, job, article_outcome_presence=presence).items[0]
    request = options(job, item_id=str(item.item_id), article_outcome_presence=presence)
    state = results.create(org, request, str(uuid4()))
    assert results.process(lease(results, org, state.id))
    assert results.download(org, state.id).body
    for changes in ({"expires_at": datetime(2000, 1, 1, tzinfo=UTC)}, {"revision": 999}):
        with changed_row(
            scenario,
            "article_observations",
            {"organization_id": org, "job_id": job, "article_url": item.source_url},
            changes,
        ):
            assert (
                results.outcomes(
                    org, job, item_id=item.item_id, article_outcome_presence=presence
                ).items
                == ()
            )
            assert (
                len(
                    results.outcomes(
                        org, job, item_id=item.item_id, article_outcome_presence="unresolved"
                    ).items
                )
                == 1
            )
            with pytest.raises(AuthorizationDenied):
                results.download(org, state.id)

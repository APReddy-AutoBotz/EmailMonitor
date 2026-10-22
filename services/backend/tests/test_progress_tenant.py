"""Actual disposable PostgreSQL lifecycle, replay and current-permission acceptance."""

from uuid import UUID, uuid4

import pytest
from emailmonitor.discovery.service import Discovery
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import bound
from emailmonitor.progress.service import Progress, Work
from sqlalchemy import create_engine, text
from test_durable_jobs import SETTINGS
from test_html_extraction_tenant import approved, begin, ready
from test_job_contracts import request_body
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario

TABLES = (
    "execution_runs",
    "execution_items",
    "execution_outbox",
    "execution_events",
    "execution_effects",
)


def planned(s: Scenario, url: str | None = None, cap: int = 500) -> tuple[Progress, UUID]:
    if url is None:
        discovery, job = begin(s, articles=cap)
    else:
        ledger = approved(s)
        body = request_body()
        body["input"] = {"type": "url", "url": url}
        job = ledger.create(s.organizations[0], JobRequest.model_validate(body), str(uuid4()))
        discovery = Discovery(ledger.database, ledger.token, SETTINGS)
        discovery.plan(s.organizations[0], job, 1)
    return Progress(discovery.database, discovery.token, SETTINGS), job


def claim(progress: Progress, org: UUID, job: UUID, *, kind: str | None = None) -> Work:
    rows = [row for row in progress.pending(org) if row["job_id"] == job]
    for row in rows:
        work = progress.claim(org, job, UUID(str(row["item_id"])), UUID(str(row["event_id"])))
        if work is None:
            continue
        if kind is not None and work.kind != kind:
            progress.finish(work, failure="worker_failure")
            continue
        return work
    raise AssertionError("Expected eligible durable work")


def drain(progress: Progress, org: UUID, job: UUID) -> None:
    for _ in range(20):
        if progress.snapshot(org, job).state in {"completed", "completed_partial", "failed"}:
            return
        progress.process_fixture(claim(progress, org, job))
    raise AssertionError("Bounded fixture job failed to settle")


def test_real_unknown_total_actual_counters_partial_dynamic_and_replay(scenario: Scenario) -> None:
    progress, job = planned(scenario)
    org = scenario.organizations[0]
    initial = progress.snapshot(org, job)
    assert initial.state == "draft" and initial.progress_percent is None
    queued = progress.start(org, job, initial.revision)
    assert queued.state == "queued" and queued.last_sequence == 1
    work = claim(progress, org, job)
    assert work.kind == "discover" and progress.snapshot(org, job).state == "running"
    progress.process_fixture(work)
    first = progress.snapshot(org, job)
    assert first.unique_articles == 2 and first.progress_percent is None
    restored = Progress(progress.database, progress.token, SETTINGS)
    drain(restored, org, job)
    final = restored.snapshot(org, job)
    assert final.state == "completed_partial" and final.discovery_complete
    assert final.counts.discovered == final.counts.terminal == 4
    assert final.counts.by_outcome["unsupported"] == 1
    assert final.counts.by_outcome["no_contact"] == 1
    rows = restored.events(org, job, 0)
    assert rows[-1].event_type == "job.finished"
    assert [e.sequence for e in rows] == list(range(1, len(rows) + 1))
    assert restored.events(org, job, rows[-1].sequence) == []
    with pytest.raises(ValueError):
        restored.events(org, job, rows[-1].sequence + 1)
    with restored.database.tenant(restored.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.execution_effects "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            == 4
        )


def test_real_all_no_contact_completes_without_accepted_contacts(scenario: Scenario) -> None:
    progress, job = planned(scenario, "https://synthetic.publisher.example/no-contact.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    drain(progress, org, job)
    result = progress.snapshot(org, job)
    assert result.state == "completed" and result.counts.by_outcome == {"no_contact": 1}
    assert result.accepted_associations == 0 and result.progress_percent == 100


def test_real_cap_partial_never_claims_known_denominator(scenario: Scenario) -> None:
    progress, job = planned(scenario, cap=1)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    drain(progress, org, job)
    result = progress.snapshot(org, job)
    assert result.state == "completed_partial" and not result.discovery_complete
    assert result.discovery_stop_reason == "article_cap" and result.progress_percent is None


def test_real_pause_generation_resume_checkpoint_old_lease_denied(scenario: Scenario) -> None:
    progress, job = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    old = claim(progress, org, job)
    progress.control(org, job, progress.snapshot(org, job).revision, "pause")
    paused = progress.snapshot(org, job)
    assert paused.state == "paused" and paused.generation == 2
    with pytest.raises(AuthorizationDenied):
        progress.process_fixture(old)
    progress.control(org, job, paused.revision, "resume")
    restored = claim(progress, org, job)
    assert restored.lease.generation == 2
    progress.process_fixture(restored)
    assert progress.snapshot(org, job).state == "completed"


def test_real_cancel_retains_permitted_source_but_fences_uncommitted_effect(
    scenario: Scenario,
) -> None:
    progress, job = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)
    with bound(work.lease):
        progress.extraction.fixture(org, job, work.url, work.discovery_revision)
    progress.control(org, job, progress.snapshot(org, job).revision, "cancel")
    assert progress.snapshot(org, job).state == "cancelled"
    assert len(progress.extraction.read(org, job)) == 1
    with pytest.raises(AuthorizationDenied):
        progress.finish(work)


def test_real_exhausted_last_attempt_pause_settles_and_retry_is_new_lineage(
    scenario: Scenario,
) -> None:
    progress, job = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    for _ in range(2):
        assert progress.finish(claim(progress, org, job), failure="worker_failure") == "retry_wait"
    final_lease = claim(progress, org, job)
    progress.control(org, job, progress.snapshot(org, job).revision, "pause")
    progress.control(org, job, progress.snapshot(org, job).revision, "resume")
    original = progress.snapshot(org, job)
    assert original.state == "completed_partial" and original.counts.by_outcome == {"failed": 1}
    with pytest.raises(AuthorizationDenied):
        progress.finish(final_lease)
    continuation = progress.retry(org, job, original.revision)
    assert continuation != job and progress.snapshot(org, job) == original
    assert progress.retry(org, job, original.revision) == continuation
    drain(progress, org, continuation)
    assert progress.snapshot(org, continuation).state == "completed"
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        lineage = c.execute(
            text(
                "SELECT root_job_id,retry_from FROM emailmonitor.execution_runs "
                "WHERE organization_id=:org AND job_id=:job"
            ),
            {"org": org, "job": continuation},
        ).one()
        assert tuple(lineage) == (job, job)


def test_real_started_writes_need_current_lease_and_runtime_tables_are_read_only(
    scenario: Scenario,
) -> None:
    extraction, job = ready(scenario)
    progress = Progress(extraction.database, extraction.token, SETTINGS)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    with pytest.raises(AuthorizationDenied):
        extraction.fixture(org, job, "https://synthetic.publisher.example/article-a.html", 3)
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        for table in TABLES:
            for operation in ("INSERT", "UPDATE", "DELETE"):
                assert not c.execute(
                    text("SELECT has_table_privilege(current_user,:table,:op)"),
                    {"table": "emailmonitor." + table, "op": operation},
                ).scalar_one()
        assert not c.execute(
            text("SELECT has_table_privilege(current_user,'emailmonitor.source_catalog','UPDATE')")
        ).scalar_one()


def test_real_revision_conflict_does_not_start_or_reopen_terminal(scenario: Scenario) -> None:
    progress, job = planned(scenario, "https://synthetic.publisher.example/no-contact.html")
    org = scenario.organizations[0]
    with pytest.raises(RevisionConflict):
        progress.start(org, job, 999)
    assert progress.snapshot(org, job).state == "draft"
    progress.start(org, job, progress.snapshot(org, job).revision)
    drain(progress, org, job)
    with pytest.raises(AuthorizationDenied):
        progress.retry(org, job, progress.snapshot(org, job).revision)


@pytest.mark.parametrize("reason", ["policy", "membership", "deletion"])
def test_real_current_authorization_closes_replay_and_all_progress_tables(
    scenario: Scenario, reason: str
) -> None:
    from emailmonitor.identity.foundation import COOKIE
    from test_source_foundation import source_path
    from test_tenant_foundation import ORIGIN

    progress, job = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    with scenario.client() as client:
        if reason == "membership":
            scenario.login(client, "viewer")
            read = Progress(progress.database, str(client.cookies[COOKIE]), SETTINGS)
            assert read.events(org, job, 0)
        else:
            read = progress
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        if reason == "policy":
            response = client.post(
                source_path(scenario) + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
            )
        elif reason == "membership":
            response = client.patch(
                f"/api/v1/organizations/{org}/members/{scenario.identities['viewer']}",
                headers=headers,
                json={"expected_revision": 1, "role": "viewer", "status": "revoked"},
            )
        else:
            response = client.post(
                f"/api/v1/organizations/{org}/lifecycle",
                headers=headers,
                json={"expected_revision": 1, "status": "offboarding"},
            )
        assert response.status_code == 200, response.text
    with pytest.raises(AuthorizationDenied):
        read.events(org, job, 0)
    with pytest.raises(AuthorizationDenied):
        read.snapshot(org, job)
    if reason == "policy":
        # Metadata reconciliation records a gap without acquiring any further source bytes.
        progress.reconcile(org, job)
        with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
            for table in TABLES:
                assert (
                    c.execute(
                        text(
                            f"SELECT count(*) FROM emailmonitor.{table} "
                            "WHERE organization_id=:org AND job_id=:job"
                        ),
                        {"org": org, "job": job},
                    ).scalar_one()
                    == 0
                )


def test_real_mixed_exhausted_and_running_job_does_not_terminalize_live_work(
    scenario: Scenario,
) -> None:
    extraction, job = ready(scenario)
    progress = Progress(extraction.database, extraction.token, SETTINGS)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    live = claim(progress, org, job)
    for attempt in range(3):
        failed = claim(progress, org, job)
        # Select the same second item again on retry while the first lease remains active.
        outcome = progress.finish(failed, failure="worker_failure")
        assert outcome == ("retry_wait" if attempt < 2 else "failed")
    assert progress.snapshot(org, job).state == "running"
    progress.process_fixture(live)
    drain(progress, org, job)
    assert progress.snapshot(org, job).state == "completed_partial"


def test_real_atomic_review_event_is_metadata_only_and_replayed_after_completion(
    scenario: Scenario,
) -> None:
    from test_association_tenant import review_request

    progress, job = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    drain(progress, org, job)
    previous = progress.snapshot(org, job)
    batch = UUID(str(progress.associations.batches(org, job)[0]["id"]))
    progress.associations.review(
        org, batch, review_request(progress.associations, org, batch, action="reject")
    )
    events = progress.events(org, job, previous.last_sequence)
    assert len(events) == 1 and events[0].event_type == "association.reviewed"
    assert events[0].batch_id == batch and events[0].aggregate_version == 2
    assert "example.org" not in events[0].model_dump_json()
    after = progress.snapshot(org, job)
    assert (
        after.state == "completed" and after.accepted_associations < previous.accepted_associations
    )


def test_real_page_committed_before_effect_pause_resumes_without_refetch(
    scenario: Scenario,
) -> None:
    from emailmonitor.discovery.fixture import step_fixture

    progress, job = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    original = claim(progress, org, job)
    with bound(original.lease):
        page = step_fixture(progress.discovery, org, job, original.discovery_revision)
    progress.control(org, job, progress.snapshot(org, job).revision, "pause")
    progress.control(org, job, progress.snapshot(org, job).revision, "resume")
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        retry_event: UUID = c.execute(
            text(
                "SELECT event_id FROM emailmonitor.execution_outbox "
                "WHERE organization_id=:org AND job_id=:job "
                "AND item_id=:item AND generation=2"
            ),
            {"org": org, "job": job, "item": original.lease.item},
        ).scalar_one()
    resumed = progress.claim(org, job, original.lease.item, retry_event)
    assert resumed is not None
    progress.process_fixture(resumed)
    assert progress.discovery.read(org, job)["checkpoint"] == page["checkpoint"]
    drain(progress, org, job)
    assert progress.snapshot(org, job).discovery_pages == 2


def test_real_catalog_guard_preserves_live_work_and_item_scope(scenario: Scenario) -> None:
    from sqlalchemy.exc import DBAPIError

    extraction, job = ready(scenario)
    progress = Progress(extraction.database, extraction.token, SETTINGS)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    live = claim(progress, org, job)
    with pytest.raises(DBAPIError):
        with progress.database.tenant(progress.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
            c.execute(
                text(
                    "UPDATE emailmonitor.jobs SET state='completed' "
                    "WHERE organization_id=:org AND id=:job"
                ),
                {"org": org, "job": job},
            )
    alternate = "https://synthetic.publisher.example/article-a.html"
    if live.url == alternate:
        alternate = "https://synthetic.publisher.example/no-contact.html"
    with bound(live.lease), pytest.raises(AuthorizationDenied):
        extraction.fixture(org, job, alternate, live.discovery_revision)
    assert progress.snapshot(org, job).state == "running"


def test_real_identifier_api_csrf_and_authorized_sse_replay(scenario: Scenario) -> None:
    from api_client import APIClient
    from emailmonitor.api import create_app
    from emailmonitor.identity.foundation import COOKIE
    from test_tenant_foundation import ORIGIN

    progress, job = planned(scenario, "https://synthetic.publisher.example/no-contact.html")
    org = scenario.organizations[0]
    with APIClient(
        create_app(SETTINGS.model_copy(update={"identity_stub": True}), scenario.foundation),
        base_url=ORIGIN,
    ) as client:
        csrf = scenario.login(client, "owner")
        route = f"/api/v1/organizations/{org}/jobs/{job}"
        revision = progress.snapshot(org, job).revision
        assert (
            client.post(route + "/start", json={"expected_revision": revision}).status_code == 403
        )
        response = client.post(
            route + "/start",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"expected_revision": revision},
        )
        assert response.status_code == 200, response.text
        execution = Progress(progress.database, str(client.cookies[COOKIE]), SETTINGS)
        drain(execution, org, job)
        result = client.get(route + "/progress")
        assert result.status_code == 200 and result.json()["state"] == "completed"
        items = client.get(route + "/progress/items")
        assert items.status_code == 200 and items.json()[0]["state"] == "no_contact"
        assert "lease_token" not in items.text and "input_url" not in items.text
        stream = client.get(route + "/events")
        assert stream.status_code == 200 and "event: job.finished" in stream.text
        assert "text/event-stream" in stream.headers["content-type"]
        assert stream.headers["cache-control"] == "no-store"
        cross = client.get(route + "/events", headers={"Last-Event-ID": f"{uuid4()}/{job}:1"})
        assert cross.status_code == 409
        scenario.login(client, "owner_b")
        denied = client.get(route + "/events")
        unknown = client.get(f"/api/v1/organizations/{org}/jobs/{uuid4()}/events")
        assert denied.status_code == unknown.status_code == 404
        assert denied.json() == unknown.json() == {"detail": "Resource unavailable"}
        assert "text/event-stream" not in denied.headers["content-type"]
        assert "data:" not in denied.text


def test_real_stream_rechecks_source_before_each_cached_frame(scenario: Scenario) -> None:
    import asyncio

    from emailmonitor.progress.models import Event, Snapshot
    from emailmonitor.progress.stream import replay
    from test_source_foundation import source_path
    from test_tenant_foundation import ORIGIN

    progress, job = planned(scenario, "https://synthetic.publisher.example/no-contact.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    drain(progress, org, job)

    class RevokingReader:
        checks = 0

        def events(self, organization: UUID, identifier: UUID, after: int) -> list[Event]:
            return progress.events(organization, identifier, after)

        def snapshot(self, organization: UUID, identifier: UUID) -> Snapshot:
            return progress.snapshot(organization, identifier)

        def authorize(self, organization: UUID, identifier: UUID) -> None:
            self.checks += 1
            if self.checks == 2:
                with scenario.client() as client:
                    csrf = scenario.login(client, "owner")
                    response = client.post(
                        source_path(scenario) + "/policy-state",
                        headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
                        json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
                    )
                    assert response.status_code == 200, response.text
            progress.authorize(organization, identifier)

    async def collect() -> list[str]:
        return [frame async for frame in replay(RevokingReader(), org, job, 0)]

    frames = asyncio.run(collect())
    assert len(frames) == 1 and "event: job.queued" in frames[0]


def test_real_failed_pagination_retry_inherits_committed_articles_without_new_effects(
    scenario: Scenario,
) -> None:
    progress, job = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    first_page = claim(progress, org, job)
    progress.process_fixture(first_page)
    # Commit every currently discovered article before exhausting the next page.
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        article_items: list[UUID] = list(
            c.execute(
                text(
                    "SELECT id FROM emailmonitor.execution_items WHERE organization_id=:org "
                    "AND job_id=:job AND work_kind='article' ORDER BY id"
                ),
                {"org": org, "job": job},
            ).scalars()
        )
    for identifier in article_items:
        message = next(row for row in progress.pending(org) if row["item_id"] == identifier)
        work = progress.claim(org, job, identifier, UUID(str(message["event_id"])))
        assert work is not None
        progress.process_fixture(work)
    for _ in range(3):
        page_work = claim(progress, org, job)
        assert page_work.kind == "discover"
        progress.finish(page_work, failure="worker_failure")
    original = progress.snapshot(org, job)
    assert original.state == "completed_partial" and original.counts.terminal == 2
    continuation = progress.retry(org, job, original.revision)
    inherited = progress.items(org, continuation)
    assert sum(item.inherited_job_id == job for item in inherited) == 2
    from emailmonitor.results.service import Results

    outcomes = Results(progress.database, progress.token, SETTINGS).outcomes(
        org, continuation, limit=25
    )
    retained = [item for item in outcomes.items if item.inherited_job_id == job]
    assert len(retained) == 2 and all(item.batch_id is not None for item in retained)
    for item in retained:
        assert item.batch_id is not None
        assert progress.associations.quality(org, item.batch_id).scope == "article"
    assert (
        progress.snapshot(org, continuation).accepted_associations == original.accepted_associations
    )
    from test_association_tenant import review_request

    inherited_batch = next(item.batch_id for item in inherited if item.batch_id is not None)
    prior_quality = progress.snapshot(org, job).accepted_associations
    predecessor_cursor = progress.snapshot(org, job).last_sequence
    continuation_cursor = progress.snapshot(org, continuation).last_sequence
    progress.associations.review(
        org,
        inherited_batch,
        review_request(progress.associations, org, inherited_batch, action="reject"),
    )
    predecessor_events = progress.events(org, job, predecessor_cursor)
    continuation_events = progress.events(org, continuation, continuation_cursor)
    assert len(predecessor_events) == len(continuation_events) == 1
    assert predecessor_events[0].event_type == "association.reviewed"
    assert continuation_events[0].event_type == "association.reviewed"
    assert predecessor_events[0].event_id == continuation_events[0].event_id
    assert predecessor_events[0].batch_id == continuation_events[0].batch_id == inherited_batch
    original = progress.snapshot(org, job)
    assert original.accepted_associations < prior_quality
    assert (
        progress.snapshot(org, continuation).accepted_associations == original.accepted_associations
    )
    drain(progress, org, continuation)
    final = progress.snapshot(org, continuation)
    assert final.counts.terminal == 4 and final.state == "completed_partial"
    assert progress.snapshot(org, job) == original
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.execution_effects "
                    "WHERE organization_id=:org AND root_job_id=:job"
                ),
                {"org": org, "job": job},
            ).scalar_one()
            == 4
        )
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.article_observations "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": continuation},
            ).scalar_one()
            == 2
        )


def test_real_review_rejection_does_not_turn_processing_into_failure(scenario: Scenario) -> None:
    from test_association_tenant import review_request

    progress, job = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)
    with bound(work.lease):
        observation = progress.extraction.fixture(org, job, work.url, work.discovery_revision)
        batch = progress.associations.derive(org, job, work.url, int(str(observation["revision"])))
        progress.associations.review(
            org, batch, review_request(progress.associations, org, batch, action="reject")
        )
        assert progress.finish(work, batch) == "succeeded"
    result = progress.snapshot(org, job)
    assert result.state == "completed" and result.counts.by_outcome == {"succeeded": 1}
    assert result.accepted_associations == 0


def test_real_source_ceiling_is_partial_and_not_a_false_percentage(scenario: Scenario) -> None:
    from emailmonitor.identity.foundation import COOKIE
    from emailmonitor.jobs.ledger import Ledger
    from test_html_extraction_tenant import extraction_policy
    from test_source_foundation import source_path
    from test_tenant_foundation import ORIGIN

    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        proposal = extraction_policy()
        proposal["limits"] = {
            "max_concurrent_requests": 1,
            "min_request_interval_seconds": 5,
            "max_articles_per_job": 1,
        }
        assert (
            client.post(
                source_path(scenario) + "/policies",
                headers=headers,
                json={"expected_version": 0, "policy": proposal},
            ).status_code
            == 201
        )
        assert (
            client.post(
                source_path(scenario) + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 200
        )
        ledger = Ledger(scenario.foundation.database, str(client.cookies[COOKIE]), SETTINGS)
    body = request_body()
    body["input"] = {
        "type": "keyword",
        "source_id": "synthetic-publisher",
        "original_query": "Myocardial Infarction",
    }
    body["options"] = {"max_articles": 500, "max_search_pages": 100, "author_target": "both"}
    org = scenario.organizations[0]
    job = ledger.create(org, JobRequest.model_validate(body), str(uuid4()))
    progress = Progress(ledger.database, ledger.token, SETTINGS)
    progress.discovery.plan(org, job, 1)
    progress.start(org, job, progress.snapshot(org, job).revision)
    drain(progress, org, job)
    result = progress.snapshot(org, job)
    assert result.state == "completed_partial" and result.discovery_stop_reason == "source_cap"
    assert result.progress_percent is None and result.counts.discovered == 1


def test_real_reconciliation_reopens_confirmed_unleased_pending_only(scenario: Scenario) -> None:
    progress, job = planned(scenario, "https://synthetic.publisher.example/no-contact.html")
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    message = progress.pending(org)[0]
    event_id = UUID(str(message["event_id"]))
    progress.confirmed(org, job, event_id)
    assert progress.pending(org) == []
    progress.reconcile(org, job)
    assert progress.pending(org)[0]["event_id"] == event_id
    work = progress.claim(org, job, UUID(str(message["item_id"])), event_id)
    assert work is not None
    progress.confirmed(org, job, event_id)
    progress.reconcile(org, job)
    assert progress.pending(org) == []
    progress.process_fixture(work)
    before = progress.snapshot(org, job)
    progress.reconcile(org, job)
    assert progress.pending(org) == [] and progress.snapshot(org, job) == before


def test_real_cancel_after_page_checkpoint_terminalizes_frontier_and_reconcile_is_inert(
    scenario: Scenario,
) -> None:
    from emailmonitor.discovery.fixture import step_fixture
    from test_source_foundation import source_path
    from test_tenant_foundation import ORIGIN

    progress, job = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    work = claim(progress, org, job)
    assert work.kind == "discover"
    with bound(work.lease):
        page = step_fixture(progress.discovery, org, job, work.discovery_revision)
    checkpoint = page["checkpoint"]
    assert isinstance(checkpoint, dict)
    articles = checkpoint["articles"]
    assert isinstance(articles, list)
    count = len(articles)
    assert count == 2
    progress.control(org, job, progress.snapshot(org, job).revision, "cancel")
    snapshot = progress.snapshot(org, job)
    assert snapshot.state == "cancelled"
    assert snapshot.unique_articles == count
    assert snapshot.counts.by_outcome["cancelled"] == snapshot.counts.terminal == count
    assert snapshot.counts.pending == snapshot.counts.active == snapshot.counts.retry_wait == 0
    items = progress.items(org, job)
    assert all(item.state == "cancelled" for item in items)
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (c, _):
        before = {
            table: c.execute(
                text(
                    f"SELECT * FROM emailmonitor.{table} "
                    "WHERE organization_id=:org AND job_id=:job ORDER BY 1,2,3"
                ),
                {"org": org, "job": job},
            ).all()
            for table in TABLES
        }
    assert before["execution_effects"] == []
    progress.reconcile(org, job)
    assert progress.snapshot(org, job) == snapshot
    with scenario.client() as client:
        csrf = scenario.login(client, "owner")
        response = client.post(
            source_path(scenario) + "/policy-state",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
            json={"expected_version": 1, "expected_revision": 2, "state": "revoked"},
        )
        assert response.status_code == 200, response.text
    progress.reconcile(org, job)
    # Current-policy RLS hides the terminal rows; the owner test connection verifies
    # no reconciliation mutation after revocation, without changing runtime grants.
    admin = create_engine(scenario.admin_url)
    try:
        with admin.begin() as c:
            after = {
                table: c.execute(
                    text(
                        f"SELECT * FROM emailmonitor.{table} "
                        "WHERE organization_id=:org AND job_id=:job ORDER BY 1,2,3"
                    ),
                    {"org": org, "job": job},
                ).all()
                for table in TABLES
            }
    finally:
        admin.dispose()
    assert after == before

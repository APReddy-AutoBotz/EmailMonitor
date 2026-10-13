"""Real shared PostgreSQL admission/settlement regressions, never local mock acceptance."""

import time
from uuid import UUID, uuid4

import pytest
from emailmonitor.administration.models import ConfigurationUpdate
from emailmonitor.administration.service import Administration
from emailmonitor.discovery.fixture import step_fixture
from emailmonitor.discovery.service import Discovery
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.service import Progress, Work
from sqlalchemy import text
from test_durable_jobs import SETTINGS
from test_html_extraction_tenant import extraction_policy
from test_job_contracts import request_body
from test_progress_tenant import planned
from test_results_tenant import options, prepared, ready
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario


def configuration(progress: Progress, org: UUID, **limits: object) -> Administration:
    service = Administration(progress.database, progress.token, progress.settings)
    old = service.read(org)
    service.update(
        org,
        ConfigurationUpdate.model_validate(
            {
                "expected_revision": old.revision,
                "entitlements": {**old.entitlements.model_dump(), **limits},
                "branding": old.branding.model_dump(),
            }
        ),
    )
    return service


def new_job(progress: Progress, org: UUID, url: str | None = None) -> UUID:
    request = request_body()
    request["input"] = (
        {"type": "url", "url": url}
        if url
        else {
            "type": "keyword",
            "source_id": "synthetic-publisher",
            "original_query": "Myocardial Infarction",
        }
    )
    job = Ledger(progress.database, progress.token, progress.settings).create(
        org, JobRequest.model_validate(request), str(uuid4())
    )
    Discovery(progress.database, progress.token, progress.settings).plan(org, job, 1)
    return job


def tenant_b(s: Scenario) -> tuple[Progress, UUID]:
    org = s.organizations[1]
    with s.client() as client:
        csrf = s.login(client, "owner_b")
        path = f"/api/v1/organizations/{org}/sources/synthetic-publisher"
        headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
        assert (
            client.post(
                path + "/policies",
                headers=headers,
                json={"expected_version": 0, "policy": extraction_policy()},
            ).status_code
            == 201
        )
        assert (
            client.post(
                path + "/policy-state",
                headers=headers,
                json={"expected_version": 1, "expected_revision": 1, "state": "approved"},
            ).status_code
            == 200
        )
        service = Progress(s.foundation.database, str(client.cookies[COOKIE]), SETTINGS)
    return service, new_job(service, org)


def rows(progress: Progress, org: UUID, job: UUID) -> list[dict[str, object]]:
    return [row for row in progress.pending(org) if row["job_id"] == job]


def try_claim(
    progress: Progress, org: UUID, job: UUID, row: dict[str, object], seconds: int = 30
) -> Work | None:
    return progress.claim(org, job, UUID(str(row["item_id"])), UUID(str(row["event_id"])), seconds)


def run_until_terminal(progress: Progress, org: UUID, job: UUID) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if progress.snapshot(org, job).state in {
            "completed",
            "completed_partial",
            "failed",
            "cancelled",
        }:
            return
        progress.reconcile(org, job)
        for row in rows(progress, org, job):
            work = try_claim(progress, org, job, row)
            if work is not None:
                progress.process_fixture(work)
        time.sleep(0.05)
    raise AssertionError("Bounded admission failed to settle")


def test_real_running_job_admission_and_one_settlement_each(scenario: Scenario) -> None:
    progress, first = planned(scenario, "https://synthetic.publisher.example/no-contact.html")
    org = scenario.organizations[0]
    jobs = [
        first,
        *[
            new_job(progress, org, "https://synthetic.publisher.example/no-contact.html")
            for _ in range(2)
        ],
    ]
    for job in jobs:
        progress.start(org, job, progress.snapshot(org, job).revision)
    messages = [rows(progress, org, job)[0] for job in jobs]
    a, b = [
        try_claim(progress, org, job, row) for job, row in zip(jobs[:2], messages[:2], strict=True)
    ]
    assert a is not None and b is not None
    assert try_claim(progress, org, jobs[2], messages[2]) is None
    administration = Administration(progress.database, progress.token, progress.settings)
    assert administration.usage(org).active_units["parse"] == 2
    progress.process_fixture(a)
    third = try_claim(progress, org, jobs[2], messages[2])
    assert third is not None
    progress.process_fixture(b)
    progress.process_fixture(third)
    usage = administration.usage(org)
    assert usage.settled_resolution_units == 3 and usage.reserved_resolution_units == 0
    assert usage.source_resource_attempts == 0 and not usage.active_units


def test_real_two_tenant_round_robin_under_shared_pool_contention(scenario: Scenario) -> None:
    a, job_a = planned(scenario)
    b, job_b = tenant_b(scenario)
    org_a, org_b = scenario.organizations
    for service, org, job in ((a, org_a, job_a), (b, org_b, job_b)):
        step_fixture(service.discovery, org, job, 1)
        step_fixture(service.discovery, org, job, 2)
        service.start(org, job, service.snapshot(org, job).revision)
    messages_a, messages_b = rows(a, org_a, job_a), rows(b, org_b, job_b)
    assert len(messages_a) == len(messages_b) == 4
    held_a = [try_claim(a, org_a, job_a, row) for row in messages_a[:2]]
    held_b = [try_claim(b, org_b, job_b, row) for row in messages_b[:2]]
    assert all(work is not None for work in held_a + held_b)
    assert try_claim(a, org_a, job_a, messages_a[2]) is None
    assert try_claim(b, org_b, job_b, messages_b[2]) is None
    assert held_a[0] is not None and held_b[0] is not None
    a.process_fixture(held_a[0])
    b.process_fixture(held_b[0])
    # B admitted last. Its fresh poll cannot bypass A's current waiting ticket.
    assert try_claim(b, org_b, job_b, messages_b[2]) is None
    next_a = try_claim(a, org_a, job_a, messages_a[2])
    assert next_a is not None
    next_b = try_claim(b, org_b, job_b, messages_b[2])
    assert next_b is not None
    for service, work in ((a, held_a[1]), (b, held_b[1]), (a, next_a), (b, next_b)):
        assert work is not None
        service.process_fixture(work)
    run_until_terminal(a, org_a, job_a)
    run_until_terminal(b, org_b, job_b)
    for service, org in ((a, org_a), (b, org_b)):
        usage = Administration(service.database, service.token, service.settings).usage(org)
        assert usage.settled_resolution_units == 4 and usage.reserved_resolution_units == 0


def test_real_quota_reduction_stops_remaining_units_without_recharging(scenario: Scenario) -> None:
    progress, job = planned(scenario)
    org = scenario.organizations[0]
    step_fixture(progress.discovery, org, job, 1)
    step_fixture(progress.discovery, org, job, 2)
    progress.start(org, job, progress.snapshot(org, job).revision)
    first = try_claim(progress, org, job, rows(progress, org, job)[0])
    assert first is not None
    progress.process_fixture(first)
    administration = configuration(progress, org, monthly_resolution_units=1)
    run_until_terminal(progress, org, job)
    state = progress.snapshot(org, job)
    assert state.state == "completed_partial" and state.discovery_stop_reason == "quota_exhausted"
    assert state.counts.terminal == state.counts.discovered == 4
    usage = administration.usage(org)
    assert usage.settled_resolution_units == 1 and usage.reserved_resolution_units == 0
    before = state.model_dump()
    progress.reconcile(org, job)
    assert progress.snapshot(org, job).model_dump() == before
    assert administration.usage(org).settled_resolution_units == 1


def test_real_active_reservation_survives_temporary_full_quota_and_cancel_releases(
    scenario: Scenario,
) -> None:
    progress, job = planned(scenario)
    org = scenario.organizations[0]
    administration = configuration(progress, org, monthly_resolution_units=1)
    progress.start(org, job, progress.snapshot(org, job).revision)
    discovery = try_claim(progress, org, job, rows(progress, org, job)[0])
    assert discovery is not None
    progress.process_fixture(discovery)
    messages = [r for r in rows(progress, org, job) if r["work_kind"] == "article"]
    active = try_claim(progress, org, job, messages[0])
    assert active is not None
    assert try_claim(progress, org, job, messages[1]) is None
    assert progress.snapshot(org, job).state == "running"
    usage = administration.usage(org)
    assert usage.reserved_resolution_units == 1 and usage.settled_resolution_units == 0
    progress.control(org, job, progress.snapshot(org, job).revision, "cancel")
    assert administration.usage(org).reserved_resolution_units == 0
    assert administration.usage(org).settled_resolution_units == 0


def test_real_export_reduction_hides_download_and_keeps_private_artifact(
    scenario: Scenario,
) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = ready(results, org, job)
    progress = Progress(results.database, results.token, results.settings)
    configuration(progress, org, max_export_bytes=1)
    assert not results.state(org, export).download_available
    from emailmonitor.organizations.database import AuthorizationDenied

    with pytest.raises(AuthorizationDenied):
        results.download(org, export)
    with results.database.tenant(results.token, org, Capability.EXPORT_RESULTS) as (connection, _):
        assert not connection.execute(
            text(
                "SELECT has_table_privilege(current_user,'emailmonitor.export_artifacts','SELECT')"
            )
        ).scalar_one()
    configuration(progress, org, max_export_bytes=8388608)
    assert results.state(org, export).download_available
    assert results.download(org, export).body


def test_real_current_export_disable_closes_claim_and_reconciliation(scenario: Scenario) -> None:
    results, job = prepared(scenario)
    org = scenario.organizations[0]
    export = results.create(org, options(job), str(uuid4()))
    progress = Progress(results.database, results.token, results.settings)
    configuration(progress, org, exports_enabled=False)
    results.reconcile(org, export.id)
    assert results.state(org, export.id).state == "failed"
    assert not results.pending(org)


def test_real_source_attempt_spacing_backoff_and_idempotent_admission(scenario: Scenario) -> None:
    from emailmonitor.administration.source import SourceAdmission
    from emailmonitor.fetching.safety import classify_url
    from emailmonitor.sources.policy import Operation

    progress, _ = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    source = SourceAdmission(progress.database, progress.token, progress.settings)
    url = classify_url(
        "https://synthetic.publisher.example/article-a.html",
        frozenset({"synthetic.publisher.example"}),
    )
    first = source.acquire(org, 1, Operation.HTML, url, time.monotonic() + 15)
    with progress.database.tenant(progress.token, org, Capability.ACQUIRE_SOURCE) as (
        connection,
        _,
    ):
        repeated: object = connection.execute(
            text(
                """SELECT emailmonitor.source_resource_claim(
:org,:id,NULL,1,'fetch_html','/article-a.html',:nonce,10)"""
            ),
            {"org": org, "id": first.identifier, "nonce": first.nonce},
        ).scalar_one()
        assert isinstance(repeated, dict) and repeated["admitted"] is True
    administration = Administration(progress.database, progress.token, progress.settings)
    assert administration.usage(org).source_resource_attempts == 1
    source.finish(first, 429, "1")
    before = time.monotonic()
    second = source.acquire(org, 1, Operation.HTML, url, time.monotonic() + 15)
    assert time.monotonic() - before >= 4.9
    source.finish(second)
    usage = administration.usage(org)
    assert usage.source_resource_attempts == 2 and usage.settled_resolution_units == 0
    assert usage.reserved_resolution_units == 0 and not usage.active_units


def test_real_current_network_entitlement_refusal_does_not_count_attempt(
    scenario: Scenario,
) -> None:
    from emailmonitor.administration.source import SourceAdmission
    from emailmonitor.fetching.fixture import TenantFixtureAuthorization
    from emailmonitor.fetching.safety import FetchDenied, classify_url
    from emailmonitor.sources.policy import Operation

    progress, _ = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    administration = configuration(progress, org, max_parallel_parse=0)
    url = classify_url(
        "https://synthetic.publisher.example/article-a.html",
        frozenset({"synthetic.publisher.example"}),
    )
    with pytest.raises(FetchDenied):
        SourceAdmission(progress.database, progress.token, progress.settings).acquire(
            org, 1, Operation.HTML, url, time.monotonic() + 5
        )
    with pytest.raises(FetchDenied):
        TenantFixtureAuthorization(
            progress.database, progress.token, org, "synthetic-publisher", 1
        )(url, Operation.HTML)
    usage = administration.usage(org)
    assert usage.source_resource_attempts == 0 and usage.settled_resolution_units == 0


def test_real_captured_job_limits_do_not_expand_on_upgrade(scenario: Scenario) -> None:
    progress, initial = planned(scenario, "https://synthetic.publisher.example/no-contact.html")
    org = scenario.organizations[0]
    configuration(progress, org, max_articles_per_job=1)
    job = new_job(progress, org)
    configuration(progress, org, max_articles_per_job=500)
    state = progress.discovery.read(org, job)
    assert state["max_articles"] == 1
    step_fixture(progress.discovery, org, job, 1)
    from emailmonitor.discovery.state import DiscoveryState

    assert (
        DiscoveryState.model_validate(progress.discovery.read(org, job)["checkpoint"]).reason
        == "entitlement_cap"
    )
    # Source/security configuration is separate from the administration mutation.
    with progress.database.tenant(progress.token, org, Capability.READ_ORGANIZATION) as (
        connection,
        _,
    ):
        assert connection.execute(
            text("""SELECT policy->'limits'->>'min_request_interval_seconds'
FROM emailmonitor.source_policies WHERE organization_id=:org
AND source_id='synthetic-publisher' AND version=1"""),
            {"org": org},
        ).scalar_one() in {"5", "5.0"}
    assert progress.snapshot(org, initial).state == "draft"


def test_real_concurrent_claims_never_oversubscribe_tenant_or_recharge(scenario: Scenario) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    progress, first = planned(scenario, "https://synthetic.publisher.example/no-contact.html")
    org = scenario.organizations[0]
    jobs = [
        first,
        *[
            new_job(progress, org, "https://synthetic.publisher.example/no-contact.html")
            for _ in range(3)
        ],
    ]
    for job in jobs:
        progress.start(org, job, progress.snapshot(org, job).revision)
    messages = [rows(progress, org, job)[0] for job in jobs]
    barrier = Barrier(len(jobs))

    def claim_at_once(index: int) -> Work | None:
        independent = Progress(progress.database, progress.token, progress.settings)
        barrier.wait(timeout=5)
        return try_claim(independent, org, jobs[index], messages[index])

    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        claimed = list(executor.map(claim_at_once, range(len(jobs))))
    admitted = [work for work in claimed if work is not None]
    assert 1 <= len(admitted) <= 2
    assert len({work.lease.item for work in admitted}) == len(admitted)
    admin = Administration(progress.database, progress.token, progress.settings)
    assert admin.usage(org).active_units["parse"] == len(admitted)
    assert admin.usage(org).reserved_resolution_units == len(admitted)
    for work in admitted:
        progress.process_fixture(work)
    for job in jobs:
        run_until_terminal(progress, org, job)
    assert admin.usage(org).settled_resolution_units == len(jobs)
    assert admin.usage(org).reserved_resolution_units == 0


def test_real_contended_source_grant_and_backoff_use_post_lock_time(scenario: Scenario) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from emailmonitor.administration.source import SourceAdmission
    from emailmonitor.fetching.safety import classify_url
    from emailmonitor.sources.policy import Operation
    from sqlalchemy import Connection, create_engine

    progress, _ = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    source = SourceAdmission(progress.database, progress.token, progress.settings)
    url = classify_url(
        "https://synthetic.publisher.example/article-a.html",
        frozenset({"synthetic.publisher.example"}),
    )
    admin = create_engine(scenario.admin_url)

    def contended(connection: Connection, function: str) -> object:
        pid: object = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            # Current-query statistics are transaction-cached; refresh this read-only
            # observation while retaining the exact owned mutex lock.
            connection.execute(text("SELECT pg_stat_clear_snapshot()"))
            waiting: object = connection.execute(
                text("""SELECT EXISTS(SELECT 1 FROM pg_stat_activity a
WHERE :pid=ANY(pg_blocking_pids(a.pid)) AND a.query LIKE :function)"""),
                {"pid": pid, "function": f"%{function}%"},
            ).scalar_one()
            if waiting is True:
                # Keep the exact owned waiter blocked for a measurable interval.
                time.sleep(1)
                return connection.execute(text("SELECT clock_timestamp()")).scalar_one()
            time.sleep(0.01)
        raise AssertionError("Owned source call never contended on its held mutex")

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            started = Event()

            def acquire() -> object:
                started.set()
                return source.acquire(org, 1, Operation.HTML, url, time.monotonic() + 15)

            with admin.begin() as connection:
                connection.execute(
                    text("SELECT id FROM emailmonitor.admission_mutex WHERE id FOR UPDATE")
                )
                future = executor.submit(acquire)
                assert started.wait(2)
                grant_unlock = contended(connection, "source_resource_claim")
            ticket = future.result(timeout=16)
            from emailmonitor.administration.source import SourceLease

            assert isinstance(ticket, SourceLease)
            with admin.begin() as connection:
                valid: object = connection.execute(
                    text("""SELECT ready_at>=CAST(:unlock AS timestamptz)+interval '5 seconds'
FROM emailmonitor.source_resource_buckets WHERE source_id='synthetic-publisher'"""),
                    {"unlock": grant_unlock},
                ).scalar_one()
                assert valid is True
            started.clear()

            def finish() -> None:
                started.set()
                source.finish(ticket, 429, "5")

            with admin.begin() as connection:
                connection.execute(
                    text("SELECT id FROM emailmonitor.admission_mutex WHERE id FOR UPDATE")
                )
                future_finish = executor.submit(finish)
                assert started.wait(2)
                finish_unlock = contended(connection, "source_resource_finish")
            future_finish.result(timeout=6)
            with admin.begin() as connection:
                valid = connection.execute(
                    text("""SELECT retry_after_until>=
CAST(:unlock AS timestamptz)+interval '5 seconds'
FROM emailmonitor.source_resource_buckets WHERE source_id='synthetic-publisher'"""),
                    {"unlock": finish_unlock},
                ).scalar_one()
                assert valid is True
    finally:
        admin.dispose()


@pytest.mark.parametrize(
    "state",
    [
        "expired",
        "cleanup_finished",
        "failure_finished",
        "response_finished",
        "wrong_nonce",
        "waiting",
    ],
)
def test_real_source_success_requires_its_live_active_current_lease(
    scenario: Scenario, state: str
) -> None:
    from emailmonitor.administration.source import SourceAdmission, SourceLease
    from emailmonitor.fetching.safety import FetchDenied, classify_url
    from emailmonitor.sources.policy import Operation
    from sqlalchemy import create_engine

    progress, _ = planned(scenario, "https://synthetic.publisher.example/article-a.html")
    org = scenario.organizations[0]
    source = SourceAdmission(progress.database, progress.token, progress.settings)
    url = classify_url(
        "https://synthetic.publisher.example/article-a.html",
        frozenset({"synthetic.publisher.example"}),
    )
    active = source.acquire(org, 1, Operation.HTML, url, time.monotonic() + 15)
    tested = active
    admin = create_engine(scenario.admin_url)
    try:
        if state in {"expired", "cleanup_finished"}:
            with admin.begin() as connection:
                connection.execute(
                    text(
                        """UPDATE emailmonitor.source_resource_requests
SET lease_until=clock_timestamp()-interval '1 second' WHERE organization_id=:org AND id=:id"""
                    ),
                    {"org": org, "id": active.identifier},
                )
                if state == "cleanup_finished":
                    connection.execute(
                        text("SELECT id FROM emailmonitor.admission_mutex WHERE id FOR UPDATE")
                    )
                    connection.execute(text("SELECT emailmonitor.admission_cleanup()"))
        elif state == "failure_finished":
            source.finish(active)
        elif state == "response_finished":
            source.finish(active, 200)
        elif state == "wrong_nonce":
            tested = SourceLease(active.identifier, uuid4(), org)
        else:
            tested = SourceLease(uuid4(), uuid4(), org)
            with progress.database.tenant(progress.token, org, Capability.ACQUIRE_SOURCE) as (
                connection,
                _,
            ):
                advice: object = connection.execute(
                    text(
                        """SELECT emailmonitor.source_resource_claim(
:org,:id,NULL,1,'fetch_html','/article-a.html',:nonce,10)"""
                    ),
                    {"org": org, "id": tested.identifier, "nonce": tested.nonce},
                ).scalar_one()
                assert isinstance(advice, dict) and not advice["admitted"]
        with pytest.raises(FetchDenied):
            source.finish(tested, 200)
        # Cleanup is distinct from authorization to release a successful response.
        source.finish(active)
        if tested != active and state == "waiting":
            source.finish(tested)
    finally:
        admin.dispose()


def test_real_draft_parse_cannot_commit_after_lease_expiry_and_slot_reuse(
    scenario: Scenario,
) -> None:
    from emailmonitor.administration.admission import Admission
    from emailmonitor.administration.binding import CURRENT, bound
    from emailmonitor.discovery.fixture import fixture_bytes
    from emailmonitor.discovery.search import parse_search
    from emailmonitor.organizations.database import AuthorizationDenied
    from sqlalchemy import create_engine

    progress, job = planned(scenario)
    org = scenario.organizations[0]
    url = "https://synthetic.publisher.example/search-page-1.html"
    page = parse_search(progress.settings, url, fixture_bytes("search-page-1.html"))
    admission = Admission(progress.database, progress.token, progress.settings)
    admin = create_engine(scenario.admin_url)
    try:
        # Capture a genuine admitted parser scope, then expire only this owned row.
        with pytest.raises(AuthorizationDenied):
            with admission.fixture(org, job, url):
                old = CURRENT.get()
                assert old is not None
                with admin.begin() as connection:
                    connection.execute(
                        text(
                            """UPDATE emailmonitor.admission_requests
SET lease_until=clock_timestamp()-interval '1 second'
WHERE organization_id=:org AND job_id=:job AND reference_id=:reference AND nonce=:nonce"""
                        ),
                        {"org": org, "job": job, "reference": old.reference, "nonce": old.nonce},
                    )
                with admission.fixture(org, job, url):
                    replacement = CURRENT.get()
                    assert replacement is not None and replacement.nonce != old.nonce
                    with bound(old):
                        with pytest.raises(AuthorizationDenied):
                            progress.discovery.commit(org, job, 1, page)
                    assert progress.discovery.read(org, job)["revision"] == 1
                # The stale successful context exit also must refuse.
        assert progress.discovery.read(org, job)["revision"] == 1
        assert (
            not Administration(progress.database, progress.token, progress.settings)
            .usage(org)
            .active_units
        )
    finally:
        admin.dispose()

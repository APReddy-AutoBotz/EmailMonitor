"""Real SQL callback fences; absent disposable PostgreSQL is an explicit skip.

Two cases reuse the existing ephemeral service-login fixture. No gateway, parser,
network acquisition, persistent grants or live database target is introduced.
"""

import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from uuid import UUID

import pytest
import test_service_authority_tenant as service_fixtures
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.progress.binding import bound
from emailmonitor.progress.provider import ProviderJourney
from emailmonitor.progress.service import Progress
from emailmonitor.sources import provider_documents as catalog
from sqlalchemy import Connection, text
from test_durable_jobs import SETTINGS
from test_progress_tenant import claim
from test_provider_journey_tenant import NoDispatch, planned_provider
from test_service_authority_tenant import ServiceCase
from test_service_authority_tenant import _service_ci_guard as _service_ci_guard
from test_service_authority_tenant import service_case as service_case
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


@pytest.fixture
def provider_service_case(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, route: str
) -> ServiceCase:
    def plan(s: Scenario) -> tuple[Progress, UUID]:
        return planned_provider(s, url=None if route == "discover" else catalog.DOI_URL)

    # Reuse all existing exact-CI guards, role setup and finally cleanup. Only the
    # authored job plan differs; this is installed before fixture construction.
    monkeypatch.setattr(service_fixtures, "planned", plan)
    case: ServiceCase = request.getfixturevalue("service_case")
    return case


@pytest.mark.parametrize("route,mutation", [("discover", "revoke"), ("article", "policy")])
def test_service_callback_releases_sql_locks_then_next_callback_denies(
    provider_service_case: ServiceCase,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    mutation: str,
) -> None:
    case = provider_service_case
    org, job = case.scope.organization, case.scope.resource
    progress = Progress(case.database, case.scope, SETTINGS)
    work = claim(progress, org, job)
    assert work.kind == route
    journey = ProviderJourney(progress, NoDispatch())
    with bound(work.lease):
        boundary, _ = journey.boundary(work)
        original_authorize = progress.discovery._authorize
        original_documents = catalog.documents
        authorization_calls = 0
        writer: Future[None] | None = None
        released_before_return = False

        def audit_count() -> int:
            with case.admin.connect() as c:
                return int(
                    c.execute(
                        text(
                            "SELECT count(*) FROM emailmonitor.service_audit "
                            "WHERE principal_id=:principal AND action='transaction'"
                        ),
                        {"principal": case.principal},
                    ).scalar_one()
                )

        before = audit_count()
        with ThreadPoolExecutor(max_workers=1) as executor:

            def authorize(
                c: Connection,
                actual_org: UUID,
                actual_job: UUID,
                version: int,
                url: str,
                search: bool,
            ) -> dict[str, object]:
                nonlocal authorization_calls, writer
                policy = original_authorize(c, actual_org, actual_job, version, url, search)
                authorization_calls += 1
                # Discovery prepares through this instance as well; article scope
                # calls the static guard. Start contention at the final fence.
                if authorization_calls != (2 if route == "discover" else 1):
                    return policy
                worker_pid: int = c.execute(text("SELECT pg_backend_pid()")).scalar_one()
                writer_identity: Future[int] = Future()

                def change() -> None:
                    with case.admin.begin() as other:
                        other.execute(text("SET LOCAL lock_timeout='3000ms'"))
                        other.execute(text("SET LOCAL statement_timeout='5000ms'"))
                        writer_identity.set_result(
                            other.execute(text("SELECT pg_backend_pid()")).scalar_one()
                        )
                        if mutation == "revoke":
                            other.execute(
                                text(
                                    "UPDATE emailmonitor.service_delegations "
                                    "SET revoked_at=clock_timestamp() WHERE id=:grant"
                                ),
                                {"grant": case.grant},
                            )
                        else:
                            other.execute(
                                text(
                                    "UPDATE emailmonitor.source_policies SET state='revoked' "
                                    "WHERE organization_id=:org AND source_id=:source "
                                    "AND version=:version"
                                ),
                                {"org": org, "source": catalog.SOURCE, "version": version},
                            )

                until = time.monotonic() + 1
                writer = executor.submit(change)
                writer_pid = writer_identity.result(timeout=max(0, until - time.monotonic()))
                while True:
                    with case.admin.connect() as observer:
                        blocked: bool = observer.execute(
                            text(
                                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                                "WHERE pid=:writer_pid AND :worker_pid=ANY(pg_blocking_pids(pid)))"
                            ),
                            {"writer_pid": writer_pid, "worker_pid": worker_pid},
                        ).scalar_one()
                    if blocked:
                        break
                    assert not writer.done(), "Writer did not contend on current callback locks"
                    assert time.monotonic() < until, "Writer did not reach bounded lock wait"
                    time.sleep(0.01)
                assert not writer.done()
                return policy

            def documents(support: Any, source: str) -> Any:
                nonlocal released_before_return
                assert writer is not None
                # This runs inside _request, after its tenant context exits but
                # before the current binding can return to a channel callback.
                writer.result(timeout=4)
                released_before_return = True
                assert audit_count() == before + 1
                return original_documents(support, source)

            monkeypatch.setattr(progress.discovery, "_authorize", authorize)
            monkeypatch.setattr(catalog, "documents", documents)
            boundary.check_current()
            assert released_before_return
            assert authorization_calls == (2 if route == "discover" else 1)
            monkeypatch.setattr(progress.discovery, "_authorize", original_authorize)
            monkeypatch.setattr(catalog, "documents", original_documents)
            # A second callback must enter a fresh service-authorized transaction:
            # neither the successful binding nor its policy may be cached.
            with pytest.raises(FetchDenied):
                boundary.check_current()

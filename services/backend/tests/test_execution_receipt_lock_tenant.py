"""Real SQL receipt concurrency; unavailable disposable SQL is an explicit skip."""

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Event, Thread
from uuid import UUID

import pytest
from emailmonitor.fetching.fixture import HOSTS, TenantFixtureAuthorization
from emailmonitor.fetching.safety import FetchDenied, classify_url
from emailmonitor.organizations.database import AuthorizationDenied, Database, digest
from emailmonitor.progress.binding import bound
from emailmonitor.progress.service import Progress
from emailmonitor.sources.policy import Operation
from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.exc import DBAPIError
from test_progress_tenant import claim, planned
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


@contextmanager
def held_receipt(engine: Engine, action: Callable[[], None]) -> Iterator[None]:
    entered, release = Event(), Event()
    failures: list[BaseException] = []

    def hold(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        many: bool,
    ) -> None:
        if "SELECT emailmonitor.execution_confirmed(" in statement:
            entered.set()
            if not release.wait(5):
                raise AssertionError("Owned SQL barrier exceeded")

    def run() -> None:
        try:
            action()
        except BaseException as error:
            failures.append(error)

    event.listen(engine, "after_cursor_execute", hold)
    thread = Thread(target=run)
    thread.start()
    try:
        assert entered.wait(5), [type(error).__name__ for error in failures]
        yield
    finally:
        release.set()
        thread.join(5)
        event.remove(engine, "after_cursor_execute", hold)
        assert not thread.is_alive()
        assert not failures, [type(error).__name__ for error in failures]


def test_receipt_allows_actual_claimed_worker_authorization(scenario: Scenario) -> None:
    progress, job = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    pending = next(row for row in progress.pending(org) if row["job_id"] == job)
    work = claim(progress, org, job)
    worker = Database(os.environ["EM_TEST_DATABASE_URL"])
    authorize = TenantFixtureAuthorization(worker, progress.token, org, "synthetic-publisher", 1)

    def check() -> None:
        with bound(work.lease):
            authorize(classify_url(work.url, HOSTS), Operation.SEARCH)

    try:
        check()
        with held_receipt(
            progress.database.engine,
            lambda: progress.confirmed(org, job, UUID(str(pending["event_id"]))),
        ):
            check()
        check()
        progress.control(org, job, progress.snapshot(org, job).revision, "cancel")
        with pytest.raises(FetchDenied):
            check()
    finally:
        worker.engine.dispose()


LOCK_TARGETS = {
    "job": "SELECT 1 FROM emailmonitor.jobs "
    "WHERE organization_id=:org AND id=:job FOR UPDATE NOWAIT",
    "deletion": "SELECT 1 FROM emailmonitor.organizations WHERE id=:org FOR UPDATE NOWAIT",
    "membership": "SELECT 1 FROM emailmonitor.memberships "
    "WHERE organization_id=:org AND identity_id=:actor FOR UPDATE NOWAIT",
    "identity": "SELECT 1 FROM emailmonitor.identities WHERE id=:actor FOR UPDATE NOWAIT",
    "session": "SELECT 1 FROM emailmonitor.sessions WHERE token_hash=:token FOR UPDATE NOWAIT",
    "source": "SELECT 1 FROM emailmonitor.source_catalog "
    "WHERE source_id='synthetic-publisher' FOR UPDATE NOWAIT",
    "policy": "SELECT 1 FROM emailmonitor.source_policy_heads "
    "WHERE organization_id=:org AND source_id='synthetic-publisher' FOR UPDATE NOWAIT",
    "discovery": "SELECT 1 FROM emailmonitor.discovery "
    "WHERE organization_id=:org AND job_id=:job FOR UPDATE NOWAIT",
}


@pytest.mark.parametrize("target", LOCK_TARGETS)
def test_receipt_control_lock_compatibility_matches_existing_scope(
    scenario: Scenario, target: str
) -> None:
    progress, job = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    pending = next(row for row in progress.pending(org) if row["job_id"] == job)
    params = {
        "org": org,
        "job": job,
        "actor": scenario.identities["owner"],
        "token": digest(progress.token),
    }
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with held_receipt(
            progress.database.engine,
            lambda: progress.confirmed(org, job, UUID(str(pending["event_id"]))),
        ):
            if target in {"source", "policy"}:
                # Existing extraction jobs do not populate jobs.source_id; the
                # original control fence does not lock these rows either.
                # Preserve that limitation explicitly, not a stronger safety claim.
                with admin.begin() as c:
                    assert (
                        c.execute(
                            text("SELECT source_id FROM emailmonitor.jobs WHERE id=:job"), params
                        ).scalar_one()
                        is None
                    )
                    assert c.execute(text(LOCK_TARGETS[target]), params).first() is not None
            else:
                with pytest.raises(DBAPIError) as refused, admin.begin() as c:
                    c.execute(text(LOCK_TARGETS[target]), params)
                assert refused.value.orig is not None
                assert refused.value.orig.args[0]["C"] == "55P03"
        with admin.begin() as c:
            assert c.execute(text(LOCK_TARGETS[target]), params).first() is not None
    finally:
        admin.dispose()


@pytest.mark.parametrize(
    "target",
    [target for target in LOCK_TARGETS if target not in {"source", "policy"}] + ["receipt"],
)
def test_control_first_or_concurrent_receipt_serializes_or_refuses(
    scenario: Scenario, target: str
) -> None:
    progress, job = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    pending = next(row for row in progress.pending(org) if row["job_id"] == job)
    event_id = UUID(str(pending["event_id"]))
    params = {
        "org": org,
        "job": job,
        "event": event_id,
        "actor": scenario.identities["owner"],
        "token": digest(progress.token),
    }
    peer_database = Database(os.environ["EM_TEST_DATABASE_URL"])
    peer = Progress(peer_database, progress.token, progress.settings)
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    failures: list[BaseException] = []
    done = Event()
    with peer_database.engine.connect() as c:
        peer_pid: int = c.execute(text("SELECT pg_backend_pid()")).scalar_one()

    def confirm() -> None:
        try:
            peer.confirmed(org, job, event_id)
        except BaseException as error:
            failures.append(error)
        finally:
            done.set()

    def contend() -> None:
        thread = Thread(target=confirm)
        thread.start()
        try:
            deadline = time.monotonic() + 3
            with admin.connect() as observer:
                while time.monotonic() < deadline:
                    blocked: bool = observer.execute(
                        text("SELECT cardinality(pg_blocking_pids(:pid))>0"), {"pid": peer_pid}
                    ).scalar_one()
                    if blocked:
                        break
                    if done.is_set():
                        assert failures, "Receipt succeeded while conflicting control lock held"
                        return
                    time.sleep(0.01)
                else:
                    raise AssertionError("Expected receipt to wait behind owned transaction")
            assert not done.is_set()
        finally:
            # The outer owner releases its transaction before joining this thread.
            threads.append(thread)

    threads: list[Thread] = []
    try:
        if target == "receipt":
            with held_receipt(
                progress.database.engine, lambda: progress.confirmed(org, job, event_id)
            ):
                contend()
        else:
            with admin.begin() as holder:
                holder.execute(text(LOCK_TARGETS[target]), params)
                contend()
    finally:
        for thread in threads:
            thread.join(5)
            assert not thread.is_alive()
        peer_database.engine.dispose()
        admin.dispose()
    assert done.is_set()
    if failures:
        assert target != "receipt"
        assert len(failures) == 1 and isinstance(failures[0], DBAPIError)
        error = failures[0].orig
        assert error is not None
        assert error.args[0]["C"] in {"55P03", "EM014", "EM010", "P0001"}
        # An actual authority/lock refusal cannot manufacture a durable receipt.
        check = create_engine(scenario.admin_url, hide_parameters=True)
        try:
            with check.connect() as c:
                assert (
                    c.execute(
                        text(
                            "SELECT published_at FROM emailmonitor.execution_outbox "
                            "WHERE organization_id=:org AND job_id=:job AND event_id=:event"
                        ),
                        params,
                    ).scalar_one()
                    is None
                )
        finally:
            check.dispose()


def test_receipt_duplicates_and_rollback_preserve_durable_outbox(scenario: Scenario) -> None:
    progress, job = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    pending = next(row for row in progress.pending(org) if row["job_id"] == job)
    event_id = UUID(str(pending["event_id"]))
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    statement = text(
        "SELECT published_at FROM emailmonitor.execution_outbox "
        "WHERE organization_id=:org AND job_id=:job AND event_id=:event"
    )
    params = {"org": org, "job": job, "event": event_id}

    def receipt() -> object:
        with admin.connect() as c:
            return c.execute(statement, params).scalar_one()

    from emailmonitor.organizations.roles import Capability

    try:
        assert receipt() is None
        with pytest.raises(RuntimeError, match="uncertain publication"):
            with progress.database.tenant(progress.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
                c.execute(text("SELECT emailmonitor.execution_confirmed(:org,:job,:event)"), params)
                raise RuntimeError("uncertain publication")
        assert receipt() is None
        progress.confirmed(org, job, event_id)
        first = receipt()
        assert first is not None
        progress.confirmed(org, job, event_id)
        assert receipt() == first
        progress.control(org, job, progress.snapshot(org, job).revision, "cancel")
        progress.confirmed(org, job, event_id)
        assert receipt() == first
    finally:
        admin.dispose()


@pytest.mark.parametrize("first_receipt", [False, True])
@pytest.mark.parametrize("mutation", ["session", "identity", "tenant", "deletion"])
def test_committed_revocation_or_deletion_fences_later_receipt(
    scenario: Scenario, mutation: str, first_receipt: bool
) -> None:
    from emailmonitor.lifecycle.models import DeletionRequest
    from test_lifecycle_tenant import lifecycle

    progress, job = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    pending = next(row for row in progress.pending(org) if row["job_id"] == job)
    event_id = UUID(str(pending["event_id"]))
    admin = create_engine(scenario.admin_url, hide_parameters=True)
    params = {"org": org, "job": job, "event": event_id, "token": digest(progress.token)}
    receipt_sql = text(
        "SELECT published_at FROM emailmonitor.execution_outbox "
        "WHERE organization_id=:org AND job_id=:job AND event_id=:event"
    )
    try:
        if first_receipt:
            progress.confirmed(org, job, event_id)
        with admin.connect() as c:
            before: object = c.execute(receipt_sql, params).scalar_one()
        if mutation == "deletion":
            lifecycle(scenario, progress.token).stage(
                org, DeletionRequest(job_id=job, reason="privacy_request")
            )
        else:
            sql = {
                "session": "UPDATE emailmonitor.sessions SET revoked_at=clock_timestamp() "
                "WHERE token_hash=:token",
                "identity": "UPDATE emailmonitor.identities SET active=false "
                "WHERE id=(SELECT identity_id FROM emailmonitor.sessions WHERE token_hash=:token)",
                "tenant": "UPDATE emailmonitor.organizations SET status='suspended' WHERE id=:org",
            }[mutation]
            with admin.begin() as c:
                c.execute(text(sql), params)
        with pytest.raises((AuthorizationDenied, DBAPIError)) as refused:
            progress.confirmed(org, job, event_id)
        if isinstance(refused.value, DBAPIError):
            assert refused.value.orig is not None
            assert refused.value.orig.args[0]["C"] in {"EM014", "P0001"}
        with admin.connect() as c:
            assert c.execute(receipt_sql, params).scalar_one() == before
    finally:
        admin.dispose()

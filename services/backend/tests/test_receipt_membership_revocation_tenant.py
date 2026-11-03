"""Committed normal-route revocation versus receipts in the existing SQL fixture."""

import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Event
from typing import Any
from uuid import UUID

import pytest
from api_client import APIClient
from emailmonitor.fetching.fixture import HOSTS, TenantFixtureAuthorization
from emailmonitor.fetching.safety import FetchDenied, classify_url
from emailmonitor.identity.foundation import COOKIE
from emailmonitor.organizations.database import AuthorizationDenied, Database
from emailmonitor.progress.binding import bound
from emailmonitor.progress.service import Progress, Work
from emailmonitor.sources.policy import Operation
from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.exc import DBAPIError
from test_execution_receipt_lock_tenant import held_receipt
from test_progress_tenant import claim, planned
from test_tenant_foundation import ORIGIN, Scenario
from test_tenant_foundation import scenario as scenario


@dataclass
class Case:
    scenario: Scenario
    owner: APIClient
    csrf: str
    actor: Progress
    observer: Engine
    job: UUID
    event_id: UUID
    work: Work
    actor_pid: int
    owner_pid: int

    @property
    def org(self) -> UUID:
        return self.scenario.organizations[0]

    def confirm(self) -> None:
        self.actor.confirmed(self.org, self.job, self.event_id)

    def revoke(self) -> int:
        return self.owner.patch(
            f"/api/v1/organizations/{self.org}/members/{self.scenario.identities['admin']}",
            headers={"Origin": ORIGIN, "X-CSRF-Token": self.csrf},
            json={"role": "admin", "status": "revoked", "expected_revision": 1},
        ).status_code

    def authorize_worker(self) -> None:
        authorize = TenantFixtureAuthorization(
            self.actor.database, self.actor.token, self.org, "synthetic-publisher", 1
        )
        with bound(self.work.lease):
            authorize(classify_url(self.work.url, HOSTS), Operation.SEARCH)

    def snapshot(self) -> tuple[tuple[object, ...], object]:
        # Compare owned durable state without printing lease tokens or row identifiers.
        with self.observer.connect() as c:
            seals: list[object] = []
            for table in ("jobs", "execution_items", "execution_effects", "execution_outbox"):
                key = "id" if table == "jobs" else "job_id"
                record = (
                    "to_jsonb(t)-'published_at'" if table == "execution_outbox" else "to_jsonb(t)"
                )
                seals.append(
                    c.execute(
                        text(
                            f"SELECT md5(COALESCE(string_agg(({record})::text,',' "
                            f"ORDER BY ({record})::text),'')) FROM emailmonitor.{table} t "
                            f"WHERE organization_id=:org AND {key}=:job"
                        ),
                        {"org": self.org, "job": self.job},
                    ).scalar_one()
                )
            seals.append(
                c.execute(
                    text(
                        "SELECT md5(string_agg(to_jsonb(t)::text,',' ORDER BY to_jsonb(t)::text)) "
                        "FROM emailmonitor.memberships t WHERE organization_id=:other"
                    ),
                    {"other": self.scenario.organizations[1]},
                ).scalar_one()
            )
            marker: object = c.execute(
                text(
                    "SELECT published_at FROM emailmonitor.execution_outbox "
                    "WHERE organization_id=:org AND job_id=:job AND event_id=:event"
                ),
                {"org": self.org, "job": self.job, "event": self.event_id},
            ).scalar_one()
        return tuple(seals), marker

    def assert_revoked(self, expected: tuple[tuple[object, ...], object]) -> None:
        with self.observer.connect() as c:
            assert c.execute(
                text(
                    "SELECT role,status,row_version FROM emailmonitor.memberships "
                    "WHERE organization_id=:org AND identity_id=:actor"
                ),
                {"org": self.org, "actor": self.scenario.identities["admin"]},
            ).one() == ("admin", "revoked", 2)
        with pytest.raises(AuthorizationDenied):
            self.confirm()
        with pytest.raises(FetchDenied, match="^source_policy_denied$"):
            self.authorize_worker()
        with pytest.raises(AuthorizationDenied):
            self.actor.finish(self.work)
        # Revoking an existing admin never requires transferring/removing the last owner.
        response = self.owner.patch(
            f"/api/v1/organizations/{self.org}/members/{self.scenario.identities['owner']}",
            headers={"Origin": ORIGIN, "X-CSRF-Token": self.csrf},
            json={"role": "owner", "status": "revoked", "expected_revision": 1},
        )
        assert response.status_code == 409
        assert self.snapshot() == expected


@pytest.fixture
def case(scenario: Scenario) -> Iterator[Case]:
    progress, job = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    pending = next(row for row in progress.pending(org) if row["job_id"] == job)
    peer = Database(progress.database.engine.url.render_as_string(hide_password=False))
    observer = create_engine(scenario.admin_url, hide_parameters=True)
    try:
        with scenario.client() as owner, scenario.client() as member:
            csrf = scenario.login(owner, "owner")
            scenario.login(member, "admin")
            actor = Progress(peer, str(member.cookies[COOKIE]), progress.settings)
            work = claim(actor, org, job)
            with peer.engine.connect() as c:
                actor_pid: int = c.execute(text("SELECT pg_backend_pid()")).scalar_one()
            with scenario.foundation.database.engine.connect() as c:
                owner_pid: int = c.execute(text("SELECT pg_backend_pid()")).scalar_one()
            value = Case(
                scenario,
                owner,
                csrf,
                actor,
                observer,
                job,
                UUID(str(pending["event_id"])),
                work,
                actor_pid,
                owner_pid,
            )
            value.authorize_worker()
            yield value
    finally:
        peer.engine.dispose()
        observer.dispose()


def assert_refusal(error: BaseException | None) -> None:
    if isinstance(error, AuthorizationDenied):
        return
    assert isinstance(error, DBAPIError) and error.orig is not None
    details = error.orig.args[0]
    assert details["C"] == "55P03" or (
        details["C"] == "P0001" and details["M"] == "JOB_UNAVAILABLE"
    )


def observe_contention(case: Case, future: Future[Any], pid: int, blocker: int) -> bool:
    deadline = time.monotonic() + 3
    with case.observer.connect() as c:
        while time.monotonic() < deadline:
            blockers: list[int] = c.execute(
                text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}
            ).scalar_one()
            if blocker in blockers:
                assert not future.done()
                return True
            if future.done():
                assert_refusal(future.exception())
                return False
            time.sleep(0.01)
    raise AssertionError("Owned contention was not observed within the test barrier")


@contextmanager
def hold_membership_update(engine: Engine) -> Iterator[tuple[Event, Event]]:
    entered, release = Event(), Event()

    def hold(
        c: Connection, cursor: object, sql: str, parameters: object, context: object, many: bool
    ) -> None:
        if "UPDATE emailmonitor.memberships SET role=" in sql:
            entered.set()
            if not release.wait(5):
                raise AssertionError("Owned membership transaction barrier exceeded")

    event.listen(engine, "after_cursor_execute", hold)
    try:
        yield entered, release
    finally:
        release.set()
        event.remove(engine, "after_cursor_execute", hold)


@pytest.mark.parametrize("existing_receipt", [False, True])
def test_committed_membership_revocation_preserves_receipt(
    case: Case, existing_receipt: bool
) -> None:
    if existing_receipt:
        case.confirm()
    before = case.snapshot()
    assert (before[1] is not None) == existing_receipt
    assert case.revoke() == 200
    case.assert_revoked(before)


def test_receipt_first_normal_membership_revocation_waits_then_fences(case: Case) -> None:
    before = case.snapshot()
    assert before[1] is None
    with ThreadPoolExecutor(max_workers=1) as pool:
        with held_receipt(case.actor.database.engine, case.confirm):
            revocation = pool.submit(case.revoke)
            assert observe_contention(case, revocation, case.owner_pid, case.actor_pid)
            assert case.snapshot() == before  # Receipt is still uncommitted.
        assert revocation.result(timeout=5) == 200
    after = case.snapshot()
    assert after[0] == before[0] and after[1] is not None
    case.assert_revoked(after)


def test_membership_revocation_first_receipt_refuses_without_mark(case: Case) -> None:
    before = case.snapshot()
    assert before[1] is None
    with hold_membership_update(case.scenario.foundation.database.engine) as (entered, release):
        with ThreadPoolExecutor(max_workers=2) as pool:
            revocation = pool.submit(case.revoke)
            try:
                assert entered.wait(3)
                receipt = pool.submit(case.confirm)
                observe_contention(case, receipt, case.actor_pid, case.owner_pid)
                assert case.snapshot() == before
            finally:
                release.set()
            assert revocation.result(timeout=5) == 200
            assert_refusal(receipt.exception(timeout=5))
    case.assert_revoked(before)

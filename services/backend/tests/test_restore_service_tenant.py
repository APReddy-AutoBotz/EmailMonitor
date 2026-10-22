"""Actual closed dump/restore proof; positive probes prove SQL identity, not login."""

import hashlib
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
from emailmonitor.discovery.service import Discovery
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.lifecycle.models import DeletionRequest, SuppressionCreate
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import digest
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.service import Progress
from emailmonitor.results.service import Results
from restore_exercise import ADMIN, AUTH, RUNTIME, RestoreRefused, capture, fingerprint, require_ci
from service_restore_exercise import (
    EXPORT_TABLES,
    SERVICE_TABLES,
    ServiceRestoreExercise,
    seal,
    service_rows,
    snapshot_difference_sections,
    supported_service_delta,
)
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_results_tenant import options, prepared, ready
from test_service_authority_tenant import require_service_sql_ci
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


@pytest.fixture(autouse=True)
def _closed_restore_ci_guard() -> None:
    # Refuse before Scenario can mutate anything outside the exact disposable CI.
    if os.environ.get("EM_REQUIRE_SYNTHETIC_RESTORE") != "true":
        pytest.skip("Required disposable service PostgreSQL dump/restore is unavailable")
    require_service_sql_ci(dict(os.environ))
    require_ci(dict(os.environ))


@dataclass(frozen=True)
class Authority:
    login: str
    principal: UUID
    organization: UUID
    resource: UUID
    kind: Literal["worker", "publisher"]
    purpose: Literal["extraction", "export"]
    grant: UUID

    def parameters(self) -> dict[str, object]:
        return {
            "org": self.organization,
            "resource": self.resource,
            "kind": self.kind,
            "purpose": self.purpose,
            "principal": self.principal,
            "generation": 1,
        }


def queued_job(results: Results, organization: UUID) -> UUID:
    """Reuse the fixture's approval/session; never approve a second policy version."""
    ledger = Ledger(results.database, results.token, SETTINGS)
    body = request_body()
    body["input"] = {"type": "url", "url": "https://synthetic.publisher.example/article-a.html"}
    job = ledger.create(organization, JobRequest.model_validate(body), str(uuid4()))
    Discovery(results.database, results.token, SETTINGS).plan(organization, job, 1)
    progress = Progress(results.database, results.token, SETTINGS)
    progress.start(organization, job, progress.snapshot(organization, job).revision)
    return job


def authorize(
    admin: Engine,
    results: Results,
    organization: UUID,
    resource: UUID,
    owned: list[tuple[str, UUID]],
    *,
    kind: Literal["worker", "publisher"] = "worker",
    purpose: Literal["extraction", "export"] = "extraction",
    seconds: int = 21600,
) -> Authority:
    login, principal = "em_service_test_" + uuid4().hex, uuid4()
    with admin.begin() as c:
        c.exec_driver_sql(
            f"CREATE ROLE {login} LOGIN NOSUPERUSER NOBYPASSRLS "
            "PASSWORD 'authored-disposable-service-only'"
        )
        c.exec_driver_sql(f"GRANT emailmonitor_{kind} TO {login}")
        c.execute(
            text(
                "INSERT INTO emailmonitor.service_principals "
                "(id,organization_id,login_oid,login_name,kind,active) "
                "SELECT :id,:org,oid,rolname,:kind,true FROM pg_roles WHERE rolname=:name"
            ),
            {"id": principal, "org": organization, "kind": kind, "name": login},
        )
    owned.append((login, principal))
    capability = Capability.ACQUIRE_SOURCE if purpose == "extraction" else Capability.EXPORT_RESULTS
    with results.database.tenant(results.token, organization, capability) as (c, _):
        grant: UUID = c.execute(
            text(
                "SELECT emailmonitor.delegate_service_work("
                ":org,:principal,:resource,:purpose,:seconds)"
            ),
            {
                "org": organization,
                "principal": principal,
                "resource": resource,
                "purpose": purpose,
                "seconds": seconds,
            },
        ).scalar_one()
    return Authority(login, principal, organization, resource, kind, purpose, grant)


@contextmanager
def identity_probe(engine: Engine, login: str) -> Iterator[Connection]:
    """A fresh trusted connection assumes an existing identity, then rolls back.

    Never call this an authenticated service connection to the closed target.
    No connection or session authorization is returned to any application pool.
    """
    assert login == "em_ci_runtime" or re.fullmatch(r"em_service_test_[a-f0-9]{32}", login)
    fresh = create_engine(
        engine.url, poolclass=NullPool, hide_parameters=True, connect_args={"timeout": 3}
    )
    try:
        with fresh.connect() as c:
            transaction = c.begin()
            try:
                assert c.execute(text("SELECT session_user,current_user")).one() == (
                    "postgres",
                    "postgres",
                )
                assert c.execute(
                    text("SELECT rolcanlogin FROM pg_roles WHERE rolname=:name"), {"name": login}
                ).scalar_one()
                c.exec_driver_sql(f'SET SESSION AUTHORIZATION "{login}"')
                assert c.execute(text("SELECT session_user,current_user")).one() == (login, login)
                c.execute(text("SET LOCAL statement_timeout='5000'"))
                c.execute(text("SET LOCAL lock_timeout='2000'"))
                yield c
            finally:
                transaction.rollback()
    finally:
        fresh.dispose()


def begin(c: Connection, authority: Authority, **changes: object) -> UUID:
    value: UUID = c.execute(
        text(
            "SELECT emailmonitor.service_begin("
            ":org,:resource,:purpose,:generation,:kind,:principal)"
        ),
        {**authority.parameters(), **changes},
    ).scalar_one()
    return value


def settings(c: Connection, **values: object) -> None:
    for name, value in values.items():
        c.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": "emailmonitor." + name, "value": str(value)},
        )


def sqlstate(error: DBAPIError) -> str:
    assert error.orig is not None
    detail = error.orig.args[0]
    assert isinstance(detail, dict)
    return str(detail.get("C"))


@contextmanager
def denied() -> Iterator[None]:
    with pytest.raises(DBAPIError) as raised:
        yield
    # An undefined function, syntax error or transaction error is not denial proof.
    code = sqlstate(raised.value)
    assert code.startswith("EM") or code == "42501"


def event(admin: Engine, authority: Authority) -> dict[str, Any]:
    table, column = (
        ("execution_outbox", "job_id")
        if authority.purpose == "extraction"
        else ("export_outbox", "export_id")
    )
    with admin.connect() as c:
        row = (
            c.execute(
                text(
                    f"SELECT * FROM emailmonitor.{table} "
                    f"WHERE organization_id=:org AND {column}=:resource"
                ),
                authority.parameters(),
            )
            .mappings()
            .one()
        )
    return dict(row)


def publication(c: Connection, authority: Authority, row: dict[str, Any]) -> object:
    return c.execute(
        text(
            "SELECT emailmonitor.service_publish_event("
            ":org,:resource,:purpose,:generation,:event,:item,true)"
        ),
        {
            **authority.parameters(),
            "event": row["event_id"],
            "item": row.get("item_id"),
        },
    ).scalar_one()


def claim(c: Connection, authority: Authority, row: dict[str, Any], token: UUID) -> object:
    return (
        c.execute(
            text(
                "SELECT * FROM emailmonitor.execution_claim("
                ":org,:resource,:item,:event,:token,30,1)"
            ),
            {
                **authority.parameters(),
                "item": row["item_id"],
                "event": row["event_id"],
                "token": token,
            },
        )
        .mappings()
        .one_or_none()
    )


def finish(c: Connection, authority: Authority, row: dict[str, Any], token: UUID) -> object:
    settings(
        c,
        execution_job=authority.resource,
        execution_item=row["item_id"],
        execution_token=token,
        execution_generation=1,
        execution_deletion=1,
    )
    return c.execute(
        text(
            "SELECT emailmonitor.execution_finish("
            ":org,:resource,:item,:token,NULL,'worker_failure',:event)"
        ),
        {
            **authority.parameters(),
            "item": row["item_id"],
            "token": token,
            "event": uuid4(),
        },
    ).scalar_one()


def assert_closed(target: ServiceRestoreExercise, owned: list[tuple[str, UUID]]) -> None:
    target.closed()
    assert not target.ready
    for original_url in (RUNTIME, AUTH):
        with pytest.raises(RestoreRefused, match="restore_service_target_must_remain_closed"):
            target.url(original_url)
    with pytest.raises(RestoreRefused, match="restore_service_target_must_remain_closed"):
        target.open_after_validation()
    # Genuine new connection attempts are separate from the trusted SQL probes.
    urls = [make_url(RUNTIME), make_url(AUTH)] + [
        make_url(ADMIN).set(username=login, password="authored-disposable-service-only")
        for login, _ in owned
    ]
    for url in urls:
        blocked = create_engine(
            url.set(database=target.name),
            poolclass=NullPool,
            connect_args={"timeout": 3},
            hide_parameters=True,
        )
        try:
            with pytest.raises(DBAPIError) as raised, blocked.connect():
                pytest.fail("A non-superuser opened the closed restore target")
            assert sqlstate(raised.value) in {"42501", "53300"}
        finally:
            blocked.dispose()


def test_actual_service_restore_keeps_revocations_privacy_and_sql_boundary_closed(
    scenario: Scenario, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    started = time.monotonic()
    org_a, org_b = scenario.organizations
    other = replace(
        scenario,
        organizations=(org_b, org_a),
        identities={**scenario.identities, "owner": scenario.identities["owner_b"]},
    )
    results_a, completed_a = prepared(scenario)
    results_b, completed_b = prepared(other, "article-b.html")
    export_a = ready(results_a, org_a, completed_a)
    export_b = ready(results_b, org_b, completed_b)
    expected_hash = hashlib.sha256(results_b.download(org_b, export_b).body).hexdigest()
    pending_export = results_b.create(org_b, options(completed_b), str(uuid4())).id
    life_a = Lifecycle(results_a.database, results_a.token, SETTINGS)
    life_b = Lifecycle(results_b.database, results_b.token, SETTINGS)
    life_a.retention(org_a)
    life_b.retention(org_b)
    job = queued_job(results_b, org_b)
    foreign_job = queued_job(results_a, org_a)
    admin = create_engine(ADMIN, hide_parameters=True)
    target = ServiceRestoreExercise(tmp_path)
    owned: list[tuple[str, UUID]] = []
    try:
        current_worker = authorize(admin, results_b, org_b, job, owned)
        foreign_worker = authorize(admin, results_a, org_a, foreign_job, owned)
        revoked_worker = authorize(admin, results_b, org_b, job, owned)
        disabled_worker = authorize(admin, results_b, org_b, job, owned)
        publisher = authorize(admin, results_b, org_b, job, owned, kind="publisher")
        revoked_publisher = authorize(admin, results_b, org_b, job, owned, kind="publisher")
        export_worker = authorize(admin, results_b, org_b, pending_export, owned, purpose="export")
        export_publisher = authorize(
            admin, results_b, org_b, pending_export, owned, kind="publisher", purpose="export"
        )
        # A separate job avoids shortening all grants for the unchanged current job.
        expired_job = queued_job(results_b, org_b)
        expired_worker = authorize(admin, results_b, org_b, expired_job, owned, seconds=5)
        pending = event(admin, current_worker)
        export_pending = event(admin, export_worker)
        expired_pending = event(admin, expired_worker)
        # No worker/publisher process is started. All completed work above was
        # synchronous; the remaining outbox rows are queued with no live leases.
        for authority in (
            current_worker,
            foreign_worker,
            revoked_worker,
            disabled_worker,
            publisher,
        ):
            with identity_probe(admin, authority.login) as c:
                assert begin(c, authority) == authority.grant
        # This is an existing, currently valid grant in the other tenant. Its
        # identifiers still cannot authorize our tenant-B service connection.
        with denied(), identity_probe(admin, current_worker.login) as c:
            begin(c, foreign_worker)
        # Supported human transitions below may explicitly reconnect, but both
        # capture boundaries close every fixture application/authenticator pool.
        results_a.database.engine.dispose()
        results_b.database.engine.dispose()
        scenario.foundation.authentication.engine.dispose()
        with admin.connect() as c:
            # REVOKE on these new tables materializes the owner-only default.
            # pg_dump omits that redundant ACL, so restore legitimately stores
            # NULL. Compare the complete effective grants, not their storage.
            source_acls: dict[str, str] = {}
            for table in SERVICE_TABLES:
                acl = (
                    c.execute(
                        text(
                            "SELECT relacl IS NOT NULL AND "
                            "relacl=acldefault('r',relowner) AS owner_default,"
                            "COALESCE(relacl,acldefault('r',relowner))::text AS effective "
                            "FROM pg_class WHERE oid=CAST(:table AS regclass)"
                        ),
                        {"table": "emailmonitor." + table},
                    )
                    .mappings()
                    .one()
                )
                if acl["owner_default"] is not True:
                    raise RestoreRefused("restore_source_default_acl_refused")
                source_acls[table] = acl["effective"]
            # PostgreSQL's raw JSON representation of oid is a string. The
            # capture boundary changes only this field to an exact integer.
            raw = (
                c.execute(
                    text(
                        "SELECT row_to_json(t) AS record,t.login_oid::bigint AS login_oid "
                        "FROM emailmonitor.service_principals t "
                        "WHERE t.organization_id=:org AND t.id=:id"
                    ),
                    {"org": org_b, "id": current_worker.principal},
                )
                .mappings()
                .one()
            )
            assert type(raw["record"]["login_oid"]) is str
            assert type(raw["login_oid"]) is int
            assert raw["record"]["login_oid"] == str(raw["login_oid"])
            normalized = next(
                row
                for row in service_rows(c, "service_principals")
                if row["id"] == str(current_worker.principal)
            )
            assert type(normalized["login_oid"]) is int
            assert normalized == {**raw["record"], "login_oid": raw["login_oid"]}
            # OID is unsigned32: the SQL boundary must not narrow it to int4.
            maximum = (
                c.execute(
                    text(
                        "SELECT row_to_json(t) AS raw_record,"
                        "jsonb_build_object('login_oid',t.login_oid::bigint) AS projected_record "
                        "FROM (SELECT '4294967295'::oid AS login_oid) t"
                    )
                )
                .mappings()
                .one()
            )
            assert maximum["raw_record"] == {"login_oid": "4294967295"}
            assert maximum["projected_record"] == {"login_oid": 4294967295}
            assert type(maximum["projected_record"]["login_oid"]) is int
            for login, _ in owned:
                assert (
                    c.execute(
                        text("SELECT count(*) FROM pg_stat_activity WHERE usename=:login"),
                        {"login": login},
                    ).scalar_one()
                    == 0
                )
        with pytest.raises(RestoreRefused, match="restore_service_authority_unsupported"):
            capture(admin, scenario.organizations)
        before = target.capture(admin, scenario.organizations)
        archive_digest = target.backup()

        for authority in (revoked_worker, revoked_publisher):
            with results_b.database.tenant(results_b.token, org_b, Capability.ACQUIRE_SOURCE) as (
                c,
                _,
            ):
                c.execute(
                    text("SELECT emailmonitor.revoke_service_work(:org,:id)"),
                    {"org": org_b, "id": authority.grant},
                )
        with admin.begin() as c:
            c.execute(
                text("UPDATE emailmonitor.service_principals SET active=false WHERE id=:id"),
                {"id": disabled_worker.principal},
            )
        marker = life_a.stage(org_a, DeletionRequest(job_id=completed_a, reason="privacy_request"))
        life_a.purge(org_a, marker.id)
        life_a.suppress(
            org_a, SuppressionCreate(kind="domain", value="example.org", reason="privacy_request")
        )
        with admin.begin() as c:
            c.execute(
                text(
                    "UPDATE emailmonitor.source_policies SET state='revoked' "
                    "WHERE organization_id=:org AND source_id='synthetic-publisher' AND version=1"
                ),
                {"org": org_a},
            )
        # Wall-clock expiry changes no immutable grant row and is never extended.
        with admin.connect() as c:
            remaining = float(
                c.execute(
                    text(
                        "SELECT greatest(0,extract(epoch FROM deadline-clock_timestamp())) "
                        "FROM emailmonitor.service_delegations WHERE id=:id"
                    ),
                    {"id": expired_worker.grant},
                ).scalar_one()
            )
        assert remaining <= 5
        if remaining:
            time.sleep(remaining + 0.05)
        results_a.database.engine.dispose()
        results_b.database.engine.dispose()
        scenario.foundation.authentication.engine.dispose()
        current = target.capture(admin, scenario.organizations)
        supported_service_delta(before, current)
        assert {row["id"]: row["deadline"] for row in seal(before).delegations} == {
            row["id"]: row["deadline"] for row in seal(current).delegations
        }
        assert all(row["action"] != "transaction" for row in seal(current).audit)
        target.restore_closed()
        assert_closed(target, owned)
        with target.target.connect() as c:
            for table in SERVICE_TABLES:
                acl_matches = c.execute(
                    text(
                        "SELECT relacl IS NULL,"
                        "COALESCE(relacl,acldefault('r',relowner))::text=:source_acl "
                        "FROM pg_class WHERE oid=CAST(:table AS regclass)"
                    ),
                    {"table": "emailmonitor." + table, "source_acl": source_acls[table]},
                ).one() == (True, True)
                if not acl_matches:
                    raise RestoreRefused("restore_effective_acl_mismatch")
        restored = target.capture(target.target, scenario.organizations)
        if fingerprint(restored) != fingerprint(before):
            # Fixed section labels only: never print authority rows or hashes.
            sections = snapshot_difference_sections(before, restored)
            error = RestoreRefused("restore_snapshot_mismatch")
            error.add_note("snapshot sections: " + ",".join(sections))
            raise error
        # These Results fixtures retain ordinary human tokens, not service scopes.
        assert isinstance(results_a.token, str) and isinstance(results_b.token, str)
        human_tokens = {org_a: results_a.token, org_b: results_b.token}
        target.replay(before, current, human_tokens)
        first_seal = fingerprint(target.capture(target.target, scenario.organizations))
        target.replay(before, current, human_tokens)
        assert fingerprint(target.capture(target.target, scenario.organizations)) == first_seal
        assert target.validated
        assert_closed(target, owned)

        for authority in (
            revoked_worker,
            disabled_worker,
            expired_worker,
            revoked_publisher,
            foreign_worker,
        ):
            with denied(), identity_probe(target.target, authority.login) as c:
                begin(c, authority)
        with denied(), identity_probe(target.target, current_worker.login) as c:
            begin(c, foreign_worker)
        # Restored human/session/member anchors retain their independent semantics.
        # Each mutation is inside one trusted rollback-only probe; no new session
        # or authority is minted and none of these temporary changes is persisted.
        for change in ("natural_expiry", "origin_revoked", "membership_revision"):
            with identity_probe(target.target, current_worker.login) as c:
                c.exec_driver_sql("RESET SESSION AUTHORIZATION")
                if change == "membership_revision":
                    c.execute(
                        text(
                            "UPDATE emailmonitor.memberships SET row_version=row_version "
                            "WHERE organization_id=:org AND identity_id=:identity"
                        ),
                        {"org": org_b, "identity": scenario.identities["owner_b"]},
                    )
                else:
                    assignment = (
                        "expires_at=transaction_timestamp()-interval '1 second'"
                        if change == "natural_expiry"
                        else "revoked_at=clock_timestamp()"
                    )
                    c.execute(
                        text(
                            f"UPDATE emailmonitor.sessions SET {assignment} WHERE token_hash=:hash"
                        ),
                        {"hash": digest(results_b.token)},
                    )
                    assert (
                        c.execute(
                            text("SELECT count(*) FROM emailmonitor.resolve_session(:hash)"),
                            {"hash": digest(results_b.token)},
                        ).scalar_one()
                        == 0
                    )
                c.exec_driver_sql(f'SET SESSION AUTHORIZATION "{current_worker.login}"')
                assert c.execute(text("SELECT session_user,current_user")).one() == (
                    current_worker.login,
                    current_worker.login,
                )
                if change == "natural_expiry":
                    assert begin(c, current_worker) == current_worker.grant
                else:
                    with denied():
                        begin(c, current_worker)
        # A stolen unrevoked grant ID, a tenant ID, or forged settings are not a login.
        with denied(), identity_probe(target.target, revoked_worker.login) as c:
            begin(c, current_worker)
        for changes in (
            {"org": org_a},
            {"resource": completed_b},
            {"purpose": "export"},
            {"generation": 2},
            {"kind": "publisher"},
        ):
            with denied(), identity_probe(target.target, current_worker.login) as c:
                begin(c, current_worker, **changes)
        with identity_probe(target.target, current_worker.login) as c:
            for table in ("jobs", "execution_items", "article_observations"):
                assert (
                    c.execute(text(f"SELECT count(*) FROM emailmonitor.{table}")).scalar_one() == 0
                )
            assert begin(c, current_worker) == current_worker.grant
            assert c.execute(text("SELECT id FROM emailmonitor.jobs")).scalars().all() == [job]
            settings(c, organization_id=org_a)
            assert c.execute(text("SELECT count(*) FROM emailmonitor.jobs")).scalar_one() == 0
        with denied(), identity_probe(target.target, current_worker.login) as c:
            claim(c, current_worker, pending, uuid4())
        for authority, row in (
            (revoked_worker, pending),
            (disabled_worker, pending),
            (expired_worker, expired_pending),
        ):
            for operation in (claim, finish):
                with denied(), identity_probe(target.target, authority.login) as c:
                    settings(
                        c,
                        organization_id=org_b,
                        service_delegation=authority.grant,
                        service_kind="worker",
                        session_hash="",
                    )
                    operation(c, authority, row, uuid4())
        with identity_probe(target.target, revoked_publisher.login) as c:
            assert (
                c.execute(
                    text("SELECT * FROM emailmonitor.service_pending(:principal,100)"),
                    {"principal": revoked_publisher.principal},
                ).all()
                == []
            )
        with denied(), identity_probe(target.target, revoked_publisher.login) as c:
            settings(
                c,
                organization_id=org_b,
                service_delegation=revoked_publisher.grant,
                service_kind="publisher",
                session_hash="",
            )
            publication(c, revoked_publisher, pending)
        for authority, row, phase in (
            (publisher, pending, "parse"),
            (export_publisher, export_pending, "export"),
        ):
            with identity_probe(target.target, authority.login) as c:
                rows = (
                    c.execute(
                        text("SELECT * FROM emailmonitor.service_pending(:principal,100)"),
                        {"principal": authority.principal},
                    )
                    .mappings()
                    .all()
                )
                assert [item["event_id"] for item in rows] == [row["event_id"]]
                assert begin(c, authority) == authority.grant
                assert publication(c, authority, row) == phase
                assert (
                    c.execute(
                        text("SELECT emailmonitor.service_end(:org,:resource,:purpose,:kind)"),
                        authority.parameters(),
                    ).scalar_one()
                    is None
                )
        # Actual claim and finish SQL succeeds for the unchanged grant, all rolled
        # back. Then revoke that same claimed grant inside the isolated probe and
        # prove its once-current lease cannot commit after revocation.
        with identity_probe(target.target, current_worker.login) as c:
            assert begin(c, current_worker) == current_worker.grant
            token = uuid4()
            assert claim(c, current_worker, pending, token) is not None
            assert finish(c, current_worker, pending, token) == "retry_wait"
        with denied(), identity_probe(target.target, current_worker.login) as c:
            assert begin(c, current_worker) == current_worker.grant
            token = uuid4()
            assert claim(c, current_worker, pending, token) is not None
            c.exec_driver_sql("RESET SESSION AUTHORIZATION")
            c.execute(
                text(
                    "UPDATE emailmonitor.service_delegations SET revoked_at=clock_timestamp() "
                    "WHERE id=:id"
                ),
                {"id": current_worker.grant},
            )
            c.exec_driver_sql(f'SET SESSION AUTHORIZATION "{current_worker.login}"')
            assert c.execute(text("SELECT session_user,current_user")).one() == (
                current_worker.login,
                current_worker.login,
            )
            finish(c, current_worker, pending, token)
        with identity_probe(target.target, export_worker.login) as c:
            assert begin(c, export_worker) == export_worker.grant
            assert (
                c.execute(
                    text("SELECT count(*) FROM emailmonitor.article_observations")
                ).scalar_one()
                == 0
            )
            assert (
                c.execute(
                    text("SELECT emailmonitor.exports_claim(:org,:resource,:event,1,:nonce,30)"),
                    {
                        **export_worker.parameters(),
                        "event": export_pending["event_id"],
                        "nonce": uuid4(),
                    },
                ).scalar_one()
                is not None
            )
        with denied(), identity_probe(target.target, export_worker.login) as c:
            begin(c, export_worker)
            c.execute(
                text("SELECT * FROM emailmonitor.exports_download(:org,:id)"),
                {"org": org_b, "id": export_b},
            )

        with target.target.connect() as c:
            for table in (
                *SERVICE_TABLES,
                *EXPORT_TABLES,
                "article_observations",
                "execution_items",
            ):
                assert c.execute(
                    text(
                        "SELECT relrowsecurity AND relforcerowsecurity "
                        "AND pg_get_userbyid(relowner)='emailmonitor_owner' FROM pg_class "
                        "WHERE oid=CAST(:table AS regclass)"
                    ),
                    {"table": "emailmonitor." + table},
                ).scalar_one()
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations WHERE job_id=:job"
                    ),
                    {"job": completed_a},
                ).scalar_one()
                == 0
            )
            assert (
                c.execute(
                    text("SELECT count(*) FROM emailmonitor.export_artifacts WHERE export_id=:id"),
                    {"id": export_a},
                ).scalar_one()
                == 0
            )
            assert c.execute(
                text(
                    "SELECT deadline<=clock_timestamp() FROM emailmonitor.service_delegations "
                    "WHERE id=:id"
                ),
                {"id": expired_worker.grant},
            ).scalar_one()
            assert c.execute(
                text("SELECT active,revision FROM emailmonitor.service_principals WHERE id=:id"),
                {"id": disabled_worker.principal},
            ).one() == (False, 2)
        with identity_probe(target.target, "em_ci_runtime") as c:
            assert c.execute(text("SELECT count(*) FROM emailmonitor.jobs")).scalar_one() == 0
            settings(c, organization_id=org_b, session_hash=digest(results_b.token))
            body = c.execute(
                text("SELECT body FROM emailmonitor.exports_download(:org,:id)"),
                {"org": org_b, "id": export_b},
            ).scalar_one()
            assert hashlib.sha256(bytes(body)).hexdigest() == expected_hash
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.article_observations WHERE job_id=:job"
                    ),
                    {"job": completed_b},
                ).scalar_one()
                > 0
            )
            settings(c, organization_id=org_a)
            assert c.execute(text("SELECT count(*) FROM emailmonitor.jobs")).scalar_one() == 0
        with denied(), identity_probe(target.target, "em_ci_runtime") as c:
            settings(c, organization_id=org_a, session_hash=digest(results_a.token))
            c.execute(
                text("SELECT * FROM emailmonitor.exports_download(:org,:id)"),
                {"org": org_a, "id": export_a},
            )
        with identity_probe(target.target, "em_ci_runtime") as c:
            settings(c, organization_id=org_a, session_hash=digest(results_a.token))
            assert not c.execute(
                text("SELECT emailmonitor.privacy_payload_allowed(:org,CAST(:payload AS jsonb))"),
                {"org": org_a, "payload": '{"raw_address":"mira@example.org"}'},
            ).scalar_one()
        # Probes added no transaction audit, publication receipt, lease, effect or
        # usage. The entire captured target, including export-owned tables, agrees.
        assert fingerprint(target.capture(target.target, scenario.organizations)) == first_seal
        target.replay(before, current, human_tokens)

        # Even with CONNECTION LIMIT 0 and no grants, the database owner must
        # remain the exact trusted owner. Restore it before all further probes.
        with target.admin.connect() as c:
            c.exec_driver_sql(f'ALTER DATABASE "{target.name}" OWNER TO "{current_worker.login}"')
        try:
            with pytest.raises(RestoreRefused, match="restore_service_closed_seal_refused"):
                target.closed()
            with pytest.raises(RestoreRefused, match="restore_service_closed_seal_refused"):
                target.replay(before, current, human_tokens)
        finally:
            with target.admin.connect() as c:
                c.exec_driver_sql(f'ALTER DATABASE "{target.name}" OWNER TO postgres')
        target.closed()
        # Target-only catalog drift after validation cannot bless a new seal.
        with target.target.begin() as c:
            c.exec_driver_sql("ALTER TABLE emailmonitor.service_audit NO FORCE ROW LEVEL SECURITY")
        try:
            with pytest.raises(RestoreRefused, match="restore_state_refused"):
                target.replay(before, current, human_tokens)
        finally:
            with target.target.begin() as c:
                c.exec_driver_sql("ALTER TABLE emailmonitor.service_audit FORCE ROW LEVEL SECURITY")
        assert fingerprint(target.capture(target.target, scenario.organizations)) == first_seal

        # Real post-backup receipt drift is unsupported, even with unchanged jobs.
        receipt_sql = text(
            "UPDATE emailmonitor.export_outbox SET published_at=:stamp "
            "WHERE organization_id=:org AND export_id=:id"
        )
        with admin.begin() as c:
            stamp = c.execute(text("SELECT clock_timestamp()")).scalar_one()
            c.execute(receipt_sql, {"stamp": stamp, "org": org_b, "id": pending_export})
        try:
            with pytest.raises(RestoreRefused, match="restore_service_export_drift"):
                supported_service_delta(before, target.capture(admin, scenario.organizations))
            with pytest.raises(RestoreRefused, match="restore_source_changed"):
                target.replay(before, current, human_tokens)
        finally:
            with admin.begin() as c:
                c.execute(receipt_sql, {"stamp": None, "org": org_b, "id": pending_export})
        assert fingerprint(target.capture(admin, scenario.organizations)) == fingerprint(current)
        with target.target.begin() as c:
            c.execute(receipt_sql, {"stamp": stamp, "org": org_b, "id": pending_export})
        with pytest.raises(RestoreRefused, match="restore_state_refused"):
            target.replay(before, current, human_tokens)
        assert_closed(target, owned)
        with capsys.disabled():
            print(
                {
                    "synthetic_service_restore": True,
                    "archive_sha256": archive_digest,
                    "same_cluster_existing_roles": True,
                    "target_always_closed": True,
                    "sql_session_identity_probes_only": True,
                    "target_login_authentication_proven": False,
                    "revoked_disabled_expired_work_denied": True,
                    "unchanged_grant_sql_claim_and_publish": True,
                    "stale_commit_denied": True,
                    "privacy_and_export_seals": True,
                    "exact_replay_noop_and_drift_refusal": True,
                    "exercise_seconds": round(time.monotonic() - started, 3),
                    "production_rpo_rto_measured": False,
                }
            )
    finally:
        try:
            target.close()
            assert not target.archive.exists()
            with admin.connect() as c:
                assert (
                    c.execute(
                        text("SELECT count(*) FROM pg_database WHERE datname=:name"),
                        {"name": target.name},
                    ).scalar_one()
                    == 0
                )
        finally:
            try:
                with admin.begin() as c:
                    for login, principal in owned:
                        for table in ("service_audit", "service_delegations"):
                            c.execute(
                                text(f"DELETE FROM emailmonitor.{table} WHERE principal_id=:id"),
                                {"id": principal},
                            )
                        c.execute(
                            text("DELETE FROM emailmonitor.service_principals WHERE id=:id"),
                            {"id": principal},
                        )
                        c.exec_driver_sql(f'DROP ROLE "{login}"')
                with admin.connect() as c:
                    for login, principal in owned:
                        assert (
                            c.execute(
                                text("SELECT count(*) FROM pg_roles WHERE rolname=:name"),
                                {"name": login},
                            ).scalar_one()
                            == 0
                        )
                        assert (
                            c.execute(
                                text(
                                    "SELECT count(*) FROM emailmonitor.service_principals "
                                    "WHERE id=:id"
                                ),
                                {"id": principal},
                            ).scalar_one()
                            == 0
                        )
            finally:
                admin.dispose()

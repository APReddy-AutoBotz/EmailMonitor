"""Actual disposable SQL authority checks, never live role/grant provisioning."""

import os
from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from emailmonitor.organizations.database import AuthorizationDenied, Database, TenantContext, digest
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import bound
from emailmonitor.progress.service import Progress
from emailmonitor.runtime.authority import ServiceProcess, ServiceWork
from emailmonitor.runtime.database import ServiceDatabase
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from test_durable_jobs import SETTINGS
from test_progress_tenant import claim, drain, planned
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def require_service_sql_ci(environment: dict[str, str]) -> None:
    expected = {
        "EM_TEST_ADMIN_DATABASE_URL": "postgresql+pg8000://postgres:emailmonitor-ci-only@127.0.0.1:5432/postgres",
        "EM_TEST_DATABASE_URL": "postgresql+pg8000://em_ci_runtime:emailmonitor-ci-runtime-only@127.0.0.1:5432/postgres",
        "EM_TEST_AUTH_DATABASE_URL": "postgresql+pg8000://em_ci_authenticator:emailmonitor-ci-auth-only@127.0.0.1:5432/postgres",
    }
    if any(not environment.get(key) for key in expected):
        if environment.get("EM_REQUIRE_REAL_BROKER") == "true":
            pytest.fail("Required disposable service SQL prerequisites unavailable")
        pytest.skip("Disposable service authority SQL unavailable")
    if environment.get("GITHUB_ACTIONS") != "true" or any(
        environment.get(key) != value for key, value in expected.items()
    ):
        raise RuntimeError("Exact disposable CI service authority targets required")


@pytest.fixture(autouse=True)
def _service_ci_guard() -> None:
    # Autouse runs before the Scenario fixture creates any synthetic SQL state.
    # In particular, role-attribute mutation tests must never target other systems.
    require_service_sql_ci(dict(os.environ))


@dataclass
class ServiceCase:
    admin: Engine
    database: ServiceDatabase
    progress: Progress
    scope: ServiceWork
    principal: UUID
    grant: UUID
    url: str


@pytest.fixture
def service_case(scenario: Scenario) -> Iterator[ServiceCase]:
    progress, job = planned(scenario)
    org = scenario.organizations[0]
    progress.start(org, job, progress.snapshot(org, job).revision)
    admin = create_engine(scenario.admin_url)
    name = "em_service_test_" + uuid4().hex
    principal = uuid4()
    url = (
        make_url(scenario.admin_url)
        .set(username=name, password="authored-disposable-service-only")
        .render_as_string(hide_password=False)
    )
    database: ServiceDatabase | None = None
    try:
        with admin.begin() as c:
            # Generated closed identifier and authored disposable password only.
            c.exec_driver_sql(
                f"CREATE ROLE {name} LOGIN NOSUPERUSER NOBYPASSRLS "
                "PASSWORD 'authored-disposable-service-only'"
            )
            c.exec_driver_sql(f"GRANT emailmonitor_worker TO {name}")
            c.execute(
                text(
                    "INSERT INTO emailmonitor.service_principals"
                    "(id,organization_id,login_oid,login_name,kind,active) "
                    "SELECT :id,:org,oid,rolname,'worker',true FROM pg_roles WHERE rolname=:name"
                ),
                {"id": principal, "org": org, "name": name},
            )
        with progress.database.tenant(progress.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
            grant: UUID = c.execute(
                text(
                    "SELECT emailmonitor.delegate_service_work("
                    ":org,:principal,:job,'extraction',21600)"
                ),
                {"org": org, "principal": principal, "job": job},
            ).scalar_one()
        database = ServiceDatabase(url, ServiceProcess(kind="worker", principal=principal))
        scope = ServiceWork(organization=org, resource=job, purpose="extraction", generation=1)
        yield ServiceCase(admin, database, progress, scope, principal, grant, url)
    finally:
        if database is not None:
            database.engine.dispose()
        with admin.begin() as c:
            for table in ("admission_requests", "source_resource_requests"):
                c.execute(
                    text(
                        f"DELETE FROM emailmonitor.{table} WHERE service_delegation IN "
                        "(SELECT id FROM emailmonitor.service_delegations WHERE principal_id=:id)"
                    ),
                    {"id": principal},
                )
            c.execute(
                text("DELETE FROM emailmonitor.service_audit WHERE principal_id=:id"),
                {"id": principal},
            )
            c.execute(
                text("DELETE FROM emailmonitor.service_delegations WHERE principal_id=:id"),
                {"id": principal},
            )
            c.execute(
                text("DELETE FROM emailmonitor.service_principals WHERE id=:id"),
                {"id": principal},
            )
            c.exec_driver_sql(f"DROP ROLE IF EXISTS {name}")
        admin.dispose()


def test_service_real_login_scope_and_human_pool_separation(service_case: ServiceCase) -> None:
    case = service_case
    with case.database.tenant(case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE) as (
        c,
        context,
    ):
        assert context.delegation_id == case.grant
        assert context.principal_id == case.principal
        assert (
            c.execute(text("SELECT current_setting('emailmonitor.session_hash',true)")).scalar_one()
            == ""
        )
    with pytest.raises(ValueError):
        Database(case.url)
    with pytest.raises(AuthorizationDenied):
        with case.database.tenant(
            case.progress.token, case.scope.organization, Capability.ACQUIRE_SOURCE
        ):
            raise AssertionError("Human session accepted by service pool")
    with pytest.raises(AuthorizationDenied):
        with case.progress.database.tenant(
            case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE
        ):
            raise AssertionError("Service scope accepted by human pool")


def test_service_real_natural_expiry_then_explicit_origin_revocation(
    service_case: ServiceCase,
) -> None:
    case = service_case
    assert isinstance(case.progress.token, str)
    with case.admin.begin() as c:
        c.execute(
            text(
                "UPDATE emailmonitor.sessions SET expires_at=clock_timestamp()-interval '1 second' "
                "WHERE token_hash=:token"
            ),
            {"token": digest(case.progress.token)},
        )
    with case.database.tenant(case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE):
        pass
    with pytest.raises(AuthorizationDenied):
        with case.progress.database.tenant(
            case.progress.token, case.scope.organization, Capability.READ_ORGANIZATION
        ):
            raise AssertionError("Expired human session accepted")
    with case.admin.begin() as c:
        c.execute(
            text(
                "UPDATE emailmonitor.sessions SET revoked_at=clock_timestamp() "
                "WHERE token_hash=:token"
            ),
            {"token": digest(case.progress.token)},
        )
    with pytest.raises(AuthorizationDenied):
        with case.database.tenant(case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE):
            raise AssertionError("Explicitly revoked origin authorized service")


@pytest.mark.parametrize("change", ["organization", "resource", "purpose", "generation"])
def test_service_real_forged_scope_and_rolled_back_pool(
    service_case: ServiceCase, change: str
) -> None:
    case = service_case
    data = case.scope.model_dump()
    data[change] = 2 if change == "generation" else "export" if change == "purpose" else uuid4()
    altered = ServiceWork.model_validate(data)
    with pytest.raises(AuthorizationDenied):
        with case.database.tenant(
            altered,
            altered.organization,
            Capability.EXPORT_RESULTS if change == "purpose" else Capability.ACQUIRE_SOURCE,
        ):
            raise AssertionError("Forged service scope accepted")
    with case.database.tenant(case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE):
        pass


def test_service_real_no_direct_authority_or_human_management_access(
    service_case: ServiceCase,
) -> None:
    case = service_case
    for statement in (
        "SELECT * FROM emailmonitor.sessions",
        "SELECT * FROM emailmonitor.service_delegations",
        "SELECT * FROM emailmonitor.memberships",
        "SELECT emailmonitor.resolve_session('')",
        "SELECT emailmonitor.establish_session('','','','')",
        "SET ROLE emailmonitor_runtime",
        "SET ROLE emailmonitor_authenticator",
        "SET ROLE emailmonitor_owner",
    ):
        with pytest.raises(DBAPIError):
            with case.database.engine.begin() as c:
                c.execute(text(statement))


def test_service_real_principal_disable_enable_never_revives_delegation(
    service_case: ServiceCase,
) -> None:
    case = service_case
    with case.admin.begin() as c:
        for active in (False, True):
            c.execute(
                text("UPDATE emailmonitor.service_principals SET active=:active WHERE id=:id"),
                {"id": case.principal, "active": active},
            )
    with pytest.raises(AuthorizationDenied):
        with case.database.tenant(case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE):
            raise AssertionError("Reactivated principal revived stale delegation")


def test_service_real_duplicate_delegation_preserves_deadline(service_case: ServiceCase) -> None:
    case = service_case
    with case.admin.connect() as c:
        before: datetime = c.execute(
            text("SELECT deadline FROM emailmonitor.service_delegations WHERE id=:id"),
            {"id": case.grant},
        ).scalar_one()
    with case.progress.database.tenant(
        case.progress.token, case.scope.organization, Capability.ACQUIRE_SOURCE
    ) as (c, _):
        again: UUID = c.execute(
            text(
                "SELECT emailmonitor.delegate_service_work(:org,:principal,:job,'extraction',21600)"
            ),
            {
                "org": case.scope.organization,
                "principal": case.principal,
                "job": case.scope.resource,
            },
        ).scalar_one()
    assert again == case.grant
    with case.admin.connect() as c:
        assert (
            c.execute(
                text("SELECT deadline FROM emailmonitor.service_delegations WHERE id=:id"),
                {"id": case.grant},
            ).scalar_one()
            == before
        )
    with pytest.raises(DBAPIError):
        with case.admin.begin() as c:
            c.execute(
                text(
                    "UPDATE emailmonitor.service_delegations "
                    "SET deadline=deadline+interval '1 second' WHERE id=:id"
                ),
                {"id": case.grant},
            )


def test_service_real_extraction_without_human_session_and_current_logout_fence(
    service_case: ServiceCase,
) -> None:
    case = service_case
    with case.admin.begin() as c:
        c.execute(
            text(
                "UPDATE emailmonitor.sessions SET expires_at=clock_timestamp()-interval '1 second' "
                "WHERE token_hash=:token"
            ),
            {"token": digest(case.progress.token)},
        )
    worker = Progress(case.database, case.scope, SETTINGS)
    drain(worker, case.scope.organization, case.scope.resource)
    snapshot = worker.snapshot(case.scope.organization, case.scope.resource)
    assert snapshot.state == "completed_partial"
    assert snapshot.counts.discovered == snapshot.counts.terminal == 4
    assert snapshot.counts.by_outcome["no_contact"] == 1
    with case.admin.connect() as c:
        audits = c.execute(
            text(
                "SELECT a.action,count(*),bool_and(a.actor_id=d.initiator_id) "
                "FROM emailmonitor.audit_events a JOIN emailmonitor.service_delegations d "
                "ON d.organization_id=a.organization_id AND d.resource_id=a.resource_id "
                "WHERE d.id=:grant AND a.action IN "
                "('discovery.page_committed','extraction.observation_committed') "
                "GROUP BY a.action"
            ),
            {"grant": case.grant},
        ).all()
    assert {row[0]: (row[1], row[2]) for row in audits} == {
        "discovery.page_committed": (2, True),
        "extraction.observation_committed": (4, True),
    }
    with pytest.raises(AuthorizationDenied):
        worker.control(case.scope.organization, case.scope.resource, snapshot.revision, "resume")


@pytest.mark.parametrize(
    "action",
    [
        "discovery.planned",
        "discovery.page_committed",
        "discovery.delivery.received",
        "extraction.observation_committed",
    ],
)
def test_human_work_audit_preserves_event_and_resource_semantics(
    service_case: ServiceCase, action: str
) -> None:
    case = service_case
    # A delivery receipt intentionally identifies an event rather than its job.
    resource = uuid4() if action == "discovery.delivery.received" else case.scope.resource
    identifier = uuid4()
    with case.progress.database.tenant(
        case.progress.token, case.scope.organization, Capability.ACQUIRE_SOURCE
    ) as (c, context):
        assert isinstance(context, TenantContext)
        c.execute(
            text("SELECT emailmonitor.work_audit(:org,:resource,:action,:id)"),
            {
                "org": case.scope.organization,
                "resource": resource,
                "action": action,
                "id": identifier,
            },
        )
        row = c.execute(
            text(
                "SELECT actor_id,action,resource_id FROM emailmonitor.audit_events "
                "WHERE organization_id=:org AND id=:id"
            ),
            {"org": case.scope.organization, "id": identifier},
        ).one()
        assert tuple(row) == (context.identity_id, action, resource)


@pytest.mark.parametrize("action", ["discovery.page_committed", "extraction.observation_committed"])
@pytest.mark.parametrize("condition", ["current", "missing", "stale", "wrong_resource"])
def test_service_real_audit_requires_current_exact_lease(
    service_case: ServiceCase, action: str, condition: str
) -> None:
    case = service_case
    worker = Progress(case.database, case.scope, SETTINGS)
    work = claim(worker, case.scope.organization, case.scope.resource)
    if condition == "stale":
        with case.admin.begin() as c:
            c.execute(
                text(
                    "UPDATE emailmonitor.execution_items SET "
                    "lease_until=clock_timestamp()-interval '1 second' "
                    "WHERE organization_id=:org AND job_id=:job AND id=:item"
                ),
                {
                    "org": case.scope.organization,
                    "job": case.scope.resource,
                    "item": work.lease.item,
                },
            )
    identifier = uuid4()
    resource = uuid4() if condition == "wrong_resource" else case.scope.resource
    with (
        bound(work.lease) if condition != "missing" else nullcontext(),
        pytest.raises(AuthorizationDenied) if condition != "current" else nullcontext(),
        case.database.tenant(case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE) as (
            c,
            _,
        ),
    ):
        c.execute(
            text("SELECT emailmonitor.work_audit(:org,:resource,:action,:id)"),
            {
                "org": case.scope.organization,
                "resource": resource,
                "action": action,
                "id": identifier,
            },
        )
    with case.admin.connect() as c:
        assert c.execute(
            text("SELECT count(*) FROM emailmonitor.audit_events WHERE id=:id"),
            {"id": identifier},
        ).scalar_one() == int(condition == "current")


@pytest.mark.parametrize(
    "action", [None, "discovery.planned", "discovery.delivery.received", "arbitrary.audit"]
)
def test_service_real_audit_refuses_actions_outside_commit_subset(
    service_case: ServiceCase, action: str | None
) -> None:
    case = service_case
    worker = Progress(case.database, case.scope, SETTINGS)
    work = claim(worker, case.scope.organization, case.scope.resource)
    with (
        bound(work.lease),
        pytest.raises(AuthorizationDenied),
        case.database.tenant(case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE) as (
            c,
            _,
        ),
    ):
        c.execute(
            text("SELECT emailmonitor.work_audit(:org,:resource,:action,:id)"),
            {
                "org": case.scope.organization,
                "resource": case.scope.resource,
                "action": action,
                "id": uuid4(),
            },
        )


def test_service_real_logout_after_observation_prevents_association_and_effect(
    service_case: ServiceCase,
) -> None:
    case = service_case
    worker = Progress(case.database, case.scope, SETTINGS)
    worker.process_fixture(claim(worker, case.scope.organization, case.scope.resource))
    work = claim(worker, case.scope.organization, case.scope.resource, kind="article")

    def logout() -> None:
        with case.admin.begin() as c:
            c.execute(
                text(
                    "UPDATE emailmonitor.sessions SET revoked_at=clock_timestamp() "
                    "WHERE token_hash=:token"
                ),
                {"token": digest(case.progress.token)},
            )

    with pytest.raises(AuthorizationDenied):
        worker.process_fixture(work, after_observation=logout)
    with case.admin.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.association_batches "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": case.scope.organization, "job": case.scope.resource},
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize("role", ["owner", "owner_b"])
def test_service_real_known_human_hash_cannot_escape_service_login(
    service_case: ServiceCase, scenario: Scenario, role: str
) -> None:
    from emailmonitor.identity.foundation import COOKIE

    case = service_case
    with scenario.client() as client:
        scenario.login(client, role)
        token = str(client.cookies[COOKIE])
    org = scenario.organizations[1 if role == "owner_b" else 0]
    if role == "owner_b":
        tenant_b = replace(
            scenario,
            organizations=(scenario.organizations[1], scenario.organizations[0]),
            identities={**scenario.identities, "owner": scenario.identities["owner_b"]},
        )
        other, job = planned(tenant_b)
        other.start(org, job, other.snapshot(org, job).revision)
    else:
        job = case.scope.resource
    for function in ("execution_read_fence", "work_job_lock", "job_permission_fence"):
        with pytest.raises(DBAPIError):
            with case.database.engine.begin() as c:
                c.execute(
                    text(
                        "SELECT set_config('emailmonitor.session_hash',:token,true), "
                        "set_config('emailmonitor.organization_id',:org,true), "
                        "set_config('emailmonitor.service_delegation','',true)"
                    ),
                    {"token": digest(token), "org": str(org)},
                )
                c.execute(
                    text(f"SELECT emailmonitor.{function}(:org,:job)"),
                    {"org": org, "job": job},
                )


def test_service_real_unleased_discovery_mutation_denied(service_case: ServiceCase) -> None:
    case = service_case
    with pytest.raises(AuthorizationDenied):
        with case.database.tenant(
            case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE
        ) as (c, _):
            c.execute(
                text("SELECT emailmonitor.work_discovery_complete(:org,:job)"),
                {"org": case.scope.organization, "job": case.scope.resource},
            )
    with pytest.raises(AuthorizationDenied):
        with case.database.tenant(
            case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE
        ) as (c, _):
            c.execute(
                text("UPDATE emailmonitor.jobs SET discovery_complete=true WHERE id=:job"),
                {"job": case.scope.resource},
            )


def test_service_real_export_separate_scope_and_exact_snapshot(service_case: ServiceCase) -> None:
    from emailmonitor.results.models import ExportInput
    from emailmonitor.results.service import Results

    case = service_case
    org, job = case.scope.organization, case.scope.resource
    drain(case.progress, org, job)
    human = Results(case.progress.database, case.progress.token, SETTINGS)
    request = ExportInput.model_validate(
        {
            "job_id": str(job),
            "format": "xlsx",
            "purpose": "academic_contact_research",
        }
    )
    first = human.create(org, request, str(uuid4()))
    other = human.create(org, request, str(uuid4()))
    with case.progress.database.tenant(case.progress.token, org, Capability.EXPORT_RESULTS) as (
        c,
        _,
    ):
        c.execute(
            text("SELECT emailmonitor.delegate_service_work(:org,:principal,:id,'export',21600)"),
            {"org": org, "principal": case.principal, "id": first.id},
        )
    scope = ServiceWork(organization=org, resource=first.id, purpose="export", generation=1)
    worker = Results(case.database, scope, SETTINGS)
    pending = next(row for row in human.pending(org) if row["export_id"] == first.id)
    # Even a valid separate export may not be selected through the first grant.
    with pytest.raises(AuthorizationDenied):
        worker.claim(org, other.id, uuid4(), 1)
    with case.database.tenant(scope, org, Capability.EXPORT_RESULTS) as (c, _):
        for table in (
            "article_observations",
            "association_candidates",
            "author_email_associations",
        ):
            assert c.execute(text(f"SELECT count(*) FROM emailmonitor.{table}")).scalar_one() == 0
    with case.admin.begin() as c:
        c.execute(
            text(
                "UPDATE emailmonitor.sessions SET expires_at=clock_timestamp()-interval '1 second' "
                "WHERE token_hash=:token"
            ),
            {"token": digest(case.progress.token)},
        )
    lease = worker.claim(org, first.id, UUID(str(pending["event_id"])), 1)
    assert lease is not None
    assert worker.process(lease)
    assert worker.claim(org, first.id, UUID(str(pending["event_id"])), 1) is None
    with case.admin.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT state FROM emailmonitor.exports WHERE organization_id=:org AND id=:id"
                ),
                {"org": org, "id": first.id},
            ).scalar_one()
            == "ready"
        )
    # Worker authority never grants human download or artifact-table access.
    with pytest.raises(AuthorizationDenied):
        worker.download(org, first.id)
    with pytest.raises(AuthorizationDenied):
        with case.database.tenant(scope, org, Capability.EXPORT_RESULTS) as (c, _):
            c.execute(text("SELECT body FROM emailmonitor.export_artifacts"))


def test_service_real_legacy_restore_refuses_authority_without_revocation_seal(
    service_case: ServiceCase,
    scenario: Scenario,
) -> None:
    from restore_exercise import RestoreRefused, capture

    with pytest.raises(RestoreRefused, match="restore_service_authority_unsupported"):
        capture(service_case.admin, scenario.organizations)


@pytest.mark.parametrize("contention", ["fast_release", "timeout", "expiry"])
def test_service_export_claim_has_sql_bounded_wait_and_post_wait_fence(
    service_case: ServiceCase, contention: str
) -> None:
    import time
    from concurrent.futures import ThreadPoolExecutor

    from emailmonitor.results.models import ExportInput
    from emailmonitor.results.service import Results

    case = service_case
    org, job = case.scope.organization, case.scope.resource
    drain(case.progress, org, job)
    human = Results(case.progress.database, case.progress.token, SETTINGS)
    item = human.create(
        org,
        ExportInput.model_validate(
            {"job_id": str(job), "format": "xlsx", "purpose": "academic_contact_research"}
        ),
        str(uuid4()),
    )
    event = next(row for row in human.pending(org) if row["export_id"] == item.id)
    with case.progress.database.tenant(case.progress.token, org, Capability.EXPORT_RESULTS) as (
        c,
        _,
    ):
        c.execute(
            text(
                "SELECT emailmonitor.delegate_service_work(:org,:principal,:id,'export',:seconds)"
            ),
            {
                "org": org,
                "principal": case.principal,
                "id": item.id,
                "seconds": 5 if contention == "expiry" else 30,
            },
        )
    scope = ServiceWork(organization=org, resource=item.id, purpose="export", generation=1)

    sqlstates: list[str] = []

    def attempt() -> object:
        with case.database.tenant(scope, org, Capability.EXPORT_RESULTS) as (c, _):
            # Direct granted RPC callers must not remove the server-side wait cap.
            c.execute(text("SET LOCAL lock_timeout='0'"))
            try:
                return c.execute(
                    text("SELECT emailmonitor.exports_claim(:org,:id,:event,1,:nonce,30)"),
                    {"org": org, "id": item.id, "event": event["event_id"], "nonce": uuid4()},
                ).scalar_one()
            except DBAPIError as error:
                assert error.orig is not None
                detail = error.orig.args[0]
                assert isinstance(detail, dict)
                sqlstates.append(str(detail.get("C")))
                raise

    with ThreadPoolExecutor(max_workers=1) as executor, case.admin.connect() as holder:
        transaction = holder.begin()
        try:
            holder.execute(
                text("SELECT id FROM emailmonitor.exports WHERE id=:id FOR SHARE"),
                {"id": item.id},
            )
            if contention == "expiry":
                remaining: object = holder.execute(
                    text(
                        "SELECT extract(epoch FROM deadline-clock_timestamp()) "
                        "FROM emailmonitor.service_delegations WHERE principal_id=:principal "
                        "AND resource_id=:id AND purpose='export'"
                    ),
                    {"principal": case.principal, "id": item.id},
                ).scalar_one()
                assert float(str(remaining)) > 1.0
                time.sleep(float(str(remaining)) - 0.8)
            started = time.monotonic()
            future = executor.submit(attempt)
            # Prove the worker reached the contended lock, rather than merely
            # assuming a sleep gave the subprocess/thread enough time to begin.
            while time.monotonic() - started < 0.8:
                with case.admin.connect() as observer:
                    waiting: int = observer.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE usename=:name "
                            "AND wait_event_type='Lock'"
                        ),
                        {"name": make_url(case.url).username},
                    ).scalar_one()
                if waiting:
                    break
                assert not future.done()
                time.sleep(0.01)
            assert waiting == 1
            if contention == "timeout":
                with pytest.raises(AuthorizationDenied):
                    future.result(timeout=4)
                assert time.monotonic() - started < 3.5
            else:
                if contention == "expiry":
                    time.sleep(1.1)
                transaction.commit()
                if contention == "expiry":
                    with pytest.raises(AuthorizationDenied):
                        future.result(timeout=3)
                else:
                    assert future.result(timeout=3) is not None
        finally:
            if transaction.is_active:
                transaction.rollback()

    if contention != "fast_release":
        assert sqlstates == ["EM017" if contention == "expiry" else "55P03"]
        with case.admin.connect() as c:
            state = c.execute(
                text("SELECT state,attempts FROM emailmonitor.exports WHERE id=:id"),
                {"id": item.id},
            ).one()
            assert tuple(state) == ("queued", 0)
            for table, column in (
                ("admission_requests", "reference_id"),
                ("export_artifacts", "export_id"),
            ):
                assert (
                    c.execute(
                        text(f"SELECT count(*) FROM emailmonitor.{table} WHERE {column}=:id"),
                        {"id": item.id},
                    ).scalar_one()
                    == 0
                )


@pytest.mark.parametrize("flag", ["CREATEROLE", "CREATEDB", "REPLICATION"])
def test_service_real_excess_login_privilege_refuses_new_and_existing_pool(
    service_case: ServiceCase, flag: str
) -> None:
    case = service_case
    name = make_url(case.url).username
    assert name is not None and name.startswith("em_service_test_")
    assert flag in {"CREATEROLE", "CREATEDB", "REPLICATION"}
    with case.admin.begin() as c:
        c.exec_driver_sql(f"ALTER ROLE {name} {flag}")
    with pytest.raises(ValueError, match="Isolated non-owner service database login required"):
        ServiceDatabase(case.url, ServiceProcess(kind="worker", principal=case.principal))
    with pytest.raises(AuthorizationDenied):
        with case.database.tenant(case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE):
            pytest.fail("A pre-existing pool must not retain excess login authority")


def test_reference_service_unsupported_provider_start_rolls_back_atomically(
    scenario: Scenario,
) -> None:
    from emailmonitor.runtime.delegation import ServiceBinding, ServiceBindings
    from test_provider_journey_tenant import planned_provider

    progress, job = planned_provider(scenario)
    org = scenario.organizations[0]
    before = progress.snapshot(org, job)
    bound = Progress(
        progress.database,
        progress.token,
        SETTINGS,
        bindings=ServiceBindings(
            tenants=(ServiceBinding(organization=org, worker=uuid4(), publisher=uuid4()),)
        ),
    )
    with pytest.raises(AuthorizationDenied):
        bound.start(org, job, before.revision)
    after = progress.snapshot(org, job)
    assert (after.state, after.revision) == (before.state, before.revision)
    admin = create_engine(scenario.admin_url)
    try:
        with admin.connect() as c:
            for table in ("execution_runs", "execution_outbox"):
                assert (
                    c.execute(
                        text(f"SELECT count(*) FROM emailmonitor.{table} WHERE job_id=:job"),
                        {"job": job},
                    ).scalar_one()
                    == 0
                )
            assert (
                c.execute(
                    text(
                        "SELECT count(*) FROM emailmonitor.service_delegations "
                        "WHERE resource_id=:job"
                    ),
                    {"job": job},
                ).scalar_one()
                == 0
            )
    finally:
        admin.dispose()


def test_service_real_direct_authenticator_privilege_invalidates_existing_pool(
    service_case: ServiceCase,
) -> None:
    case = service_case
    name = make_url(case.url).username
    assert name is not None and name.startswith("em_service_test_")
    function = "emailmonitor.establish_session(text,text,text,text)"
    try:
        with case.admin.begin() as c:
            c.exec_driver_sql(f"GRANT EXECUTE ON FUNCTION {function} TO {name}")
        with pytest.raises(ValueError, match="Isolated non-owner service database login required"):
            ServiceDatabase(case.url, ServiceProcess(kind="worker", principal=case.principal))
        with pytest.raises(AuthorizationDenied):
            with case.database.tenant(
                case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE
            ):
                pytest.fail("Existing service pool retained session-minting privilege")
    finally:
        with case.admin.begin() as c:
            c.exec_driver_sql(f"REVOKE EXECUTE ON FUNCTION {function} FROM {name}")


@pytest.mark.parametrize("path", ["expected_group", "custom_group_set_false"])
def test_service_real_indirect_privilege_change_invalidates_open_pool(
    service_case: ServiceCase, path: str
) -> None:
    case = service_case
    name = make_url(case.url).username
    assert name is not None and name.startswith("em_service_test_")
    role = "emailmonitor_worker" if path == "expected_group" else "em_privilege_test_" + uuid4().hex
    changed = False
    try:
        with case.admin.begin() as c:
            if path == "expected_group":
                assert not c.execute(
                    text("SELECT rolcreatedb FROM pg_roles WHERE rolname=:role"), {"role": role}
                ).scalar_one()
                c.exec_driver_sql(f"ALTER ROLE {role} CREATEDB")
            else:
                c.exec_driver_sql(f"CREATE ROLE {role} NOLOGIN CREATEDB")
                # Even a currently non-settable path is refused; ADMIN may allow
                # its holder to change options later. No such upgrade is performed.
                c.exec_driver_sql(f"GRANT {role} TO {name} WITH ADMIN TRUE, SET FALSE")
        changed = True
        with pytest.raises(ValueError, match="Isolated non-owner service database login required"):
            ServiceDatabase(case.url, ServiceProcess(kind="worker", principal=case.principal))
        with pytest.raises(AuthorizationDenied):
            with case.database.tenant(
                case.scope, case.scope.organization, Capability.ACQUIRE_SOURCE
            ):
                pytest.fail("Existing service pool retained indirect administrative authority")
    finally:
        if changed:
            with case.admin.begin() as c:
                if path == "expected_group":
                    c.exec_driver_sql(f"ALTER ROLE {role} NOCREATEDB")
                else:
                    c.exec_driver_sql(f"DROP ROLE IF EXISTS {role}")

"""Actual fresh/0013 upgrade checks in owned disposable CI databases only.

The normal CI database and cluster role memberships are never changed. Missing
explicit CI restore context skips SQL acceptance, rather than simulating it.
"""

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from emailmonitor.organizations.database import digest
from restore_exercise import ADMIN, RUNTIME, RestoreRefused, capture, require_ci
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from test_source_foundation import policy_body

ROOT = Path(__file__).resolve().parents[3]
HEAD = "0015_service_plan_cache"
SERVICE_PREVIOUS = "0014_service_authority"
PREVIOUS = "0013_provider_journey"
AUTHORITY_TABLES = ("service_principals", "service_delegations", "service_audit")
HISTORY_TABLES = (
    "organizations",
    "identities",
    "memberships",
    "sessions",
    "source_catalog",
    "source_policy_heads",
    "source_policies",
    "jobs",
    "job_items",
    "job_outbox",
    "exports",
    "export_outbox",
    "admission_requests",
    "source_resource_requests",
    "lifecycle_job_deadlines",
    "deletion_tombstones",
    "tenant_configuration",
)

# OIDs, relfilenodes, planner statistics and database names are intentionally
# excluded. Definitions, owners, explicit ACLs (including column ACLs), policies,
# indexes and triggers are compared, not just the Alembic revision string.
CATALOG_QUERIES = {
    "schemas": """
        SELECT nspname,pg_get_userbyid(nspowner),nspacl::text FROM pg_namespace
        WHERE nspname='emailmonitor' ORDER BY nspname
    """,
    "relations": """
        SELECT c.relname,c.relkind,pg_get_userbyid(c.relowner),c.relrowsecurity,
        c.relforcerowsecurity,c.relacl::text,c.reloptions
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='emailmonitor' ORDER BY c.relname
    """,
    "columns": """
        SELECT c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),
        a.attnotnull,a.attidentity,a.attgenerated,a.attacl::text,
        pg_get_expr(d.adbin,d.adrelid)
        FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
        WHERE n.nspname='emailmonitor' AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY c.relname,a.attnum
    """,
    "constraints": """
        SELECT c.relname,k.conname,k.contype,pg_get_constraintdef(k.oid,true),
        k.convalidated,k.condeferrable,k.condeferred
        FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='emailmonitor' ORDER BY c.relname,k.conname
    """,
    "indexes": """
        SELECT tablename,indexname,indexdef FROM pg_indexes
        WHERE schemaname='emailmonitor' ORDER BY tablename,indexname
    """,
    "functions": """
        SELECT p.proname,pg_get_function_identity_arguments(p.oid),
        pg_get_userbyid(p.proowner),p.proacl::text,p.prosecdef,p.proconfig,
        pg_get_functiondef(p.oid)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='emailmonitor'
        ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)
    """,
    "policies": """
        SELECT tablename,policyname,permissive,roles,cmd,qual,with_check
        FROM pg_policies WHERE schemaname='emailmonitor'
        ORDER BY tablename,policyname
    """,
    "triggers": """
        SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid,true)
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='emailmonitor' AND NOT t.tgisinternal
        ORDER BY c.relname,t.tgname
    """,
    "default_acls": """
        SELECT pg_get_userbyid(d.defaclrole),n.nspname,d.defaclobjtype,d.defaclacl::text
        FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace
        WHERE n.nspname='emailmonitor' OR d.defaclnamespace=0
        ORDER BY 1,2,3
    """,
    "revision_acl": """
        SELECT pg_get_userbyid(c.relowner),c.relacl::text FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname='alembic_version'
    """,
}


def target_name(value: str) -> str:
    if re.fullmatch(r"em_service_migration_[a-f0-9]{32}", value) is None:
        raise ValueError("Owned disposable migration database required")
    return value


def engine(url: str, *, autocommit: bool = False) -> Engine:
    return create_engine(
        url,
        isolation_level="AUTOCOMMIT" if autocommit else "READ COMMITTED",
        pool_size=1,
        max_overflow=0,
        pool_timeout=3,
        connect_args={"timeout": 5},
        hide_parameters=True,
    )


def rows(c: Connection, statement: str) -> list[tuple[object, ...]]:
    return [tuple(row) for row in c.execute(text(statement))]


def cluster_authority(c: Connection) -> dict[str, list[tuple[object, ...]]]:
    return {
        "roles": rows(
            c,
            "SELECT rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,"
            "rolreplication,rolbypassrls,rolconnlimit,rolvaliduntil,rolconfig "
            "FROM pg_roles ORDER BY rolname",
        ),
        "memberships": rows(
            c,
            "SELECT role.rolname,member.rolname,grantor.rolname,m.admin_option,"
            "m.inherit_option,m.set_option FROM pg_auth_members m "
            "JOIN pg_roles role ON role.oid=m.roleid "
            "JOIN pg_roles member ON member.oid=m.member "
            "JOIN pg_roles grantor ON grantor.oid=m.grantor ORDER BY 1,2,3",
        ),
    }


@dataclass(frozen=True)
class OwnedDatabase:
    name: str
    marker: str
    admin: Engine

    @property
    def url(self) -> str:
        return (
            make_url(ADMIN)
            .set(database=target_name(self.name))
            .render_as_string(hide_password=False)
        )

    def verify(self, c: Connection) -> None:
        row = c.execute(
            text(
                "SELECT pg_get_userbyid(datdba),shobj_description(oid,'pg_database') "
                "FROM pg_database WHERE datname=:name"
            ),
            {"name": target_name(self.name)},
        ).one_or_none()
        if row != ("postgres", self.marker):
            raise RuntimeError("Disposable migration database ownership mismatch")

    def migrate(self, revision: str) -> None:
        assert revision in (PREVIOUS, SERVICE_PREVIOUS, HEAD)
        with self.admin.connect() as c:
            self.verify(c)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(ROOT / "services/backend/alembic.ini"),
                "upgrade",
                revision,
            ],
            cwd=ROOT,
            env={**os.environ, "EM_MIGRATION_DATABASE_URL": self.url},
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        # Never publish connection strings or SQL parameter dumps on a failure.
        assert result.returncode == 0, f"Disposable Alembic upgrade to {revision} failed"


@contextmanager
def owned_database(admin: Engine) -> Iterator[OwnedDatabase]:
    target = OwnedDatabase(
        target_name("em_service_migration_" + uuid4().hex),
        "emailmonitor-service-migration-" + uuid4().hex,
        admin,
    )
    attempted = False
    try:
        with admin.connect() as c:
            assert (
                c.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname=:name"),
                    {"name": target.name},
                ).scalar_one()
                == 0
            )
            attempted = True
            c.exec_driver_sql(
                f'CREATE DATABASE "{target.name}" TEMPLATE template0 CONNECTION LIMIT 0'
            )
            c.exec_driver_sql(f"""COMMENT ON DATABASE "{target.name}" IS '{target.marker}'""")
            target.verify(c)
            c.exec_driver_sql(
                f'REVOKE ALL ON DATABASE "{target.name}" '
                "FROM PUBLIC,em_ci_runtime,em_ci_authenticator"
            )
        yield target
    finally:
        if attempted:
            with admin.connect() as c:
                exists: int = c.execute(
                    text("SELECT count(*) FROM pg_database WHERE datname=:name"),
                    {"name": target.name},
                ).scalar_one()
                if exists:
                    # An ambiguous CREATE without the exact marker is not enough
                    # authority to delete a database. Fail rather than guessing.
                    target.verify(c)
                    c.exec_driver_sql(f'DROP DATABASE "{target.name}" WITH (FORCE)')
                assert (
                    c.execute(
                        text("SELECT count(*) FROM pg_database WHERE datname=:name"),
                        {"name": target.name},
                    ).scalar_one()
                    == 0
                )


def history(c: Connection) -> dict[str, list[tuple[object, ...]]]:
    return {
        # Only 0014's deliberately new nullable authority column is normalized.
        # Its absence of backfill is separately asserted after the migration.
        table: rows(
            c,
            "SELECT "
            + (
                "(to_jsonb(t)-'service_delegation')::text"
                if table in ("admission_requests", "source_resource_requests")
                else "row_to_json(t)::text"
            )
            + f" FROM emailmonitor.{table} t ORDER BY 1",
        )
        for table in HISTORY_TABLES
    }


@dataclass(frozen=True)
class History:
    organizations: tuple[UUID, UUID]
    tokens: tuple[str, str]
    visible_jobs: tuple[UUID, UUID]
    tombstoned_jobs: tuple[UUID, UUID]


def populate_legacy(c: Connection) -> History:
    """Author valid 0013 rows without importing a post-0013 application writer."""
    organizations = (uuid4(), uuid4())
    tokens = (uuid4().hex + uuid4().hex, uuid4().hex + uuid4().hex)
    visible_jobs = (uuid4(), uuid4())
    tombstoned_jobs = (uuid4(), uuid4())
    for org, token, job, draft in zip(
        organizations, tokens, visible_jobs, tombstoned_jobs, strict=True
    ):
        actor, item, export = (uuid4() for _ in range(3))
        params: dict[str, object] = {
            "org": org,
            "actor": actor,
            "token": digest(token),
            "job": job,
            "draft": draft,
            "item": item,
            "export": export,
            "subject": str(actor),
            "policy": json.dumps(policy_body()),
        }
        for statement in (
            "INSERT INTO emailmonitor.identities(id,issuer,subject) "
            "VALUES(:actor,'https://migration.example.test',:subject)",
            "INSERT INTO emailmonitor.organizations(id,display_name,status,region) "
            "VALUES(:org,'Synthetic migration tenant','active','test-only')",
            "INSERT INTO emailmonitor.memberships VALUES(:org,:actor,'owner','active',1)",
            "INSERT INTO emailmonitor.sessions(token_hash,csrf_hash,identity_id,"
            "permission_revision,expires_at) "
            "VALUES(:token,:token,:actor,1,clock_timestamp()+interval '1 hour')",
            "SELECT set_config('emailmonitor.session_hash',:token,true),"
            "set_config('emailmonitor.organization_id',CAST(:org AS text),true)",
            "INSERT INTO emailmonitor.source_policy_heads(organization_id,source_id) "
            "VALUES(:org,'synthetic-publisher')",
            "INSERT INTO emailmonitor.source_policies(organization_id,source_id,version,state,"
            "policy,created_by,valid_until) VALUES(:org,'synthetic-publisher',1,'pending_review',"
            "CAST(:policy AS jsonb),:actor,(CAST(:policy AS jsonb)->>'valid_until')::timestamptz)",
            "UPDATE emailmonitor.source_policy_heads SET current_version=1 "
            "WHERE organization_id=:org",
            "UPDATE emailmonitor.source_policies SET state='approved',reviewed_by=:actor,"
            "approved_at=clock_timestamp() WHERE organization_id=:org",
            "INSERT INTO emailmonitor.jobs(organization_id,id,created_by,kind,request,"
            "source_id,policy_version,state) VALUES(:org,:job,:actor,'fixture_probe',"
            '\'{"purpose":"academic_contact_research"}\','
            "'synthetic-publisher',1,'queued')",
            "INSERT INTO emailmonitor.jobs(organization_id,id,created_by,kind,request,state) "
            "VALUES(:org,:draft,:actor,'extraction',"
            "'{\"purpose\":\"academic_contact_research\"}','draft')",
            "INSERT INTO emailmonitor.job_items(organization_id,job_id,id,input_digest,state) "
            "VALUES(:org,:job,:item,repeat('a',64),'pending')",
            "INSERT INTO emailmonitor.job_outbox(organization_id,event_id,job_id,item_id,"
            "generation,aggregate_version,event_type) "
            "VALUES(:org,gen_random_uuid(),:job,:item,1,1,'job.queued')",
            "INSERT INTO emailmonitor.exports(organization_id,id,requested_by,request,snapshot,"
            "state,reason,deletion_generation,policy_version,created_at,expires_at) "
            'VALUES(:org,:export,:actor,\'{"purpose":"academic_contact_research"}\','
            "'{\"synthetic\":\"migration-history\"}','queued','requested',1,1,"
            "statement_timestamp(),statement_timestamp()+interval '1 hour')",
            "INSERT INTO emailmonitor.export_outbox(organization_id,export_id,event_id,generation)"
            " VALUES(:org,:export,gen_random_uuid(),1)",
            "INSERT INTO emailmonitor.admission_requests(organization_id,id,pool,actor_id,"
            "session_hash,job_id,reference_id,generation,expires_at,state) "
            "VALUES(:org,gen_random_uuid(),'fixture_io',:actor,:token,:job,:item,1,"
            "clock_timestamp()+interval '5 minutes','waiting')",
            "INSERT INTO emailmonitor.source_resource_requests(organization_id,id,job_id,"
            "actor_id,session_hash,source_id,generation,deletion_generation,policy_version,"
            "operation,path,expires_at,state) "
            "VALUES(:org,gen_random_uuid(),:job,:actor,:token,'synthetic-publisher',1,1,1,"
            "'fetch_html','/article-a.html',clock_timestamp()+interval '5 minutes','waiting')",
            "INSERT INTO emailmonitor.deletion_tombstones(organization_id,id,job_id,reason) "
            "VALUES(:org,gen_random_uuid(),:draft,'owner_request')",
        ):
            c.execute(text(statement), params)
    return History(organizations, tokens, visible_jobs, tombstoned_jobs)


@dataclass(frozen=True)
class MigrationPair:
    fresh: OwnedDatabase
    upgraded: OwnedDatabase
    legacy: History
    before: dict[str, list[tuple[object, ...]]]
    roles: dict[str, list[tuple[object, ...]]]


def service_function_metadata(c: Connection) -> list[tuple[object, ...]]:
    """Replacement may change language/source, but no other function property."""
    return rows(
        c,
        """SELECT oid,proname,proowner,proacl::text,proargtypes::text,
prorettype,proretset,provolatile,prosecdef,proleakproof,proisstrict,proparallel,
procost,prorows,proconfig,proargnames FROM pg_proc WHERE oid IN (
'emailmonitor.service_delegation_current(uuid,uuid)'::regprocedure,
'emailmonitor.service_schema_ready()'::regprocedure) ORDER BY proname""",
    )


@pytest.fixture(scope="module")
def migration_pair() -> Iterator[MigrationPair]:
    if os.environ.get("EM_REQUIRE_SYNTHETIC_RESTORE") != "true":
        pytest.skip("Exact disposable PostgreSQL CI migration context is unavailable")
    require_ci(dict(os.environ))
    admin = engine(ADMIN, autocommit=True)
    try:
        with admin.connect() as c:
            assert c.execute(text("SHOW server_version_num")).scalar_one() == "170011"
            roles = cluster_authority(c)
        with ExitStack() as stack:
            fresh = stack.enter_context(owned_database(admin))
            upgraded = stack.enter_context(owned_database(admin))
            upgraded.migrate(PREVIOUS)
            database = engine(upgraded.url)
            try:
                with database.begin() as c:
                    assert (
                        c.execute(
                            text("SELECT version_num FROM public.alembic_version")
                        ).scalar_one()
                        == PREVIOUS
                    )
                    assert (
                        c.execute(
                            text("SELECT to_regclass('emailmonitor.service_principals')")
                        ).scalar_one()
                        is None
                    )
                    legacy = populate_legacy(c)
                    before = history(c)
                    assert all(before[table] for table in HISTORY_TABLES)
            finally:
                database.dispose()
            upgraded.migrate(SERVICE_PREVIOUS)
            # Keep one already-used physical connection across replacement. The
            # plan changes, but OIDs, permissions and live function results do not.
            database = engine(upgraded.url)
            try:
                with database.connect() as reused:
                    raw = reused.connection.dbapi_connection
                    metadata_before = service_function_metadata(reused)
                    for _ in range(6):
                        assert (
                            reused.execute(
                                text("SELECT emailmonitor.service_delegation_current(NULL,NULL)")
                            ).scalar_one()
                            is False
                        )
                    assert (
                        reused.execute(
                            text("SELECT emailmonitor.service_schema_ready()")
                        ).scalar_one()
                        is True
                    )
                    reused.commit()
                    upgraded.migrate(HEAD)
                    assert reused.connection.dbapi_connection is raw
                    assert service_function_metadata(reused) == metadata_before
                    assert (
                        reused.execute(
                            text("SELECT emailmonitor.service_delegation_current(NULL,NULL)")
                        ).scalar_one()
                        is False
                    )
                    assert (
                        reused.execute(
                            text("SELECT emailmonitor.service_schema_ready()")
                        ).scalar_one()
                        is True
                    )
                    assert (
                        reused.execute(
                            text(
                                "SELECT l.lanname FROM pg_proc p "
                                "JOIN pg_language l ON l.oid=p.prolang "
                                "WHERE p.oid="
                                "'emailmonitor.service_delegation_current(uuid,uuid)'::regprocedure"
                            )
                        ).scalar_one()
                        == "plpgsql"
                    )
            finally:
                database.dispose()
            fresh.migrate(HEAD)
            # Reapplication must be a no-op, including populated historical rows.
            upgraded.migrate(HEAD)
            fresh.migrate(HEAD)
            yield MigrationPair(fresh, upgraded, legacy, before, roles)
    finally:
        admin.dispose()


def test_actual_fresh_and_populated_upgrade_schema_acl_rls_equivalence(
    migration_pair: MigrationPair,
) -> None:
    snapshots: list[dict[str, list[tuple[object, ...]]]] = []
    for target in (migration_pair.fresh, migration_pair.upgraded):
        database = engine(target.url)
        try:
            with database.connect() as c:
                snapshots.append({key: rows(c, sql) for key, sql in CATALOG_QUERIES.items()})
                assert (
                    c.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
                    == HEAD
                )
                assert c.execute(text("SELECT emailmonitor.service_schema_ready()")).scalar_one()
                assert cluster_authority(c) == migration_pair.roles
                for table in AUTHORITY_TABLES:
                    assert (
                        c.execute(text(f"SELECT count(*) FROM emailmonitor.{table}")).scalar_one()
                        == 0
                    )
                assert rows(
                    c,
                    "SELECT rolname,rolcanlogin,rolsuper,rolbypassrls,rolcreaterole,"
                    "rolcreatedb,rolreplication FROM pg_roles "
                    "WHERE rolname IN ('emailmonitor_worker','emailmonitor_publisher') "
                    "ORDER BY rolname",
                ) == [
                    ("emailmonitor_publisher", False, False, False, False, False, False),
                    ("emailmonitor_worker", False, False, False, False, False, False),
                ]
                for role in (
                    "emailmonitor_runtime",
                    "emailmonitor_authenticator",
                    "emailmonitor_worker",
                    "emailmonitor_publisher",
                ):
                    for table in AUTHORITY_TABLES:
                        assert not c.execute(
                            text(
                                "SELECT has_table_privilege(:role,:table,"
                                "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')"
                            ),
                            {"role": role, "table": "emailmonitor." + table},
                        ).scalar_one()
                for role in ("emailmonitor_worker", "emailmonitor_publisher"):
                    assert not c.execute(
                        text(
                            "SELECT has_function_privilege(:role,"
                            "'emailmonitor.establish_session(text,text,text,text)','EXECUTE')"
                        ),
                        {"role": role},
                    ).scalar_one()
                    assert c.execute(
                        text(
                            "SELECT has_function_privilege(:role,"
                            "'emailmonitor.service_schema_ready()','EXECUTE')"
                        ),
                        {"role": role},
                    ).scalar_one()
                assert (
                    c.execute(
                        text(
                            "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                            "ON n.oid=c.relnamespace WHERE n.nspname='emailmonitor' "
                            "AND c.relname IN ('service_principals','service_delegations',"
                            "'service_audit') AND c.relrowsecurity AND c.relforcerowsecurity "
                            "AND pg_get_userbyid(c.relowner)='emailmonitor_owner'"
                        )
                    ).scalar_one()
                    == 3
                )
                assert not c.execute(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n "
                        "ON n.oid=p.pronamespace CROSS JOIN LATERAL "
                        "aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) acl "
                        "WHERE n.nspname='emailmonitor' AND acl.grantee=0 "
                        "AND acl.privilege_type='EXECUTE')"
                    )
                ).scalar_one()
                if target is migration_pair.upgraded:
                    assert history(c) == migration_pair.before
                    for table in ("admission_requests", "source_resource_requests"):
                        assert (
                            c.execute(
                                text(
                                    f"SELECT count(*) FROM emailmonitor.{table} "
                                    "WHERE session_hash IS NOT NULL AND service_delegation IS NULL"
                                )
                            ).scalar_one()
                            == 2
                        )
        finally:
            database.dispose()
    assert snapshots[0] == snapshots[1]


@pytest.mark.parametrize(
    "revisions", [(), (PREVIOUS,), (SERVICE_PREVIOUS,), ("9999_unsupported",), (HEAD, PREVIOUS)]
)
def test_actual_service_schema_guard_refuses_old_missing_or_ambiguous_revision(
    migration_pair: MigrationPair, revisions: tuple[str, ...]
) -> None:
    database = engine(migration_pair.upgraded.url)
    try:
        with database.connect() as c:
            transaction = c.begin()
            try:
                c.execute(text("DELETE FROM public.alembic_version"))
                for revision in revisions:
                    c.execute(
                        text("INSERT INTO public.alembic_version(version_num) VALUES(:revision)"),
                        {"revision": revision},
                    )
                assert (
                    c.execute(text("SELECT emailmonitor.service_schema_ready()")).scalar_one()
                    is False
                )
            finally:
                transaction.rollback()
        with database.connect() as c:
            assert c.execute(text("SELECT emailmonitor.service_schema_ready()")).scalar_one()
    finally:
        database.dispose()


def test_actual_upgraded_human_login_retains_tenant_rls_without_service_authority(
    migration_pair: MigrationPair,
) -> None:
    target = migration_pair.upgraded
    with target.admin.connect() as c:
        target.verify(c)
        c.exec_driver_sql(f'GRANT CONNECT ON DATABASE "{target.name}" TO em_ci_runtime')
        c.exec_driver_sql(f'ALTER DATABASE "{target.name}" CONNECTION LIMIT 4')
    runtime = engine(
        make_url(RUNTIME).set(database=target.name).render_as_string(hide_password=False)
    )
    try:
        with runtime.begin() as c:
            assert rows(c, "SELECT id FROM emailmonitor.organizations") == []
            assert c.execute(text("SELECT emailmonitor.service_schema_ready()")).scalar_one()
        for org, token, visible_job, tombstoned_job in zip(
            migration_pair.legacy.organizations,
            migration_pair.legacy.tokens,
            migration_pair.legacy.visible_jobs,
            migration_pair.legacy.tombstoned_jobs,
            strict=True,
        ):
            with runtime.begin() as c:
                c.execute(
                    text(
                        "SELECT set_config('emailmonitor.session_hash',:token,true),"
                        "set_config('emailmonitor.organization_id',:org,true)"
                    ),
                    {"token": digest(token), "org": str(org)},
                )
                assert rows(c, "SELECT id FROM emailmonitor.organizations") == [(org,)]
                # Physical history preserves both jobs, but 0011's restrictive
                # lifecycle policy must keep the tombstoned draft unreadable.
                assert rows(c, "SELECT organization_id,id,kind,state FROM emailmonitor.jobs") == [
                    (org, visible_job, "fixture_probe", "queued")
                ]
                assert (
                    c.execute(
                        text("SELECT id FROM emailmonitor.jobs WHERE id=:id"),
                        {"id": tombstoned_job},
                    ).first()
                    is None
                )
            # One pooled connection has no residual tenant after each transaction.
            with runtime.begin() as c:
                assert rows(c, "SELECT id FROM emailmonitor.organizations") == []
                assert rows(c, "SELECT id FROM emailmonitor.jobs") == []
        for table in AUTHORITY_TABLES:
            with pytest.raises(DBAPIError):
                with runtime.begin() as c:
                    c.execute(text(f"SELECT * FROM emailmonitor.{table}"))
    finally:
        runtime.dispose()
        with target.admin.connect() as c:
            target.verify(c)
            c.exec_driver_sql(f'REVOKE CONNECT ON DATABASE "{target.name}" FROM em_ci_runtime')
            c.exec_driver_sql(f'ALTER DATABASE "{target.name}" CONNECTION LIMIT 0')


def test_actual_legacy_restore_refuses_even_disabled_principal_history(
    migration_pair: MigrationPair,
) -> None:
    database = engine(migration_pair.upgraded.url)
    principal = uuid4()
    try:
        # Empty service authority remains compatible with the old profile.
        capture(database, migration_pair.legacy.organizations)
        with database.begin() as c:
            # A historical disabled row is sufficient to require a new restore
            # seal. It creates no login, membership or effective service grant.
            c.execute(
                text(
                    "INSERT INTO emailmonitor.service_principals"
                    "(id,organization_id,login_oid,login_name,kind,active,revision) "
                    "SELECT :id,:org,oid,rolname,'worker',false,2 FROM pg_roles "
                    "WHERE rolname='emailmonitor_worker'"
                ),
                {"id": principal, "org": migration_pair.legacy.organizations[0]},
            )
        with pytest.raises(RestoreRefused, match="restore_service_authority_unsupported"):
            capture(database, migration_pair.legacy.organizations)
    finally:
        with database.begin() as c:
            c.execute(
                text("DELETE FROM emailmonitor.service_principals WHERE id=:id"),
                {"id": principal},
            )
        database.dispose()


@pytest.mark.parametrize(
    "name",
    [
        "postgres",
        "emailmonitor",
        "em_service_migration_",
        "em_service_migration_" + "g" * 32,
        "em_service_migration_" + "a" * 32 + '";DROP DATABASE postgres;--',
    ],
)
def test_migration_target_rejects_unowned_or_interpolated_identifiers(name: str) -> None:
    with pytest.raises(ValueError, match="Owned disposable"):
        target_name(name)


def test_migration_target_accepts_only_bounded_generated_name() -> None:
    name = "em_service_migration_" + uuid4().hex
    assert target_name(name) == name
    assert len(name) < 63

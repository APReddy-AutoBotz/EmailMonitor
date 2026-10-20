"""Trusted, quiesced synthetic CI restore exercise. Never a production restore tool."""

import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, create_engine, text

IMAGE = (
    "postgres:17.11-bookworm@sha256:"
    "3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826"
)
ADMIN = "postgresql+pg8000://postgres:emailmonitor-ci-only@127.0.0.1:5432/postgres"
RUNTIME = "postgresql+pg8000://em_ci_runtime:emailmonitor-ci-runtime-only@127.0.0.1:5432/postgres"
AUTH = "postgresql+pg8000://em_ci_authenticator:emailmonitor-ci-auth-only@127.0.0.1:5432/postgres"
MAX_BYTES = 64 * 1024 * 1024
TABLES = (
    "organizations",
    "memberships",
    "source_policy_heads",
    "source_policies",
    "lifecycle_configuration",
    "lifecycle_job_deadlines",
    "privacy_keys",
    "privacy_suppressions",
    "deletion_tombstones",
    "jobs",
    "exports",
    "resolution_accounts",
    "usage_events",
    "fixture_quota",
    "support_contexts",
    "tenant_configuration",
    "tenant_source_buckets",
    "configuration_events",
    "export_entitlements",
    "lifecycle_ticks",
)
FRONTIER_TABLES = (
    "discovery",
    "discovery_outbox",
    "article_observations",
    "association_batches",
    "execution_runs",
    "execution_items",
    "execution_events",
    "execution_outbox",
    "execution_effects",
    "job_items",
    "job_outbox",
    "usage_reservations",
    "admission_requests",
    "source_resource_requests",
    "job_entitlements",
)
BATCH_TABLES = (
    "association_authors",
    "association_candidates",
    "association_evidence",
    "author_email_associations",
    "association_affiliations",
    "association_raw_variants",
    "association_author_evidence",
    "association_candidate_evidence",
    "association_evidence_links",
    "association_reviews",
    "association_review_evidence",
    "association_outbox",
)
UNCHANGED = (
    "memberships",
    "source_policy_heads",
    "resolution_accounts",
    "usage_events",
    "fixture_quota",
    "support_contexts",
    "tenant_configuration",
    "tenant_source_buckets",
    "configuration_events",
    "export_entitlements",
    "lifecycle_ticks",
)


class RestoreRefused(RuntimeError):
    """Fixed non-content failure only."""


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda item: item.__dict__ if isinstance(item, SafetySnapshot) else str(item),
        ).encode()
    ).hexdigest()


def database_name(value: str) -> str:
    if not re.fullmatch(r"em_restore_[a-f0-9]{32}", value):
        raise RestoreRefused("restore_target_refused")
    return value


def require_tool_version(program: str, value: str) -> None:
    if program not in ("pg_dump", "pg_restore") or not re.fullmatch(
        rf"{program} \(PostgreSQL\) 17\.11(?: \(Debian 17\.11-[A-Za-z0-9.+~]+\))?", value
    ):
        raise RestoreRefused("restore_tool_version_refused")


def require_ci(environ: dict[str, str]) -> str:
    if (
        environ.get("GITHUB_ACTIONS") != "true"
        or environ.get("EM_REQUIRE_SYNTHETIC_RESTORE") != "true"
        or environ.get("EM_TEST_ADMIN_DATABASE_URL") != ADMIN
        or environ.get("EM_TEST_DATABASE_URL") != RUNTIME
        or environ.get("EM_TEST_AUTH_DATABASE_URL") != AUTH
    ):
        raise RestoreRefused("restore_environment_refused")
    container = environ.get("EM_TEST_POSTGRES_CONTAINER", "")
    if not re.fullmatch(r"[a-f0-9]{64}", container):
        raise RestoreRefused("restore_container_refused")
    return container


@dataclass(frozen=True)
class SafetySnapshot:
    organizations: tuple[UUID, UUID]
    rows: dict[str, list[dict[str, Any]]] = field(repr=False)
    identities: list[dict[str, Any]] = field(repr=False)
    sessions: list[dict[str, Any]] = field(repr=False)
    catalog: list[dict[str, Any]] = field(repr=False)
    shared: dict[str, list[dict[str, Any]]] = field(default_factory=dict, repr=False)
    frontier: dict[str, list[dict[str, Any]]] = field(default_factory=dict, repr=False)


def records(c: Connection, table: str, organizations: tuple[UUID, UUID]) -> list[dict[str, Any]]:
    if table not in TABLES:
        raise RestoreRefused("restore_table_refused")
    column = "id" if table == "organizations" else "organization_id"
    result: Sequence[dict[str, Any]] = (
        c.execute(
            text(
                f"SELECT row_to_json(t) FROM emailmonitor.{table} t "
                f"WHERE {column} IN (:a,:b) ORDER BY row_to_json(t)::text LIMIT 501"
            ),
            {"a": organizations[0], "b": organizations[1]},
        )
        .scalars()
        .all()
    )
    if len(result) > 500:
        raise RestoreRefused("restore_row_cap")
    return list(result)


def frontier_records(
    c: Connection, organizations: tuple[UUID, UUID]
) -> dict[str, list[dict[str, Any]]]:
    result = {}
    for table in (*FRONTIER_TABLES, *BATCH_TABLES):
        join = (
            (
                " JOIN emailmonitor.association_batches b ON b.organization_id=t.organization_id "
                "AND b.id=t.batch_id"
            )
            if table in BATCH_TABLES
            else ""
        )
        job = "b.job_id" if table in BATCH_TABLES else "t.job_id"
        values = c.execute(
            text(
                f"SELECT t.organization_id::text,{job}::text,row_to_json(t)::text "
                f"FROM emailmonitor.{table} t{join} WHERE t.organization_id IN (:a,:b) "
                "ORDER BY row_to_json(t)::text LIMIT 501"
            ),
            {"a": organizations[0], "b": organizations[1]},
        ).all()
        if len(values) > 500:
            raise RestoreRefused("restore_row_cap")
        result[table] = [
            {
                "organization_id": row[0],
                "job_id": row[1],
                "digest": hashlib.sha256(row[2].encode()).hexdigest(),
            }
            for row in values
        ]
    return result


def unaffected_frontier(
    snapshot: SafetySnapshot, current: SafetySnapshot
) -> dict[str, list[dict[str, Any]]]:
    deleted = {(r["organization_id"], r["job_id"]) for r in current.rows["deletion_tombstones"]}
    return {
        table: [r for r in rows if (r["organization_id"], r["job_id"]) not in deleted]
        for table, rows in snapshot.frontier.items()
    }


def capture(engine: Engine, organizations: tuple[UUID, UUID]) -> SafetySnapshot:
    if len(set(organizations)) != 2:
        raise RestoreRefused("restore_tenant_scope_refused")
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as c, c.begin():
        # This legacy restore profile has no service-role/authority seal. Refuse
        # rather than replay an older principal or delegation revocation state.
        if c.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM emailmonitor.service_principals) "
                "OR EXISTS(SELECT 1 FROM emailmonitor.service_delegations) "
                "OR EXISTS(SELECT 1 FROM emailmonitor.service_audit)"
            )
        ).scalar_one():
            raise RestoreRefused("restore_service_authority_unsupported")
        rows = {table: records(c, table, organizations) for table in TABLES}
        active: bool = c.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM emailmonitor.admission_requests "
                "WHERE organization_id IN (:a,:b) AND state='active') "
                "OR EXISTS(SELECT 1 FROM emailmonitor.execution_items "
                "WHERE organization_id IN (:a,:b) AND state='running') "
                "OR EXISTS(SELECT 1 FROM emailmonitor.job_items "
                "WHERE organization_id IN (:a,:b) AND state='running') "
                "OR EXISTS(SELECT 1 FROM emailmonitor.exports "
                "WHERE organization_id IN (:a,:b) AND lease_nonce IS NOT NULL) "
                "OR EXISTS(SELECT 1 FROM emailmonitor.source_resource_requests "
                "WHERE organization_id IN (:a,:b) AND state='active')"
            ),
            {"a": organizations[0], "b": organizations[1]},
        ).scalar_one()
        if active:
            raise RestoreRefused("restore_not_quiesced")
        identities: list[dict[str, Any]] = list(
            c.execute(
                text(
                    "SELECT row_to_json(i) FROM emailmonitor.identities i WHERE id IN "
                    "(SELECT identity_id FROM emailmonitor.memberships "
                    "WHERE organization_id IN (:a,:b)) "
                    "ORDER BY i.id LIMIT 501"
                ),
                {"a": organizations[0], "b": organizations[1]},
            ).scalars()
        )
        sessions: list[dict[str, Any]] = list(
            c.execute(
                text(
                    "SELECT row_to_json(s) FROM emailmonitor.sessions s WHERE identity_id IN "
                    "(SELECT identity_id FROM emailmonitor.memberships "
                    "WHERE organization_id IN (:a,:b)) "
                    "ORDER BY s.token_hash LIMIT 501"
                ),
                {"a": organizations[0], "b": organizations[1]},
            ).scalars()
        )
        catalog: list[dict[str, Any]] = list(
            c.execute(
                text(
                    "SELECT row_to_json(s) FROM emailmonitor.source_catalog s "
                    "ORDER BY source_id LIMIT 501"
                )
            ).scalars()
        )
        if any(len(value) > 500 for value in (identities, sessions, catalog)):
            raise RestoreRefused("restore_row_cap")
        shared: dict[str, list[dict[str, Any]]] = {}
        for table in ("source_resource_buckets", "admission_pools"):
            values: Sequence[dict[str, Any]] = (
                c.execute(
                    text(
                        f"SELECT row_to_json(t) FROM emailmonitor.{table} t "
                        "ORDER BY row_to_json(t)::text LIMIT 501"
                    )
                )
                .scalars()
                .all()
            )
            if len(values) > 500:
                raise RestoreRefused("restore_row_cap")
            shared[table] = list(values)
        return SafetySnapshot(
            organizations,
            rows,
            identities,
            sessions,
            catalog,
            shared,
            frontier_records(c, organizations),
        )


def supported_delta(before: SafetySnapshot, current: SafetySnapshot) -> None:
    # This deliberately partial exercise cannot merge post-backup work or new policy
    # versions/authentication changes. Refuse rather than roll back durable authority.
    if before.organizations != current.organizations:
        raise RestoreRefused("restore_tenant_scope_refused")
    if any(row["job_id"] is None for row in current.rows["deletion_tombstones"]):
        raise RestoreRefused("restore_org_tombstone_unsupported")
    if unaffected_frontier(before, current) != unaffected_frontier(current, current):
        raise RestoreRefused("restore_unreplayed_business_frontier")
    for table in UNCHANGED:
        if before.rows[table] != current.rows[table]:
            raise RestoreRefused("restore_unreplayed_accounting_or_authority")
    if (
        before.identities != current.identities
        or before.sessions != current.sessions
        or before.catalog != current.catalog
        or before.shared != current.shared
        or before.rows["organizations"] != current.rows["organizations"]
    ):
        raise RestoreRefused("restore_unreplayed_authority")
    old = {(r["organization_id"], r["id"]) for r in before.rows["jobs"]}
    if old != {(r["organization_id"], r["id"]) for r in current.rows["jobs"]}:
        raise RestoreRefused("restore_unreplayed_jobs")
    policies = {
        (r["organization_id"], r["source_id"], r["version"]): r
        for r in before.rows["source_policies"]
    }
    if policies.keys() != {
        (r["organization_id"], r["source_id"], r["version"])
        for r in current.rows["source_policies"]
    }:
        raise RestoreRefused("restore_unreplayed_policy_version")
    for row in current.rows["source_policies"]:
        prior = policies[(row["organization_id"], row["source_id"], row["version"])]
        if any(prior[k] != row[k] for k in ("policy", "created_by", "valid_until")):
            raise RestoreRefused("restore_unreplayed_policy_version")
        if row["state"] != prior["state"] and row["state"] not in (
            "revoked",
            "suspended",
            "expired",
        ):
            raise RestoreRefused("restore_permission_expansion_refused")
    for table, keys in (
        ("privacy_suppressions", ("organization_id", "id")),
        ("deletion_tombstones", ("organization_id", "id")),
        ("lifecycle_job_deadlines", ("organization_id", "job_id")),
    ):
        previous_records = {tuple(r[key] for key in keys): r for r in before.rows[table]}
        updated = {tuple(r[key] for key in keys): r for r in current.rows[table]}
        if not previous_records.keys() <= updated.keys():
            raise RestoreRefused("restore_safety_record_missing")
        if table == "lifecycle_job_deadlines":
            for record_key, row in previous_records.items():
                if any(
                    updated[record_key][column] > row[column]
                    for column in ("contact_deadline", "excerpt_deadline")
                ):
                    raise RestoreRefused("restore_deadline_expansion_refused")
    old_keys = {r["organization_id"]: r["key"] for r in before.rows["privacy_keys"]}
    if old_keys != {r["organization_id"]: r["key"] for r in current.rows["privacy_keys"]}:
        raise RestoreRefused("restore_privacy_key_change_refused")


class RestoreExercise:
    def __init__(self, directory: Path) -> None:
        self.container = require_ci(dict(os.environ))
        self.name = database_name("em_restore_" + uuid4().hex)
        self.owner = "emailmonitor-synthetic-restore/" + uuid4().hex
        self.admin = create_engine(ADMIN, hide_parameters=True, isolation_level="AUTOCOMMIT")
        self.target = create_engine(ADMIN.rsplit("/", 1)[0] + "/" + self.name, hide_parameters=True)
        self.archive = directory / (self.name + ".dump")
        self.created = False
        self.archive_digest: str | None = None
        self.ready = False
        self.validated = False
        self.current: SafetySnapshot | None = None
        self.target_seal: str | None = None
        self.replay_seal: str | None = None
        self.started = time.monotonic()

    def command(self, arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        try:
            result = subprocess.run(
                ["docker", "exec", *arguments],
                stderr=subprocess.PIPE,
                timeout=90,
                check=False,
                **kwargs,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise RestoreRefused("restore_command_failed") from None
        if result.returncode != 0 or result.stderr:
            raise RestoreRefused("restore_command_failed")
        return result

    def backup(self) -> str:
        inspected = subprocess.run(
            ["docker", "inspect", "--format", "{{.Config.Image}}", self.container],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if inspected.returncode != 0 or inspected.stdout.decode().strip() != IMAGE:
            raise RestoreRefused("restore_image_refused")
        for program in ("pg_dump", "pg_restore"):
            result = self.command([self.container, program, "--version"], stdout=subprocess.PIPE)
            require_tool_version(program, result.stdout.decode().strip())
        with self.admin.connect() as c:
            if c.execute(text("SHOW server_version_num")).scalar_one() != "170011":
                raise RestoreRefused("restore_server_version_refused")
            if c.execute(text("SELECT pg_database_size('postgres')")).scalar_one() > MAX_BYTES:
                raise RestoreRefused("restore_archive_cap")
        with os.fdopen(
            os.open(self.archive, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
        ) as output:
            self.command(
                [
                    self.container,
                    "pg_dump",
                    "-U",
                    "postgres",
                    "--no-password",
                    "--format=custom",
                    "postgres",
                ],
                stdout=output,
            )
        if not 0 < self.archive.stat().st_size <= MAX_BYTES:
            raise RestoreRefused("restore_archive_cap")
        self.archive_digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        return self.archive_digest

    def restore_closed(self) -> None:
        if self.created or self.ready or self.archive_digest is None:
            raise RestoreRefused("restore_state_refused")
        if (
            self.archive.is_symlink()
            or not self.archive.is_file()
            or not 0 < self.archive.stat().st_size <= MAX_BYTES
            or self.archive.stat().st_mode & 0o077
            or hashlib.sha256(self.archive.read_bytes()).hexdigest() != self.archive_digest
        ):
            raise RestoreRefused("restore_archive_integrity_refused")
        # Record exact ownership immediately after CREATE; cleanup never drops an
        # unmarked target, even if a client result is uncertain.
        with self.admin.connect() as c:
            c.execute(text(f'CREATE DATABASE "{self.name}" TEMPLATE template0 CONNECTION LIMIT 0'))
            self.created = True
            c.execute(text(f"COMMENT ON DATABASE \"{self.name}\" IS '{self.owner}'"))
            c.execute(
                text(
                    f'REVOKE CONNECT ON DATABASE "{self.name}" '
                    "FROM PUBLIC, em_ci_runtime, em_ci_authenticator"
                )
            )
        with self.archive.open("rb") as source:
            self.command(
                [
                    "-i",
                    self.container,
                    "pg_restore",
                    "-U",
                    "postgres",
                    "--no-password",
                    "--exit-on-error",
                    "--single-transaction",
                    "--dbname",
                    self.name,
                ],
                stdin=source,
                stdout=subprocess.DEVNULL,
            )

    def replay(
        self, before: SafetySnapshot, current: SafetySnapshot, tokens: dict[UUID, str]
    ) -> None:
        if not self.created or self.ready or set(tokens) != set(current.organizations):
            raise RestoreRefused("restore_state_refused")
        if self.validated:
            if self.replay_seal != fingerprint(
                (before, current)
            ) or self.target_seal != fingerprint(capture(self.target, current.organizations)):
                raise RestoreRefused("restore_state_refused")
            return
        supported_delta(before, current)
        restored = capture(self.target, current.organizations)
        if fingerprint(restored) != fingerprint(before):
            raise RestoreRefused("restore_snapshot_mismatch")
        with self.target.begin() as c:
            c.execute(text("SET LOCAL statement_timeout='5000'"))
            # Exact stored keys/digests, never recovered raw contacts, and earliest
            # retained deadlines are installed before any application connection.
            for table, columns, keys in (
                ("privacy_keys", ("organization_id", "key"), ("organization_id",)),
                (
                    "privacy_suppressions",
                    (
                        "organization_id",
                        "id",
                        "kind",
                        "digest",
                        "reason",
                        "active",
                        "created_at",
                        "withdrawn_at",
                    ),
                    ("organization_id", "id"),
                ),
                (
                    "lifecycle_configuration",
                    ("organization_id", "revision", "retention", "next_due_at"),
                    ("organization_id",),
                ),
                (
                    "lifecycle_job_deadlines",
                    ("organization_id", "job_id", "contact_deadline", "excerpt_deadline"),
                    ("organization_id", "job_id"),
                ),
            ):
                for row in current.rows[table]:
                    names = ",".join(columns)
                    updates = ",".join(
                        f"{column}=EXCLUDED.{column}" for column in columns if column not in keys
                    )
                    c.execute(
                        text(
                            f"INSERT INTO emailmonitor.{table} ({names}) SELECT {names} FROM "
                            f"json_populate_record(NULL::emailmonitor.{table},CAST(:row AS json)) "
                            f"ON CONFLICT ({','.join(keys)}) DO UPDATE SET {updates}"
                        ),
                        {"row": json.dumps(row)},
                    )
            # Replay intents against stale content, NOT an already-purged marker
            # copied onto stale bytes (which would make purge return early).
            for org in current.organizations:
                c.execute(
                    text(
                        "SELECT set_config('emailmonitor.organization_id',:org,true), "
                        "set_config('emailmonitor.session_hash',:token,true)"
                    ),
                    {"org": str(org), "token": hashlib.sha256(tokens[org].encode()).hexdigest()},
                )
                for row in current.rows["deletion_tombstones"]:
                    if row["organization_id"] != str(org):
                        continue
                    receipt: dict[str, Any] = c.execute(
                        text("SELECT emailmonitor.lifecycle_stage(:org,:id,:job,:reason)"),
                        {
                            "org": org,
                            "id": UUID(row["id"]),
                            "job": UUID(row["job_id"]) if row["job_id"] else None,
                            "reason": row["reason"],
                        },
                    ).scalar_one()
                    if receipt["id"] != row["id"]:
                        raise RestoreRefused("restore_marker_mismatch")
                    if row["stage"] == "purged":
                        purged: dict[str, Any] = c.execute(
                            text("SELECT emailmonitor.lifecycle_purge(:org,:id)"),
                            {"org": org, "id": UUID(row["id"])},
                        ).scalar_one()
                        if purged["stage"] != "purged":
                            raise RestoreRefused("restore_purge_incomplete")
                old = {
                    (r["source_id"], r["version"]): r
                    for r in before.rows["source_policies"]
                    if r["organization_id"] == str(org)
                }
                for row in current.rows["source_policies"]:
                    if (
                        row["organization_id"] == str(org)
                        and row["state"] != old[(row["source_id"], row["version"])]["state"]
                    ):
                        c.execute(
                            text(
                                "UPDATE emailmonitor.source_policies SET state=:state "
                                "WHERE organization_id=:org AND source_id=:source "
                                "AND version=:version"
                            ),
                            {
                                "state": row["state"],
                                "org": org,
                                "source": row["source_id"],
                                "version": row["version"],
                            },
                        )
            # Reconcile protected job generations/accounting before commit. These
            # checks intentionally refuse unrepresented post-backup work.
            for table in ("jobs", "exports", *UNCHANGED):
                if records(c, table, current.organizations) != current.rows[table]:
                    raise RestoreRefused("restore_reconciliation_failed")
            for table in (
                "privacy_keys",
                "privacy_suppressions",
                "lifecycle_configuration",
                "lifecycle_job_deadlines",
                "source_policies",
            ):
                if records(c, table, current.organizations) != current.rows[table]:
                    raise RestoreRefused("restore_authority_reconciliation_failed")
        if fingerprint(capture(self.admin, current.organizations)) != fingerprint(current):
            raise RestoreRefused("restore_source_changed")
        if unaffected_frontier(
            capture(self.target, current.organizations), current
        ) != unaffected_frontier(current, current):
            raise RestoreRefused("restore_frontier_reconciliation_failed")
        self.current = current
        self.target_seal = fingerprint(capture(self.target, current.organizations))
        self.replay_seal = fingerprint((before, current))
        self.validated = True

    def require_ready(self) -> None:
        if not self.ready:
            raise RestoreRefused("restore_not_ready")

    def open_after_validation(self) -> None:
        # Called only after replay and reconciliation by the explicit exercise.
        if not self.created or self.ready or not self.validated:
            raise RestoreRefused("restore_state_refused")
        if (
            self.current is None
            or fingerprint(capture(self.admin, self.current.organizations))
            != fingerprint(self.current)
            or fingerprint(capture(self.target, self.current.organizations)) != self.target_seal
        ):
            raise RestoreRefused("restore_state_changed")
        with self.admin.connect() as c:
            c.execute(
                text(
                    f'GRANT CONNECT ON DATABASE "{self.name}" TO em_ci_runtime, em_ci_authenticator'
                )
            )
            c.execute(text(f'ALTER DATABASE "{self.name}" CONNECTION LIMIT -1'))
        self.ready = True

    def url(self, original: str) -> str:
        self.require_ready()
        if original not in (ADMIN, RUNTIME, AUTH):
            raise RestoreRefused("restore_url_refused")
        return original.rsplit("/", 1)[0] + "/" + self.name

    def close(self) -> None:
        self.target.dispose()
        try:
            if self.created:
                with self.admin.connect() as c:
                    owner = c.execute(
                        text(
                            "SELECT shobj_description(oid,'pg_database') "
                            "FROM pg_database WHERE datname=:name"
                        ),
                        {"name": self.name},
                    ).scalar_one_or_none()
                    if owner != self.owner:
                        raise RestoreRefused("restore_cleanup_owner_refused")
                    c.execute(text(f'DROP DATABASE "{self.name}" WITH (FORCE)'))
        finally:
            self.admin.dispose()
            self.archive.unlink(missing_ok=True)

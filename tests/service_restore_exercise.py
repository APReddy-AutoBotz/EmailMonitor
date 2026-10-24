"""Closed, same-cluster synthetic service restore proof; never a serving restore tool."""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from restore_exercise import (
    RestoreExercise,
    RestoreRefused,
    SafetySnapshot,
    capture_rows,
    fingerprint,
    supported_delta,
)
from service_restore_catalog import CATALOG_QUERIES
from sqlalchemy import Connection, Engine, text

SERVICE_TABLES = ("service_principals", "service_delegations", "service_audit")
EXPORT_TABLES = (
    "export_members",
    "export_outcomes",
    "export_artifacts",
    "export_requests",
    "export_outbox",
    "export_effects",
    "export_events",
)
PRINCIPAL_FIELDS = frozenset(
    ("id", "organization_id", "login_oid", "login_name", "kind", "active", "revision")
)
DELEGATION_FIELDS = frozenset(
    (
        "organization_id",
        "id",
        "principal_id",
        "principal_revision",
        "purpose",
        "resource_id",
        "generation",
        "deletion_generation",
        "initiator_id",
        "permission_revision",
        "membership_revision",
        "origin_session_hash",
        "source_id",
        "policy_version",
        "issued_at",
        "deadline",
        "revoked_at",
    )
)
AUDIT_FIELDS = frozenset(
    ("organization_id", "id", "principal_id", "delegation_id", "action", "occurred_at")
)


@dataclass(frozen=True)
class ServiceSeal:
    principals: list[dict[str, Any]] = field(repr=False)
    delegations: list[dict[str, Any]] = field(repr=False)
    audit: list[dict[str, Any]] = field(repr=False)
    roles: dict[str, list[dict[str, Any]]] = field(repr=False)
    catalog: dict[str, list[dict[str, Any]]] = field(repr=False)
    exports: dict[str, list[dict[str, Any]]] = field(repr=False)


@dataclass(frozen=True)
class ServiceSnapshot(SafetySnapshot):
    service: ServiceSeal | None = field(default=None, repr=False)


def seal(snapshot: SafetySnapshot) -> ServiceSeal:
    if not isinstance(snapshot, ServiceSnapshot) or not isinstance(snapshot.service, ServiceSeal):
        raise RestoreRefused("restore_service_seal_required")
    return snapshot.service


def snapshot_difference_sections(before: ServiceSnapshot, restored: ServiceSnapshot) -> list[str]:
    """Fixed labels only: never include row values, identifiers, hashes or tokens."""
    labels = []
    for name in ("organizations", "identities", "sessions", "catalog"):
        if fingerprint(getattr(before, name)) != fingerprint(getattr(restored, name)):
            labels.append(name)
    for name in ("rows", "shared", "frontier"):
        if fingerprint(getattr(before, name)) != fingerprint(getattr(restored, name)):
            labels.append(name)
    old, new = seal(before), seal(restored)
    for name in ("principals", "delegations", "audit"):
        if fingerprint(getattr(old, name)) != fingerprint(getattr(new, name)):
            labels.append("service." + name)
    for name, keys in (
        ("roles", ("roles", "memberships")),
        ("catalog", tuple(CATALOG_QUERIES)),
        ("exports", EXPORT_TABLES),
    ):
        a, b = getattr(old, name), getattr(new, name)
        if not isinstance(a, dict) or not isinstance(b, dict):
            labels.append("service." + name + ".shape")
            continue
        for key in keys:
            if fingerprint(a.get(key)) != fingerprint(b.get(key)):
                labels.append("service." + name + "." + key)
        if set(a) != set(b) or (
            fingerprint(a) != fingerprint(b) and ((set(a) | set(b)) - set(keys))
        ):
            labels.append("service." + name + ".shape")
    return labels


def stamp(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(value)
        if result.utcoffset() is None:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise RestoreRefused("restore_service_timestamp_refused") from None


def index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result = {(r["organization_id"], r["id"]): r for r in rows}
    if len(result) != len(rows):
        raise RestoreRefused("restore_service_duplicate_refused")
    return result


def validate_service_seal(snapshot: ServiceSnapshot) -> None:
    try:
        _validate_service_seal(snapshot)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise RestoreRefused("restore_service_shape_refused") from None


def _validate_service_seal(snapshot: ServiceSnapshot) -> None:
    authority = seal(snapshot)
    scope = {str(org) for org in snapshot.organizations}
    if len(scope) != 2 or not authority.principals:
        raise RestoreRefused("restore_service_scope_refused")
    for rows, fields in (
        (authority.principals, PRINCIPAL_FIELDS),
        (authority.delegations, DELEGATION_FIELDS),
        (authority.audit, AUDIT_FIELDS),
    ):
        if not isinstance(rows, list):
            raise RestoreRefused("restore_service_shape_refused")
        if len(rows) > 500:
            raise RestoreRefused("restore_row_cap")
        for row in rows:
            if set(row) != fields or row["organization_id"] not in scope:
                raise RestoreRefused("restore_service_scope_refused")
            try:
                UUID(row["id"])
            except (ValueError, TypeError, AttributeError):
                raise RestoreRefused("restore_service_identifier_refused") from None
        index(rows)
    principals = index(authority.principals)
    delegations = index(authority.delegations)
    jobs = index(snapshot.rows["jobs"])
    exports = index(snapshot.rows["exports"])
    members = {(r["organization_id"], r["identity_id"]) for r in snapshot.rows["memberships"]}
    identities = {r["id"] for r in snapshot.identities}
    sessions = {r["token_hash"]: r for r in snapshot.sessions}
    policies = {
        (r["organization_id"], r["source_id"], r["version"])
        for r in snapshot.rows["source_policies"]
    }
    logins: set[tuple[int, str]] = set()
    for row in authority.principals:
        if (
            type(row["active"]) is not bool
            or type(row["revision"]) is not int
            or row["revision"] < 1
            or type(row["login_oid"]) is not int
            or row["login_oid"] < 1
            or row["kind"] not in ("worker", "publisher")
            or not isinstance(row["login_name"], str)
            or not re.fullmatch(r"em_service_test_[a-f0-9]{32}", row["login_name"])
        ):
            raise RestoreRefused("restore_service_principal_refused")
        logins.add((row["login_oid"], row["login_name"]))
    if (
        len(logins) != len(authority.principals)
        or len({r["login_oid"] for r in authority.principals}) != len(authority.principals)
        or len({r["login_name"] for r in authority.principals}) != len(authority.principals)
        or len({r["id"] for r in authority.principals}) != len(authority.principals)
    ):
        raise RestoreRefused("restore_service_principal_refused")
    for row in authority.delegations:
        org = row["organization_id"]
        if (
            (org, row["principal_id"]) not in principals
            or row["purpose"] not in ("extraction", "export")
            or (org, row["resource_id"])
            not in (jobs if row["purpose"] == "extraction" else exports)
            or (org, row["initiator_id"]) not in members
            or row["initiator_id"] not in identities
            or row["origin_session_hash"] not in sessions
            or sessions[row["origin_session_hash"]]["identity_id"] != row["initiator_id"]
            or (org, row["source_id"], row["policy_version"]) not in policies
        ):
            raise RestoreRefused("restore_service_anchor_refused")
        for name in (
            "principal_revision",
            "generation",
            "deletion_generation",
            "permission_revision",
            "membership_revision",
            "policy_version",
        ):
            if type(row[name]) is not int or row[name] < 1:
                raise RestoreRefused("restore_service_anchor_refused")
        issued, deadline = stamp(row["issued_at"]), stamp(row["deadline"])
        if not 0 < (deadline - issued).total_seconds() <= 21600:
            raise RestoreRefused("restore_service_deadline_refused")
        if row["revoked_at"] is not None and stamp(row["revoked_at"]) < issued:
            raise RestoreRefused("restore_service_timestamp_refused")
    if len(
        {
            (
                r["organization_id"],
                r["principal_id"],
                r["purpose"],
                r["resource_id"],
                r["generation"],
            )
            for r in authority.delegations
        }
    ) != len(authority.delegations):
        raise RestoreRefused("restore_service_duplicate_refused")
    delegated: set[tuple[str, str]] = set()
    revoked: set[tuple[str, str]] = set()
    for row in authority.audit:
        key = (row["organization_id"], row["delegation_id"])
        grant = delegations.get(key)
        if (
            grant is None
            or row["principal_id"] != grant["principal_id"]
            or row["action"] not in ("delegated", "revoked", "transaction")
        ):
            raise RestoreRefused("restore_service_audit_refused")
        occurred = stamp(row["occurred_at"])
        if occurred < stamp(grant["issued_at"]):
            raise RestoreRefused("restore_service_audit_refused")
        if row["action"] == "delegated":
            if key in delegated:
                raise RestoreRefused("restore_service_audit_refused")
            delegated.add(key)
        if row["action"] == "revoked":
            if (
                key in revoked
                or grant["revoked_at"] is None
                or occurred < stamp(grant["revoked_at"])
            ):
                raise RestoreRefused("restore_service_audit_refused")
            revoked.add(key)
    if delegated != set(delegations) or revoked != {
        key for key, row in delegations.items() if row["revoked_at"] is not None
    }:
        raise RestoreRefused("restore_service_audit_refused")
    if set(authority.exports) != set(EXPORT_TABLES):
        raise RestoreRefused("restore_service_export_seal_required")
    for rows in authority.exports.values():
        if not isinstance(rows, list):
            raise RestoreRefused("restore_service_shape_refused")
        if len(rows) > 500:
            raise RestoreRefused("restore_row_cap")
        for row in rows:
            if (
                set(row) != {"organization_id", "digest"}
                or row["organization_id"] not in scope
                or not isinstance(row["digest"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", row["digest"])
            ):
                raise RestoreRefused("restore_service_export_seal_required")


def supported_service_delta(before: SafetySnapshot, current: SafetySnapshot) -> None:
    old, new = seal(before), seal(current)
    assert isinstance(before, ServiceSnapshot) and isinstance(current, ServiceSnapshot)
    validate_service_seal(before)
    validate_service_seal(current)
    supported_delta(before, current)
    old_markers = index(before.rows["deletion_tombstones"])
    new_markers = index(current.rows["deletion_tombstones"])
    for key, prior in old_markers.items():
        row = new_markers[key]
        if (
            any(row.get(k) != v for k, v in prior.items() if k not in ("stage", "purged_at"))
            or (prior["stage"] == "purged" and row != prior)
            or row["stage"] not in (prior["stage"], "purged")
            or (prior["purged_at"] is not None and row["purged_at"] != prior["purged_at"])
        ):
            raise RestoreRefused("restore_service_marker_history_refused")
    if old.roles != new.roles or old.catalog != new.catalog:
        raise RestoreRefused("restore_service_security_drift")
    previous, updated = index(old.principals), index(new.principals)
    if previous.keys() != updated.keys():
        raise RestoreRefused("restore_service_principal_change_refused")
    for key, prior in previous.items():
        row = updated[key]
        if row != prior and row != {
            **prior,
            "active": False,
            "revision": prior["revision"] + 1,
        }:
            raise RestoreRefused("restore_service_principal_change_refused")
        if row != prior and prior["active"] is not True:
            raise RestoreRefused("restore_service_principal_change_refused")
    previous, updated = index(old.delegations), index(new.delegations)
    if previous.keys() != updated.keys():
        raise RestoreRefused("restore_service_delegation_change_refused")
    changed = set()
    for key, prior in previous.items():
        row = updated[key]
        if row == prior:
            continue
        if (
            prior["revoked_at"] is not None
            or row["revoked_at"] is None
            or {**row, "revoked_at": None} != prior
        ):
            raise RestoreRefused("restore_service_delegation_change_refused")
        changed.add(key)
    prior_audit, updated_audit = index(old.audit), index(new.audit)
    if any(updated_audit.get(key) != row for key, row in prior_audit.items()):
        raise RestoreRefused("restore_service_audit_change_refused")
    additions = [r for key, r in updated_audit.items() if key not in prior_audit]
    if (
        len(additions) != len(changed)
        or {(r["organization_id"], r["delegation_id"]) for r in additions} != changed
        or any(r["action"] != "revoked" for r in additions)
    ):
        raise RestoreRefused("restore_service_audit_change_refused")
    # Lifecycle purge conservatively invalidates all exports in an affected tenant.
    # Such changes still must match the real replay result exactly before validation.
    deleted = {r["organization_id"] for r in current.rows["deletion_tombstones"]}
    for table in EXPORT_TABLES:
        if [r for r in old.exports[table] if r["organization_id"] not in deleted] != [
            r for r in new.exports[table] if r["organization_id"] not in deleted
        ]:
            raise RestoreRefused("restore_service_export_drift")


def bounded_rows(
    c: Connection, query: str, params: dict[str, Any] | None = None, *, limit: int = 500
) -> list[dict[str, Any]]:
    values = c.execute(text(query + f" LIMIT {limit + 1}"), params or {}).mappings().all()
    if len(values) > limit:
        raise RestoreRefused("restore_row_cap")
    return [dict(row) for row in values]


def service_rows(c: Connection, table: str) -> list[dict[str, Any]]:
    # PostgreSQL serializes oid as a JSON string. Normalize only this trusted SQL
    # field to bigint, preserving every other column and strict snapshot types.
    if table not in SERVICE_TABLES:
        raise RestoreRefused("restore_service_table_refused")
    record = (
        "(row_to_json(t)::jsonb || jsonb_build_object('login_oid',t.login_oid::bigint))"
        if table == "service_principals"
        else "row_to_json(t)"
    )
    return [
        row["record"]
        for row in bounded_rows(
            c,
            f"SELECT {record} AS record FROM emailmonitor.{table} t ORDER BY organization_id,id",
        )
    ]


def export_seal(c: Connection, organizations: tuple[UUID, UUID]) -> dict[str, list[dict[str, Any]]]:
    return {
        table: bounded_rows(
            c,
            "SELECT organization_id::text,encode(sha256(convert_to(row_to_json(t)::text,'UTF8')),"
            f"'hex') AS digest FROM emailmonitor.{table} t "
            "WHERE organization_id IN (:a,:b) ORDER BY organization_id,digest",
            {"a": organizations[0], "b": organizations[1]},
        )
        for table in EXPORT_TABLES
    }


def capture_service(engine: Engine, organizations: tuple[UUID, UUID]) -> ServiceSnapshot:
    if len(set(organizations)) != 2:
        raise RestoreRefused("restore_tenant_scope_refused")
    with (
        engine.connect().execution_options(isolation_level="REPEATABLE READ") as c,
        c.begin(),
    ):
        c.execute(text("SET LOCAL statement_timeout='5000'"))
        base = capture_rows(c, organizations)
        authority = [service_rows(c, table) for table in SERVICE_TABLES]
        if c.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all() != [
            "0017_execution_receipt_lock"
        ]:
            raise RestoreRefused("restore_service_schema_refused")
        # Cluster roles are not in pg_dump. Capture public attributes and membership
        # edges only, never pg_authid/credential verifiers. This is the same cluster.
        roles = {
            "roles": bounded_rows(
                c,
                "SELECT oid,rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,"
                "rolreplication,rolbypassrls,rolconnlimit,rolvaliduntil,rolconfig "
                "FROM pg_roles ORDER BY oid",
            ),
            "memberships": bounded_rows(
                c,
                "SELECT roleid,member,grantor,admin_option,inherit_option,set_option "
                "FROM pg_auth_members ORDER BY roleid,member,grantor",
            ),
        }
        for row in authority[0]:
            safe = c.execute(
                text(
                    "SELECT oid=:oid AND emailmonitor.service_login_safe(oid) "
                    "AND pg_has_role(oid,:expected,'MEMBER') "
                    "AND NOT pg_has_role(oid,:opposite,'MEMBER') "
                    "AND NOT pg_has_role(oid,:opposite,'SET') "
                    "AND NOT pg_has_role(oid,'emailmonitor_owner','MEMBER') "
                    "AND NOT pg_has_role(oid,'emailmonitor_owner','SET') "
                    "AND NOT pg_has_role(oid,'emailmonitor_runtime','MEMBER') "
                    "AND NOT pg_has_role(oid,'emailmonitor_runtime','SET') "
                    "AND NOT pg_has_role(oid,'emailmonitor_authenticator','MEMBER') "
                    "AND NOT pg_has_role(oid,'emailmonitor_authenticator','SET') "
                    "FROM pg_roles WHERE rolname=:name"
                ),
                {
                    "oid": row["login_oid"],
                    "name": row["login_name"],
                    "expected": "emailmonitor_" + row["kind"],
                    "opposite": "emailmonitor_publisher"
                    if row["kind"] == "worker"
                    else "emailmonitor_worker",
                },
            ).scalar_one_or_none()
            if safe is not True:
                raise RestoreRefused("restore_service_login_refused")
        # Portable catalog queries already used by fresh/populated upgrade proof.
        # Columns exceed the data-row cap; a separate finite 5000 catalog cap applies.
        catalog = {
            name: bounded_rows(c, query, limit=5000) for name, query in CATALOG_QUERIES.items()
        }
        result = ServiceSnapshot(
            **base.__dict__,
            service=ServiceSeal(
                authority[0],
                authority[1],
                authority[2],
                roles,
                catalog,
                export_seal(c, organizations),
            ),
        )
        validate_service_seal(result)
        return result


class ServiceRestoreExercise(RestoreExercise):
    """No serving/open transition exists. SQL probes use rolled-back trusted sessions."""

    capture = staticmethod(capture_service)
    supported_delta = staticmethod(supported_service_delta)

    def closed(self) -> None:
        if not self.created or self.ready:
            raise RestoreRefused("restore_service_target_must_remain_closed")
        with self.admin.connect() as c:
            row = (
                c.execute(
                    text(
                        "SELECT datdba,datconnlimit,shobj_description(oid,'pg_database') AS marker,"
                        "COALESCE((SELECT bool_or(a.privilege_type='CONNECT') FROM aclexplode("
                        "COALESCE(datacl,acldefault('d',datdba))) a "
                        "WHERE a.grantee<>datdba),false) "
                        "AS other_connect FROM pg_database WHERE datname=:name"
                    ),
                    {"name": self.name},
                )
                .mappings()
                .one_or_none()
            )
            if (
                row is None
                or row["datdba"] != getattr(self, "admin_owner_oid", None)
                or row["marker"] != self.owner
                or row["datconnlimit"] != 0
                or row["other_connect"]
            ):
                raise RestoreRefused("restore_service_closed_seal_refused")

    def restore_closed(self) -> None:
        with self.admin.connect() as c:
            self.admin_owner_oid: int = c.execute(
                text("SELECT oid FROM pg_roles WHERE rolname='postgres' AND rolname=session_user")
            ).scalar_one()
        super().restore_closed()
        self.closed()

    def replay(
        self, before: SafetySnapshot, current: SafetySnapshot, tokens: dict[UUID, str]
    ) -> None:
        self.closed()
        # Recheck source even for an identical second replay; never accept a stale seal.
        if fingerprint(self.capture(self.admin, current.organizations)) != fingerprint(current):
            raise RestoreRefused("restore_source_changed")
        super().replay(before, current, tokens)
        self.closed()

    def replay_authority(
        self, c: Connection, before: SafetySnapshot, current: SafetySnapshot
    ) -> None:
        old, new = seal(before), seal(current)
        previous = index(old.principals)
        for row in new.principals:
            prior = previous[(row["organization_id"], row["id"])]
            if row != prior:
                c.execute(
                    text(
                        "UPDATE emailmonitor.service_principals SET active=false "
                        "WHERE organization_id=:org AND id=:id"
                    ),
                    {"org": row["organization_id"], "id": row["id"]},
                )
        previous = index(old.delegations)
        for row in new.delegations:
            if row != previous[(row["organization_id"], row["id"])]:
                c.execute(
                    text(
                        "UPDATE emailmonitor.service_delegations SET revoked_at=:stamp "
                        "WHERE organization_id=:org AND id=:id"
                    ),
                    {
                        "org": row["organization_id"],
                        "id": row["id"],
                        "stamp": stamp(row["revoked_at"]),
                    },
                )
        prior_audit = index(old.audit)
        for row in new.audit:
            if (row["organization_id"], row["id"]) not in prior_audit:
                c.execute(
                    text(
                        "INSERT INTO emailmonitor.service_audit SELECT * FROM "
                        "json_populate_record(NULL::emailmonitor.service_audit,CAST(:row AS json))"
                    ),
                    {"row": json.dumps(row)},
                )

    def reconcile_authority(self, c: Connection, current: SafetySnapshot) -> None:
        authority = seal(current)
        for table, expected in zip(
            SERVICE_TABLES,
            (authority.principals, authority.delegations, authority.audit),
            strict=True,
        ):
            actual = service_rows(c, table)
            if actual != expected:
                raise RestoreRefused("restore_service_reconciliation_failed")
        if export_seal(c, current.organizations) != authority.exports:
            raise RestoreRefused("restore_service_export_reconciliation_failed")

    def validate_final(
        self, before: SafetySnapshot, current: SafetySnapshot, restored: SafetySnapshot
    ) -> None:
        if seal(current) != seal(restored):
            raise RestoreRefused("restore_service_final_seal_mismatch")
        if (
            current.organizations != restored.organizations
            or current.identities != restored.identities
            or current.sessions != restored.sessions
            or current.catalog != restored.catalog
            or current.shared != restored.shared
        ):
            raise RestoreRefused("restore_service_final_authority_mismatch")
        old_markers = index(before.rows["deletion_tombstones"])
        for table, expected in current.rows.items():
            actual = restored.rows.get(table)
            if table == "deletion_tombstones":
                # Normalize only timestamps actually generated by guarded replay.
                # Existing marker creation and completed-purge history stay exact.
                def markers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
                    result = []
                    for row in rows:
                        prior = old_markers.get((row["organization_id"], row["id"]))
                        omitted = set()
                        if prior is None:
                            omitted.add("created_at")
                        if row["stage"] == "purged" and (
                            prior is None or prior["stage"] != "purged"
                        ):
                            omitted.add("purged_at")
                        result.append({k: v for k, v in row.items() if k not in omitted})
                    return result

                if actual is None or markers(actual) != markers(expected):
                    raise RestoreRefused("restore_service_final_authority_mismatch")
            elif actual != expected:
                raise RestoreRefused("restore_service_final_authority_mismatch")
        if set(current.rows) != set(restored.rows):
            raise RestoreRefused("restore_service_final_authority_mismatch")
        self.closed()

    def open_after_validation(self) -> None:
        raise RestoreRefused("restore_service_target_must_remain_closed")

    def url(self, original: str) -> str:
        raise RestoreRefused("restore_service_target_must_remain_closed")

"""Pure closed service-restore contracts; no SQL, dumps, credentials or network.

These authored snapshots exercise admission and monotonic replay grammar only.
They are not evidence of actual PostgreSQL restore, role isolation or recovery.
"""

from copy import deepcopy
from dataclasses import fields, replace
from itertools import product
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from restore_exercise import (
    AUTH,
    RUNTIME,
    TABLES,
    RestoreRefused,
    SafetySnapshot,
    capture,
    fingerprint,
    supported_delta,
)
from service_restore_catalog import CATALOG_QUERIES
from service_restore_exercise import (
    ServiceRestoreExercise,
    ServiceSeal,
    ServiceSnapshot,
    service_rows,
    snapshot_difference_sections,
    supported_service_delta,
    validate_service_seal,
)
from sqlalchemy import Connection, Engine


@pytest.mark.parametrize(
    "version_case", ["head", "previous", "unknown", "empty", "duplicate", "mixed"]
)
def test_capture_service_requires_exact_current_migration(
    version_case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import service_restore_exercise as exercise

    root = Path(__file__).resolve().parents[3]
    config = Config()
    config.set_main_option("script_location", str(root / "services/backend/migrations"))
    scripts = ScriptDirectory.from_config(config)
    head = scripts.get_current_head()
    assert head is not None
    revision = scripts.get_revision(head)
    assert revision is not None
    versions = {
        "head": [head],
        "previous": [revision.down_revision],
        "unknown": ["unrecognized_schema"],
        "empty": [],
        "duplicate": [head, head],
        "mixed": [head, revision.down_revision],
    }[version_case]
    connection = MagicMock()
    connection.execute.return_value.scalars.return_value.all.return_value = versions
    engine = MagicMock()
    engine.connect.return_value.execution_options.return_value.__enter__.return_value = connection
    monkeypatch.setattr(exercise, "capture_rows", MagicMock())
    monkeypatch.setattr(exercise, "service_rows", MagicMock(return_value=[]))
    # Stop immediately after schema admission. This is no claim of SQL/restore acceptance.
    catalog = MagicMock(side_effect=RuntimeError("schema_admitted"))
    monkeypatch.setattr(exercise, "bounded_rows", catalog)
    if version_case == "head":
        with pytest.raises(RuntimeError, match="^schema_admitted$"):
            exercise.capture_service(engine, (UUID(int=100), UUID(int=200)))
        catalog.assert_called_once()
    else:
        with pytest.raises(RestoreRefused, match="^restore_service_schema_refused$"):
            exercise.capture_service(engine, (UUID(int=100), UUID(int=200)))
        catalog.assert_not_called()


EXPORT_TABLES = (
    "export_members",
    "export_outcomes",
    "export_artifacts",
    "export_requests",
    "export_outbox",
    "export_effects",
    "export_events",
)
ISSUED = "2026-10-22T08:00:00+00:00"
DEADLINE = "2026-10-22T14:00:00+00:00"
REVOKED = "2026-10-22T09:00:00+00:00"
AUDITED = "2026-10-22T09:00:00.000001+00:00"


def identifier(number: int) -> str:
    return str(UUID(int=number))


def snapshot() -> ServiceSnapshot:
    """Two tenants, both principal kinds, and extraction plus export anchors."""
    rows: dict[str, list[dict[str, Any]]] = {table: [] for table in TABLES}
    identities: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    principals: list[dict[str, Any]] = []
    delegations: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for tenant in (100, 200):
        org, actor = identifier(tenant), identifier(tenant + 1)
        token = str(tenant // 100) * 64
        rows["organizations"].append(
            {
                "id": org,
                "display_name": "Synthetic restore tenant",
                "status": "active",
                "region": "synthetic",
                "timezone": "UTC",
                "row_version": 1,
                "deletion_generation": 1,
            }
        )
        rows["memberships"].append(
            {
                "organization_id": org,
                "identity_id": actor,
                "role": "owner",
                "status": "active",
                "row_version": 1,
            }
        )
        identities.append(
            {
                "id": actor,
                "issuer": "https://identity.example.invalid",
                "subject": "synthetic-" + str(tenant),
                "active": True,
                "permission_revision": 1,
            }
        )
        sessions.append(
            {
                "token_hash": token,
                "csrf_hash": "c" * 64,
                "identity_id": actor,
                "permission_revision": 1,
                "expires_at": "2026-10-22T20:00:00+00:00",
                "revoked_at": None,
            }
        )
        rows["source_policy_heads"].append(
            {"organization_id": org, "source_id": "synthetic-publisher", "current_version": 1}
        )
        rows["source_policies"].append(
            {
                "organization_id": org,
                "source_id": "synthetic-publisher",
                "version": 1,
                "state": "approved",
                "policy": {
                    "purpose": "academic_contact_research",
                    "allowed_operations": ["extract_contacts", "export_contacts"],
                    "export_contacts_allowed": True,
                    "permission_reference": "synthetic fixture only",
                },
                "created_by": actor,
                "reviewed_by": actor,
                "approved_at": ISSUED,
                "valid_until": "2026-10-23T08:00:00+00:00",
                "row_version": 1,
            }
        )
        rows["jobs"].append(
            {
                "organization_id": org,
                "id": identifier(tenant + 2),
                "created_by": actor,
                "kind": "extraction",
                "request": {"purpose": "academic_contact_research"},
                "source_id": "synthetic-publisher",
                "policy_version": 1,
                "state": "completed",
                "generation": 1,
                "deletion_generation": 1,
                "row_version": 1,
            }
        )
        rows["exports"].append(
            {
                "organization_id": org,
                "id": identifier(tenant + 3),
                "requested_by": actor,
                "request": {"purpose": "academic_contact_research"},
                "snapshot": {"synthetic": True},
                "state": "ready",
                "reason": "ready",
                "revision": 1,
                "generation": 1,
                "deletion_generation": 1,
                "policy_version": 1,
                "created_at": ISSUED,
                "expires_at": "2026-10-22T20:00:00+00:00",
                "lease_nonce": None,
                "lease_until": None,
                "attempts": 1,
            }
        )
        for offset, kind, purpose, resource in (
            (10, "worker", "extraction", tenant + 2),
            (11, "publisher", "export", tenant + 3),
        ):
            principal, delegation = identifier(tenant + offset), identifier(tenant + offset + 10)
            principals.append(
                {
                    "id": principal,
                    "organization_id": org,
                    "login_oid": tenant + offset,
                    "login_name": "em_service_test_" + UUID(int=tenant + offset).hex,
                    "kind": kind,
                    "active": True,
                    "revision": 1,
                }
            )
            delegations.append(
                {
                    "organization_id": org,
                    "id": delegation,
                    "principal_id": principal,
                    "principal_revision": 1,
                    "purpose": purpose,
                    "resource_id": identifier(resource),
                    "generation": 1,
                    "deletion_generation": 1,
                    "initiator_id": actor,
                    "permission_revision": 1,
                    "membership_revision": 1,
                    "origin_session_hash": token,
                    "source_id": "synthetic-publisher",
                    "policy_version": 1,
                    "issued_at": ISSUED,
                    "deadline": DEADLINE,
                    "revoked_at": None,
                }
            )
            audit.append(
                {
                    "organization_id": org,
                    "id": identifier(tenant + offset + 20),
                    "principal_id": principal,
                    "delegation_id": delegation,
                    "action": "delegated",
                    "occurred_at": ISSUED,
                }
            )
    return ServiceSnapshot(
        organizations=(UUID(int=100), UUID(int=200)),
        rows=rows,
        identities=identities,
        sessions=sessions,
        catalog=[
            {
                "source_id": "synthetic-publisher",
                "enabled": True,
                "execution_mode": "fixture",
                "allowed_operations": ["extract_contacts", "export_contacts"],
            }
        ],
        service=ServiceSeal(
            principals=principals,
            delegations=delegations,
            audit=audit,
            roles={},
            catalog={},
            exports={table: [] for table in EXPORT_TABLES},
        ),
    )


def seal(value: ServiceSnapshot) -> ServiceSeal:
    assert value.service is not None
    return value.service


def amend(value: ServiceSnapshot, **changes: Any) -> ServiceSnapshot:
    return replace(value, service=replace(seal(value), **changes))


def change_row(
    value: ServiceSnapshot, table: str, index: int = 0, **changes: Any
) -> ServiceSnapshot:
    rows = deepcopy(getattr(seal(value), table))
    rows[index].update(changes)
    return amend(value, **{table: rows})


def revoke(value: ServiceSnapshot, index: int = 0) -> ServiceSnapshot:
    current = change_row(value, "delegations", index, revoked_at=REVOKED)
    grant = seal(current).delegations[index]
    event = {
        "organization_id": grant["organization_id"],
        "id": identifier(500 + index),
        "principal_id": grant["principal_id"],
        "delegation_id": grant["id"],
        "action": "revoked",
        "occurred_at": AUDITED,
    }
    return amend(current, audit=[*seal(current).audit, event])


def final_drift(value: ServiceSnapshot, field: str) -> ServiceSnapshot:
    """A coherent but different final snapshot, injected after reconciliation."""
    if field == "principals":
        return change_row(value, field, active=False, revision=2)
    if field == "delegations":
        return change_row(value, field, deadline="2026-10-22T13:59:59+00:00")
    if field == "audit":
        event = {
            **seal(value).audit[0],
            "id": identifier(999),
            "action": "transaction",
            "occurred_at": REVOKED,
        }
        return amend(value, audit=[*seal(value).audit, event])
    if field == "exports":
        return amend(
            value,
            exports={
                **seal(value).exports,
                "export_artifacts": [{"organization_id": identifier(100), "digest": "a" * 64}],
            },
        )
    return amend(value, **{field: {"changed": [{"authority": "unrepresented"}]}})


def test_coherent_two_tenant_service_snapshot_and_identical_replay_accept() -> None:
    before = snapshot()
    validate_service_seal(before)
    supported_service_delta(before, deepcopy(before))


def test_principal_history_without_any_delegations_or_audit_is_still_sealed() -> None:
    before = amend(snapshot(), delegations=[], audit=[])
    validate_service_seal(before)
    supported_service_delta(before, deepcopy(before))


def test_historical_transaction_audit_is_preserved_by_identical_replay() -> None:
    before = snapshot()
    transaction = {
        **seal(before).audit[0],
        "id": identifier(999),
        "action": "transaction",
        "occurred_at": REVOKED,
    }
    before = amend(before, audit=[*seal(before).audit, transaction])
    supported_service_delta(before, deepcopy(before))


def test_expired_grant_history_is_preserved_without_renewing_its_deadline() -> None:
    before = snapshot()
    old = "2020-01-01T08:00:00+00:00"
    before = change_row(before, "delegations", issued_at=old, deadline="2020-01-01T14:00:00+00:00")
    before = change_row(before, "audit", occurred_at=old)
    supported_service_delta(before, deepcopy(before))


@pytest.mark.parametrize("index", range(4))
def test_one_existing_principal_can_only_disable_with_one_revision_increment(index: int) -> None:
    before = snapshot()
    current = change_row(before, "principals", index, active=False, revision=2)
    supported_service_delta(before, current)
    supported_service_delta(current, deepcopy(current))


@pytest.mark.parametrize("index", range(4))
def test_existing_grant_revocation_requires_its_corresponding_audit(index: int) -> None:
    before = snapshot()
    current = revoke(before, index)
    supported_service_delta(before, current)
    supported_service_delta(current, deepcopy(current))


def test_all_grants_may_revoke_and_all_principals_disable_together() -> None:
    before = snapshot()
    current = before
    for index in range(4):
        current = revoke(current, index)
        current = change_row(current, "principals", index, active=False, revision=2)
    supported_service_delta(before, current)


@pytest.mark.parametrize("which", ["before", "current", "both"])
def test_legacy_snapshot_cannot_be_passed_as_a_sealed_service_snapshot(which: str) -> None:
    before = snapshot()
    legacy = SafetySnapshot(
        before.organizations,
        before.rows,
        before.identities,
        before.sessions,
        before.catalog,
        before.shared,
        before.frontier,
    )
    with pytest.raises(RestoreRefused):
        supported_service_delta(
            legacy if which in ("before", "both") else before,
            legacy if which in ("current", "both") else before,
        )


@pytest.mark.parametrize("which", ["before", "current", "both"])
def test_missing_service_seal_refuses_on_either_snapshot(which: str) -> None:
    before = snapshot()
    missing = replace(before, service=None)
    with pytest.raises(RestoreRefused):
        supported_service_delta(
            missing if which in ("before", "both") else before,
            missing if which in ("current", "both") else before,
        )


@pytest.mark.parametrize("value", [{}, [], "synthetic-invalid-seal", 1])
def test_wrong_service_seal_type_is_a_fixed_refusal(value: Any) -> None:
    with pytest.raises(RestoreRefused):
        validate_service_seal(replace(snapshot(), service=value))


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", identifier(901)),
        ("organization_id", identifier(200)),
        ("login_oid", 9876),
        ("login_name", "em_service_test_" + UUID(int=999).hex),
        ("kind", "publisher"),
        ("revision", 2),
    ],
)
def test_principal_identity_and_revision_cannot_drift(field: str, value: Any) -> None:
    before = snapshot()
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, change_row(before, "principals", **{field: value}))


@pytest.mark.parametrize(
    "old_active,new_active,old_revision,new_revision",
    [
        (True, False, 1, 1),
        (True, False, 1, 3),
        (True, False, 2, 1),
        (False, True, 2, 3),
        (False, True, 2, 2),
        (False, False, 2, 3),
        (True, True, 1, 2),
    ],
)
def test_principal_reenable_or_nonmonotonic_revision_refuses(
    old_active: bool, new_active: bool, old_revision: int, new_revision: int
) -> None:
    before = change_row(snapshot(), "principals", active=old_active, revision=old_revision)
    current = change_row(before, "principals", active=new_active, revision=new_revision)
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, current)


@pytest.mark.parametrize("table", ["principals", "delegations", "audit"])
@pytest.mark.parametrize("operation", ["remove", "duplicate", "add"])
def test_service_rows_cannot_be_removed_duplicated_or_added(table: str, operation: str) -> None:
    before = snapshot()
    rows = deepcopy(getattr(seal(before), table))
    if operation == "remove":
        rows.pop()
    elif operation == "duplicate":
        rows.append(deepcopy(rows[0]))
    else:
        rows.append({**rows[0], "id": identifier(999)})
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, amend(before, **{table: rows}))


@pytest.mark.parametrize("table", ["principals", "delegations", "audit"])
def test_duplicate_service_rows_refuse_even_if_both_snapshots_have_same_duplicates(
    table: str,
) -> None:
    before = snapshot()
    rows = deepcopy(getattr(seal(before), table))
    before = amend(before, **{table: [*rows, deepcopy(rows[0])]})
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, deepcopy(before))


@pytest.mark.parametrize("table", ["principals", "delegations", "audit"])
def test_unknown_service_row_columns_refuse(table: str) -> None:
    before = change_row(snapshot(), table, unrepresented_authority="must refuse")
    with pytest.raises(RestoreRefused):
        validate_service_seal(before)


@pytest.mark.parametrize("table", ["principals", "delegations", "audit"])
@pytest.mark.parametrize("value", [None, 1, "private-invalid-row", ["id"]])
def test_malformed_service_rows_are_fixed_refusals(table: str, value: Any) -> None:
    with pytest.raises(RestoreRefused) as refused:
        validate_service_seal(amend(snapshot(), **{table: [value]}))
    assert "private-invalid-row" not in str(refused.value)


@pytest.mark.parametrize("field", ["login_oid", "login_name"])
def test_principal_login_oid_and_login_name_are_independently_unique(field: str) -> None:
    before = snapshot()
    before = change_row(before, "principals", 1, **{field: seal(before).principals[0][field]})
    with pytest.raises(RestoreRefused):
        validate_service_seal(before)


def test_principal_identifier_is_globally_unique_across_tenants() -> None:
    before = snapshot()
    principal = seal(before).principals[0]["id"]
    before = change_row(before, "principals", 2, id=principal)
    before = change_row(before, "delegations", 2, principal_id=principal)
    before = change_row(before, "audit", 2, principal_id=principal)
    with pytest.raises(RestoreRefused):
        validate_service_seal(before)


def test_duplicate_grant_scope_cannot_hide_behind_another_identifier() -> None:
    before = snapshot()
    duplicate = {**seal(before).delegations[0], "id": identifier(999)}
    before = amend(before, delegations=[*seal(before).delegations, duplicate])
    with pytest.raises(RestoreRefused):
        validate_service_seal(before)


def test_empty_principal_seal_refuses() -> None:
    before = amend(snapshot(), principals=[], delegations=[], audit=[])
    with pytest.raises(RestoreRefused):
        validate_service_seal(before)


@pytest.mark.parametrize("table", ["principals", "delegations", "audit"])
def test_service_row_caps_fail_closed(table: str) -> None:
    before = snapshot()
    rows = [deepcopy(getattr(seal(before), table)[0]) for _ in range(501)]
    with pytest.raises(RestoreRefused, match="^restore_row_cap$"):
        validate_service_seal(amend(before, **{table: rows}))


@pytest.mark.parametrize(
    "table,field",
    [
        ("principals", "login_oid"),
        ("principals", "active"),
        ("principals", "revision"),
        ("delegations", "origin_session_hash"),
        ("delegations", "deadline"),
        ("delegations", "revoked_at"),
        ("audit", "principal_id"),
        ("audit", "occurred_at"),
    ],
)
def test_missing_service_row_columns_refuse(table: str, field: str) -> None:
    before = snapshot()
    rows = deepcopy(getattr(seal(before), table))
    del rows[0][field]
    with pytest.raises(RestoreRefused):
        validate_service_seal(amend(before, **{table: rows}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("organization_id", identifier(200)),
        ("id", identifier(901)),
        ("principal_id", identifier(111)),
        ("principal_revision", 2),
        ("purpose", "export"),
        ("resource_id", identifier(103)),
        ("generation", 2),
        ("deletion_generation", 2),
        ("initiator_id", identifier(201)),
        ("permission_revision", 2),
        ("membership_revision", 2),
        ("origin_session_hash", "2" * 64),
        ("source_id", "another-synthetic-source"),
        ("policy_version", 2),
        ("issued_at", "2026-10-22T08:00:01+00:00"),
        ("deadline", "2026-10-22T13:59:59+00:00"),
        ("deadline", "2026-10-22T14:00:01+00:00"),
    ],
)
def test_all_nonrevocation_grant_fields_are_immutable(field: str, value: Any) -> None:
    before = snapshot()
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, change_row(before, "delegations", **{field: value}))


@pytest.mark.parametrize("replacement", [None, "2026-10-22T09:00:01+00:00"])
def test_recorded_revocation_cannot_be_removed_or_changed(replacement: str | None) -> None:
    before = revoke(snapshot())
    current = change_row(before, "delegations", revoked_at=replacement)
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, current)


def test_new_revocation_without_audit_refuses() -> None:
    before = snapshot()
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, change_row(before, "delegations", revoked_at=REVOKED))


def test_historical_revocation_without_its_audit_refuses_even_when_unchanged() -> None:
    before = change_row(snapshot(), "delegations", revoked_at=REVOKED)
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, deepcopy(before))


def test_every_grant_requires_its_original_delegated_audit() -> None:
    before = snapshot()
    before = amend(before, audit=seal(before).audit[1:])
    with pytest.raises(RestoreRefused):
        validate_service_seal(before)


def test_duplicate_delegated_audit_with_another_id_refuses() -> None:
    before = snapshot()
    event = {**seal(before).audit[0], "id": identifier(999)}
    with pytest.raises(RestoreRefused):
        validate_service_seal(amend(before, audit=[*seal(before).audit, event]))


@pytest.mark.parametrize("action", ["delegated", "transaction", "revoked"])
def test_new_audit_without_new_grant_revocation_refuses(action: str) -> None:
    before = snapshot()
    event = {**seal(before).audit[0], "id": identifier(999), "action": action}
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, amend(before, audit=[*seal(before).audit, event]))


@pytest.mark.parametrize(
    "field,value",
    [
        ("organization_id", identifier(200)),
        ("principal_id", identifier(111)),
        ("delegation_id", identifier(121)),
        ("action", "delegated"),
        ("action", "transaction"),
        ("occurred_at", "2026-10-22T08:59:59+00:00"),
    ],
)
def test_revocation_audit_must_match_exact_grant_and_valid_time(field: str, value: Any) -> None:
    before = snapshot()
    current = revoke(before)
    current = change_row(current, "audit", len(seal(current).audit) - 1, **{field: value})
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, current)


def test_two_audit_events_for_one_new_revocation_refuse() -> None:
    before = snapshot()
    current = revoke(before)
    extra = {**seal(current).audit[-1], "id": identifier(999)}
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, amend(current, audit=[*seal(current).audit, extra]))


def test_two_new_revocations_cannot_share_one_audit_event() -> None:
    before = snapshot()
    current = change_row(revoke(before), "delegations", 1, revoked_at=REVOKED)
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, current)


@pytest.mark.parametrize(
    "field,value",
    [
        ("principal_id", identifier(111)),
        ("delegation_id", identifier(121)),
        ("action", "transaction"),
        ("occurred_at", "2026-10-22T08:00:01+00:00"),
    ],
)
def test_preexisting_audit_records_are_immutable(field: str, value: Any) -> None:
    before = snapshot()
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, change_row(before, "audit", **{field: value}))


def test_existing_audit_identifier_cannot_be_reused_for_new_revocation() -> None:
    before = snapshot()
    current = revoke(before)
    current = change_row(current, "audit", 4, id=seal(before).audit[0]["id"])
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, current)


@pytest.mark.parametrize("table", ["principals", "delegations", "audit"])
def test_service_rows_outside_captured_tenants_refuse(table: str) -> None:
    before = change_row(snapshot(), table, organization_id=identifier(999))
    with pytest.raises(RestoreRefused):
        validate_service_seal(before)


@pytest.mark.parametrize(
    "field,value",
    [
        ("principal_id", identifier(999)),
        ("resource_id", identifier(999)),
        ("initiator_id", identifier(999)),
        ("origin_session_hash", "f" * 64),
        ("source_id", "unrepresented-source"),
        ("policy_version", 99),
    ],
)
def test_delegation_with_missing_anchor_refuses(field: str, value: Any) -> None:
    before = change_row(snapshot(), "delegations", **{field: value})
    with pytest.raises(RestoreRefused):
        validate_service_seal(before)


@pytest.mark.parametrize("table", ["jobs", "exports", "memberships", "source_policies"])
def test_missing_captured_business_or_authority_anchor_refuses(table: str) -> None:
    before = snapshot()
    with pytest.raises(RestoreRefused):
        validate_service_seal(replace(before, rows={**before.rows, table: []}))


@pytest.mark.parametrize("table", ["jobs", "exports", "memberships", "source_policies"])
def test_malformed_captured_anchor_is_a_fixed_refusal(table: str) -> None:
    before = snapshot()
    with pytest.raises(RestoreRefused):
        validate_service_seal(replace(before, rows={**before.rows, table: [{}]}))


@pytest.mark.parametrize("field", ["identities", "sessions"])
def test_missing_captured_identity_or_session_anchor_refuses(field: str) -> None:
    before = snapshot()
    changes: dict[str, Any] = {field: []}
    with pytest.raises(RestoreRefused):
        validate_service_seal(replace(before, **changes))


def test_origin_session_must_belong_to_the_grant_initiator() -> None:
    before = snapshot()
    sessions = deepcopy(before.sessions)
    sessions[0]["identity_id"] = identifier(201)
    with pytest.raises(RestoreRefused):
        validate_service_seal(replace(before, sessions=sessions))


@pytest.mark.parametrize("index,resource", [(0, 202), (1, 203)])
def test_other_tenant_job_or_export_is_not_an_anchor(index: int, resource: int) -> None:
    before = change_row(snapshot(), "delegations", index, resource_id=identifier(resource))
    with pytest.raises(RestoreRefused):
        validate_service_seal(before)


@pytest.mark.parametrize("table", ["principals", "delegations", "audit"])
def test_malformed_service_uuid_is_a_fixed_refusal(table: str) -> None:
    before = change_row(snapshot(), table, id="private-invalid-identifier")
    with pytest.raises(RestoreRefused) as refused:
        validate_service_seal(before)
    assert "private-invalid-identifier" not in str(refused.value)


@pytest.mark.parametrize(
    "table,field,value",
    [
        ("principals", "active", "false"),
        ("principals", "active", 1),
        ("principals", "revision", True),
        ("principals", "revision", 0),
        ("principals", "revision", "1"),
        ("principals", "login_oid", True),
        ("principals", "login_oid", 0),
        ("principals", "login_oid", "110"),
        ("principals", "kind", "administrator"),
        ("delegations", "principal_revision", True),
        ("delegations", "generation", 0),
        ("delegations", "deletion_generation", -1),
        ("delegations", "permission_revision", "1"),
        ("delegations", "membership_revision", 0),
        ("delegations", "policy_version", True),
        ("delegations", "purpose", "download"),
        ("audit", "action", "unknown"),
    ],
)
def test_service_field_types_and_closed_values_are_checked(
    table: str, field: str, value: Any
) -> None:
    before = change_row(snapshot(), table, **{field: value})
    with pytest.raises(RestoreRefused):
        validate_service_seal(before)


@pytest.mark.parametrize(
    "table,field",
    [
        ("delegations", "issued_at"),
        ("delegations", "deadline"),
        ("delegations", "revoked_at"),
        ("audit", "occurred_at"),
    ],
)
@pytest.mark.parametrize("stamp", ["not-a-timestamp", "2026-10-22", "2026-10-22T09:00:00", 1])
def test_service_timestamps_must_be_aware_and_well_formed(
    table: str, field: str, stamp: Any
) -> None:
    before = change_row(snapshot(), table, **{field: stamp})
    with pytest.raises(RestoreRefused):
        validate_service_seal(before)


@pytest.mark.parametrize(
    "deadline", [ISSUED, "2026-10-22T07:59:59+00:00", "2026-10-22T14:00:01+00:00"]
)
def test_grant_deadline_must_fit_its_original_six_hour_wall(deadline: str) -> None:
    before = change_row(snapshot(), "delegations", deadline=deadline)
    with pytest.raises(RestoreRefused):
        validate_service_seal(before)


@pytest.mark.parametrize("field", ["roles", "catalog"])
def test_role_and_catalog_seals_cannot_drift(field: str) -> None:
    before = snapshot()
    current = amend(before, **{field: {"changed": [{"authority": "unrepresented"}]}})
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, current)


@pytest.mark.parametrize("table", EXPORT_TABLES)
def test_every_export_frontier_is_sealed_even_without_job_drift(table: str) -> None:
    before = snapshot()
    exports = {
        **seal(before).exports,
        table: [{"organization_id": identifier(100), "digest": "a" * 64}],
    }
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, amend(before, exports=exports))


@pytest.mark.parametrize("table", EXPORT_TABLES)
@pytest.mark.parametrize("operation", ["remove", "change"])
def test_existing_export_frontier_rows_cannot_disappear_or_change(
    table: str, operation: str
) -> None:
    before = snapshot()
    entry = {"organization_id": identifier(100), "digest": "a" * 64}
    before = amend(before, exports={**seal(before).exports, table: [entry]})
    supported_service_delta(before, deepcopy(before))
    changed = [] if operation == "remove" else [{**entry, "digest": "b" * 64}]
    with pytest.raises(RestoreRefused):
        supported_service_delta(
            before, amend(before, exports={**seal(before).exports, table: changed})
        )


@pytest.mark.parametrize("table", EXPORT_TABLES)
def test_missing_export_frontier_table_refuses(table: str) -> None:
    before = snapshot()
    exports = dict(seal(before).exports)
    del exports[table]
    with pytest.raises(RestoreRefused):
        validate_service_seal(amend(before, exports=exports))


def test_unknown_export_frontier_table_refuses() -> None:
    before = snapshot()
    with pytest.raises(RestoreRefused):
        validate_service_seal(amend(before, exports={**seal(before).exports, "unknown": []}))


@pytest.mark.parametrize("table", EXPORT_TABLES)
@pytest.mark.parametrize("case", ["foreign_tenant", "missing_digest", "bad_digest", "extra", "row"])
def test_export_frontier_rows_have_closed_shape_and_captured_tenant_scope(
    table: str, case: str
) -> None:
    before = snapshot()
    row: Any = {"organization_id": identifier(100), "digest": "a" * 64}
    if case == "foreign_tenant":
        row["organization_id"] = identifier(999)
    elif case == "missing_digest":
        del row["digest"]
    elif case == "bad_digest":
        row["digest"] = "a" * 65
    elif case == "extra":
        row["private"] = "synthetic-private-export-body"
    else:
        row = None
    with pytest.raises(RestoreRefused) as refused:
        validate_service_seal(amend(before, exports={**seal(before).exports, table: [row]}))
    assert "synthetic-private-export-body" not in str(refused.value)


@pytest.mark.parametrize("digest", ["a" * 63, "A" * 64, "g" * 64, "", None, 1, b"a" * 64])
def test_export_frontier_digest_is_exact_lowercase_sha256(digest: Any) -> None:
    before = snapshot()
    row = {"organization_id": identifier(100), "digest": digest}
    with pytest.raises(RestoreRefused):
        validate_service_seal(
            amend(before, exports={**seal(before).exports, "export_artifacts": [row]})
        )


@pytest.mark.parametrize("table", EXPORT_TABLES)
def test_export_frontier_row_caps_fail_closed(table: str) -> None:
    before = snapshot()
    rows = [{"organization_id": identifier(100), "digest": "a" * 64} for _ in range(501)]
    with pytest.raises(RestoreRefused, match="^restore_row_cap$"):
        validate_service_seal(amend(before, exports={**seal(before).exports, table: rows}))


@pytest.mark.parametrize("value", [{}, (), "", None])
def test_export_frontier_collection_must_be_a_row_list(value: Any) -> None:
    before = snapshot()
    with pytest.raises(RestoreRefused):
        validate_service_seal(
            amend(before, exports={**seal(before).exports, "export_artifacts": value})
        )


@pytest.mark.parametrize("table", ["memberships", "fixture_quota", "source_policy_heads"])
def test_service_profile_keeps_legacy_unreplayed_authority_refusals(table: str) -> None:
    before = snapshot()
    changed = (
        [{**before.rows[table][0], "unrepresented": True}]
        if before.rows[table]
        else [{"unrepresented": True}]
    )
    current = replace(before, rows={**before.rows, table: changed})
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, current)


def test_service_profile_keeps_legacy_business_frontier_refusal() -> None:
    before = snapshot()
    current = replace(
        before,
        frontier={
            "execution_runs": [
                {"organization_id": identifier(100), "job_id": identifier(102), "digest": "changed"}
            ]
        },
    )
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, current)


def test_legacy_delta_contract_is_still_separate_and_unchanged() -> None:
    before = SafetySnapshot((UUID(int=100), UUID(int=200)), {t: [] for t in TABLES}, [], [], [])
    supported_delta(before, deepcopy(before))
    with pytest.raises(RestoreRefused):
        supported_delta(before, replace(before, sessions=[{"unrepresented": True}]))


def test_legacy_capture_still_refuses_any_service_history_before_row_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This is a guard-order unit check; no connection or SQL is executed.
    connection = MagicMock()
    connection.execute.return_value.scalar_one.return_value = True
    engine = MagicMock(spec=Engine)
    engine.connect.return_value.execution_options.return_value.__enter__.return_value = connection
    capture_rows = MagicMock(side_effect=AssertionError("legacy profile crossed service guard"))
    monkeypatch.setattr("restore_exercise.capture_rows", capture_rows)
    with pytest.raises(RestoreRefused, match="^restore_service_authority_unsupported$"):
        capture(cast(Engine, engine), snapshot().organizations)
    capture_rows.assert_not_called()
    connection.execute.assert_called_once()
    statement = str(connection.execute.call_args.args[0])
    for table in ("service_principals", "service_delegations", "service_audit"):
        assert "EXISTS(SELECT 1 FROM emailmonitor." + table + ")" in statement
    assert " WHERE " not in statement


@pytest.mark.parametrize(
    "field", ["principals", "delegations", "audit", "roles", "catalog", "exports"]
)
def test_final_target_must_match_every_service_seal_field(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = snapshot()
    restored = final_drift(current, field)
    validate_service_seal(restored)
    target = object.__new__(ServiceRestoreExercise)
    closed = MagicMock()
    monkeypatch.setattr(target, "closed", closed)
    with pytest.raises(RestoreRefused, match="^restore_service_final_seal_mismatch$"):
        target.validate_final(current, current, restored)
    closed.assert_not_called()


def test_matching_final_target_still_requires_the_closed_database_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = snapshot()
    target = object.__new__(ServiceRestoreExercise)
    closed = MagicMock(side_effect=RestoreRefused("restore_service_closed_seal_refused"))
    monkeypatch.setattr(target, "closed", closed)
    with pytest.raises(RestoreRefused, match="^restore_service_closed_seal_refused$"):
        target.validate_final(current, current, deepcopy(current))
    closed.assert_called_once_with()


def test_matching_final_target_checks_closure_and_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    current = snapshot()
    target = object.__new__(ServiceRestoreExercise)
    closed = MagicMock()
    monkeypatch.setattr(target, "closed", closed)
    target.validate_final(current, current, deepcopy(current))
    closed.assert_called_once_with()


@pytest.mark.parametrize("field", ["organizations", "identities", "sessions", "catalog", "shared"])
def test_final_target_must_match_inherited_authority(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = snapshot()
    changes: dict[str, Any]
    if field == "organizations":
        changes = {field: tuple(reversed(current.organizations))}
    elif field == "shared":
        changes = {field: {"source_resource_buckets": []}}
    else:
        rows = deepcopy(getattr(current, field))
        if field == "identities":
            rows[0]["active"] = False
        elif field == "sessions":
            rows[0]["revoked_at"] = REVOKED
        else:
            rows[0]["enabled"] = False
        changes = {field: rows}
    target = object.__new__(ServiceRestoreExercise)
    closed = MagicMock()
    monkeypatch.setattr(target, "closed", closed)
    with pytest.raises(RestoreRefused, match="^restore_service_final_authority_mismatch$"):
        target.validate_final(current, current, replace(current, **changes))
    closed.assert_not_called()


@pytest.mark.parametrize("table", TABLES)
def test_final_target_requires_every_inherited_table(
    table: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = snapshot()
    rows = dict(current.rows)
    del rows[table]
    target = object.__new__(ServiceRestoreExercise)
    monkeypatch.setattr(target, "closed", MagicMock())
    with pytest.raises(RestoreRefused, match="^restore_service_final_authority_mismatch$"):
        target.validate_final(current, current, replace(current, rows=rows))


@pytest.mark.parametrize(
    "table,field,value",
    [
        ("organizations", "status", "suspended"),
        ("memberships", "row_version", 2),
        ("source_policy_heads", "current_version", 2),
        ("source_policies", "state", "revoked"),
        ("jobs", "state", "failed"),
        ("exports", "state", "revoked"),
    ],
)
def test_final_target_refuses_inherited_rows_changed_after_transaction_reconciliation(
    table: str, field: str, value: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = snapshot()
    rows = deepcopy(current.rows)
    rows[table][0][field] = value
    target = object.__new__(ServiceRestoreExercise)
    monkeypatch.setattr(target, "closed", MagicMock())
    with pytest.raises(RestoreRefused, match="^restore_service_final_authority_mismatch$"):
        target.validate_final(current, current, replace(current, rows=rows))


def test_final_target_refuses_an_unknown_inherited_table(monkeypatch: pytest.MonkeyPatch) -> None:
    current = snapshot()
    target = object.__new__(ServiceRestoreExercise)
    monkeypatch.setattr(target, "closed", MagicMock())
    with pytest.raises(RestoreRefused, match="^restore_service_final_authority_mismatch$"):
        target.validate_final(
            current, current, replace(current, rows={**current.rows, "unknown": []})
        )


def tombstoned_snapshot() -> ServiceSnapshot:
    value = snapshot()
    return replace(
        value,
        rows={
            **value.rows,
            "deletion_tombstones": [
                {
                    "organization_id": identifier(100),
                    "id": identifier(700),
                    "job_id": identifier(102),
                    "reason": "owner_request",
                    "stage": "purged",
                    "created_at": REVOKED,
                    "purged_at": AUDITED,
                }
            ],
        },
    )


def test_final_tombstones_allow_only_replayed_creation_and_purge_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = tombstoned_snapshot()
    rows = deepcopy(current.rows)
    rows["deletion_tombstones"][0].update(created_at=DEADLINE, purged_at=DEADLINE)
    target = object.__new__(ServiceRestoreExercise)
    closed = MagicMock()
    monkeypatch.setattr(target, "closed", closed)
    target.validate_final(snapshot(), current, replace(current, rows=rows))
    closed.assert_called_once_with()


@pytest.mark.parametrize(
    "field,value",
    [
        ("organization_id", identifier(200)),
        ("id", identifier(701)),
        ("job_id", None),
        ("reason", "retention_expired"),
        ("stage", "fenced"),
    ],
)
def test_final_tombstone_identity_scope_reason_and_stage_remain_exact(
    field: str, value: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = tombstoned_snapshot()
    rows = deepcopy(current.rows)
    rows["deletion_tombstones"][0][field] = value
    target = object.__new__(ServiceRestoreExercise)
    monkeypatch.setattr(target, "closed", MagicMock())
    with pytest.raises(RestoreRefused, match="^restore_service_final_authority_mismatch$"):
        target.validate_final(snapshot(), current, replace(current, rows=rows))


@pytest.mark.parametrize("field", ["created_at", "purged_at"])
def test_final_preexisting_purged_tombstone_timestamps_remain_exact(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = tombstoned_snapshot()
    rows = deepcopy(current.rows)
    rows["deletion_tombstones"][0][field] = DEADLINE
    target = object.__new__(ServiceRestoreExercise)
    monkeypatch.setattr(target, "closed", MagicMock())
    with pytest.raises(RestoreRefused):
        target.validate_final(current, current, replace(current, rows=rows))


def test_final_existing_fenced_marker_allows_only_newly_executed_purge_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = tombstoned_snapshot()
    before_rows = deepcopy(current.rows)
    before_rows["deletion_tombstones"][0].update(stage="fenced", purged_at=None)
    before = replace(current, rows=before_rows)
    supported_service_delta(before, current)
    restored_rows = deepcopy(current.rows)
    restored_rows["deletion_tombstones"][0]["purged_at"] = DEADLINE
    restored = replace(current, rows=restored_rows)
    target = object.__new__(ServiceRestoreExercise)
    closed = MagicMock()
    monkeypatch.setattr(target, "closed", closed)
    target.validate_final(before, current, restored)
    closed.assert_called_once_with()
    restored_rows["deletion_tombstones"][0]["created_at"] = DEADLINE
    with pytest.raises(RestoreRefused):
        target.validate_final(before, current, replace(current, rows=restored_rows))


def test_final_new_fenced_marker_allows_creation_time_but_keeps_null_purge_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = tombstoned_snapshot()
    current_rows = deepcopy(current.rows)
    current_rows["deletion_tombstones"][0].update(stage="fenced", purged_at=None)
    current = replace(current, rows=current_rows)
    restored_rows = deepcopy(current.rows)
    restored_rows["deletion_tombstones"][0]["created_at"] = DEADLINE
    target = object.__new__(ServiceRestoreExercise)
    monkeypatch.setattr(target, "closed", MagicMock())
    target.validate_final(snapshot(), current, replace(current, rows=restored_rows))
    restored_rows["deletion_tombstones"][0]["purged_at"] = DEADLINE
    with pytest.raises(RestoreRefused):
        target.validate_final(snapshot(), current, replace(current, rows=restored_rows))


@pytest.mark.parametrize(
    "field,value",
    [
        ("created_at", DEADLINE),
        ("purged_at", DEADLINE),
        ("purged_at", None),
        ("stage", "fenced"),
        ("reason", "retention_expired"),
        ("job_id", None),
    ],
)
def test_recorded_purged_tombstone_history_cannot_drift_during_supported_delta(
    field: str, value: Any
) -> None:
    before = tombstoned_snapshot()
    rows = deepcopy(before.rows)
    rows["deletion_tombstones"][0][field] = value
    with pytest.raises(RestoreRefused):
        supported_service_delta(before, replace(before, rows=rows))


@pytest.mark.parametrize(
    "field", ["principals", "delegations", "audit", "roles", "catalog", "exports"]
)
def test_injected_final_capture_drift_never_sets_replay_validated(
    field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mock only I/O/reconciliation, then run the actual replay orchestration.
    # This simulates a final-capture race, not a PostgreSQL concurrency proof.
    before = snapshot()
    current = deepcopy(before)
    restored = final_drift(current, field)
    target = object.__new__(ServiceRestoreExercise)
    target.created, target.ready, target.validated = True, False, False
    target.admin = cast(Engine, MagicMock(spec=Engine))
    target.target = cast(Engine, MagicMock(spec=Engine))
    target.current, target.target_seal, target.replay_seal = None, None, None
    captures = MagicMock(side_effect=[current, before, current, restored])
    monkeypatch.setattr(target, "capture", captures)
    monkeypatch.setattr(target, "closed", MagicMock())
    monkeypatch.setattr(target, "replay_authority", MagicMock())
    monkeypatch.setattr(target, "reconcile_authority", MagicMock())

    def rows(connection: Any, table: str, organizations: Any) -> list[dict[str, Any]]:
        return current.rows[table]

    monkeypatch.setattr("restore_exercise.records", rows)
    tokens = {org: "synthetic-replay-token" for org in current.organizations}
    with pytest.raises(RestoreRefused, match="^restore_service_final_seal_mismatch$"):
        target.replay(before, current, tokens)
    assert captures.call_count == 4
    assert not target.ready and not target.validated
    assert target.current is None and target.target_seal is None and target.replay_seal is None


@pytest.mark.parametrize("created,ready,validated", list(product((False, True), repeat=3)))
def test_service_target_never_opens_even_with_forged_lifecycle_flags(
    created: bool, ready: bool, validated: bool
) -> None:
    target = object.__new__(ServiceRestoreExercise)
    target.created, target.ready, target.validated = created, ready, validated
    with pytest.raises(RestoreRefused, match="^restore_service_target_must_remain_closed$"):
        target.open_after_validation()


@pytest.mark.parametrize("url", [RUNTIME, AUTH, "postgresql://foreign.example.invalid/live"])
@pytest.mark.parametrize("ready,validated", list(product((False, True), repeat=2)))
def test_service_target_never_exposes_an_application_url(
    url: str, ready: bool, validated: bool
) -> None:
    target = object.__new__(ServiceRestoreExercise)
    target.created, target.ready, target.validated = True, ready, validated
    with pytest.raises(RestoreRefused, match="^restore_service_target_must_remain_closed$"):
        target.url(url)


def test_service_seal_repr_and_snapshot_repr_never_reveal_private_state() -> None:
    secret = "private-synthetic-service-secret"
    value = snapshot()
    value = replace(
        value,
        rows={**value.rows, "privacy_keys": [{"key": secret}]},
        sessions=[{"token_hash": secret}],
        service=ServiceSeal(
            principals=[{"login_name": secret}],
            delegations=[{"origin_session_hash": secret}],
            audit=[{"private": secret}],
            roles={"private": [{"secret": secret}]},
            catalog={"private": [{"secret": secret}]},
            exports={"private": [{"body": secret}]},
        ),
    )
    assert secret not in repr(value)
    assert secret not in repr(seal(value))
    assert all(not field.repr for field in fields(ServiceSeal))
    assert next(field for field in fields(ServiceSnapshot) if field.name == "service").repr is False


@pytest.mark.parametrize(
    "field", ["principals", "delegations", "audit", "roles", "catalog", "exports"]
)
def test_fingerprint_seals_every_private_service_field_despite_redacted_repr(field: str) -> None:
    before = snapshot()
    changed = deepcopy(getattr(seal(before), field))
    if isinstance(changed, list):
        changed[0]["private-synthetic-change"] = True
    else:
        changed["private-synthetic-change"] = [{"changed": True}]
    current = amend(before, **{field: changed})
    assert repr(before) == repr(current)
    assert repr(seal(before)) == repr(seal(current))
    assert fingerprint(before) == fingerprint(deepcopy(before))
    assert fingerprint(before) != fingerprint(current)


def test_service_rows_projects_only_principal_oid_to_bigint_and_retains_the_full_row() -> None:
    # The mocked driver supplies the projected value. This checks SQL shape and
    # passthrough only; it does not prove PostgreSQL's actual OID serialization.
    rows = deepcopy(seal(snapshot()).principals)
    connection = MagicMock(spec=Connection)
    connection.execute.return_value.mappings.return_value.all.return_value = [
        {"record": row} for row in rows
    ]
    actual = service_rows(cast(Connection, connection), "service_principals")
    assert actual == rows and type(actual[0]["login_oid"]) is int
    connection.execute.assert_called_once()
    assert str(connection.execute.call_args.args[0]) == (
        "SELECT (row_to_json(t)::jsonb || "
        "jsonb_build_object('login_oid',t.login_oid::bigint)) AS record "
        "FROM emailmonitor.service_principals t ORDER BY organization_id,id LIMIT 501"
    )


@pytest.mark.parametrize(
    "table,field", [("service_delegations", "delegations"), ("service_audit", "audit")]
)
def test_service_rows_keeps_other_authority_queries_and_all_fields_unchanged(
    table: str, field: str
) -> None:
    rows = deepcopy(getattr(seal(snapshot()), field))
    connection = MagicMock(spec=Connection)
    connection.execute.return_value.mappings.return_value.all.return_value = [
        {"record": row} for row in rows
    ]
    assert service_rows(cast(Connection, connection), table) == rows
    connection.execute.assert_called_once()
    assert str(connection.execute.call_args.args[0]) == (
        f"SELECT row_to_json(t) AS record FROM emailmonitor.{table} t "
        "ORDER BY organization_id,id LIMIT 501"
    )


@pytest.mark.parametrize(
    "table,field",
    [
        ("service_principals", "principals"),
        ("service_delegations", "delegations"),
        ("service_audit", "audit"),
    ],
)
def test_service_rows_inherits_the_bounded_reader_cap(table: str, field: str) -> None:
    row = getattr(seal(snapshot()), field)[0]
    connection = MagicMock(spec=Connection)
    connection.execute.return_value.mappings.return_value.all.return_value = [
        {"record": deepcopy(row)} for _ in range(501)
    ]
    with pytest.raises(RestoreRefused, match="^restore_row_cap$"):
        service_rows(cast(Connection, connection), table)
    connection.execute.assert_called_once()
    assert str(connection.execute.call_args.args[0]).endswith(" LIMIT 501")


@pytest.mark.parametrize(
    "table", ["jobs", "public.service_principals", "service_principals;SELECT 1", ""]
)
def test_service_rows_refuses_unlisted_tables_before_any_query(table: str) -> None:
    connection = MagicMock(spec=Connection)
    with pytest.raises(RestoreRefused, match="^restore_service_table_refused$"):
        service_rows(cast(Connection, connection), table)
    connection.execute.assert_not_called()


def diagnostic_snapshot() -> ServiceSnapshot:
    return amend(
        snapshot(),
        roles={"roles": [], "memberships": []},
        catalog={key: [] for key in CATALOG_QUERIES},
    )


def test_snapshot_difference_sections_is_empty_for_identical_capture() -> None:
    before = diagnostic_snapshot()
    assert snapshot_difference_sections(before, deepcopy(before)) == []


@pytest.mark.parametrize(
    "field", ["organizations", "identities", "sessions", "catalog", "rows", "shared", "frontier"]
)
def test_snapshot_difference_sections_localizes_inherited_sections_without_values(
    field: str,
) -> None:
    before = diagnostic_snapshot()
    changes: dict[str, Any]
    if field == "organizations":
        changes = {field: tuple(reversed(before.organizations))}
    elif field in ("identities", "sessions", "catalog"):
        rows = deepcopy(getattr(before, field))
        column = {"identities": "active", "sessions": "revoked_at", "catalog": "enabled"}[field]
        rows[0][column] = REVOKED if field == "sessions" else False
        changes = {field: rows}
    else:
        tables = deepcopy(getattr(before, field))
        if field == "rows":
            tables["jobs"][0]["state"] = "failed"
        elif field == "shared":
            tables["source_resource_buckets"] = []
        else:
            tables["execution_runs"] = [
                {"organization_id": identifier(100), "job_id": identifier(102), "digest": "a" * 64}
            ]
        changes = {field: tables}
    assert snapshot_difference_sections(before, replace(before, **changes)) == [field]


@pytest.mark.parametrize("field", ["principals", "delegations", "audit"])
def test_snapshot_difference_sections_localizes_service_rows_without_values(field: str) -> None:
    before = diagnostic_snapshot()
    assert snapshot_difference_sections(before, final_drift(before, field)) == ["service." + field]


@pytest.mark.parametrize(
    "section,key",
    [
        *(("roles", key) for key in ("roles", "memberships")),
        *(("catalog", key) for key in CATALOG_QUERIES),
        *(("exports", key) for key in EXPORT_TABLES),
    ],
)
def test_snapshot_difference_sections_uses_only_fixed_subsection_labels(
    section: str, key: str
) -> None:
    before = diagnostic_snapshot()
    values = deepcopy(getattr(seal(before), section))
    values[key] = [{"private-synthetic-key": "private-synthetic-value"}]
    restored = amend(before, **{section: values})
    assert snapshot_difference_sections(before, restored) == ["service." + section + "." + key]


@pytest.mark.parametrize("section", ["roles", "catalog", "exports"])
@pytest.mark.parametrize("operation", ["add", "remove", "change"])
def test_snapshot_difference_sections_never_leaks_unknown_keys_or_their_values(
    section: str, operation: str
) -> None:
    before = diagnostic_snapshot()
    old = deepcopy(getattr(seal(before), section))
    new = deepcopy(old)
    private_key = "private-synthetic-unknown-section"
    if operation in ("remove", "change"):
        old[private_key] = [{"secret": "private-synthetic-before"}]
    if operation in ("add", "change"):
        new[private_key] = [{"secret": "private-synthetic-after"}]
    before = amend(before, **{section: old})
    restored = amend(before, **{section: new})
    assert fingerprint(before) != fingerprint(restored)
    assert snapshot_difference_sections(before, restored) == ["service." + section + ".shape"]


@pytest.mark.parametrize("section", ["roles", "catalog", "exports"])
def test_snapshot_difference_sections_sanitizes_a_nondictionary_section(section: str) -> None:
    before = diagnostic_snapshot()
    restored = amend(before, **{section: "private-synthetic-invalid-section"})
    assert snapshot_difference_sections(before, restored) == ["service." + section + ".shape"]


def test_snapshot_difference_sections_detects_integer_boolean_serialization_difference() -> None:
    before = diagnostic_snapshot()
    restored = change_row(before, "principals", revision=True)
    assert seal(before).principals == seal(restored).principals
    assert fingerprint(before) != fingerprint(restored)
    assert snapshot_difference_sections(before, restored) == ["service.principals"]


def test_snapshot_difference_sections_has_fixed_order_independent_of_dictionary_insertion() -> None:
    before = diagnostic_snapshot()
    restored = change_row(before, "principals", active=False, revision=2)
    identities = deepcopy(before.identities)
    identities[0]["active"] = False
    rows = deepcopy(before.rows)
    rows["jobs"][0]["state"] = "failed"
    restored = replace(restored, identities=identities, rows=rows)
    for section, keys in (
        ("roles", ("memberships", "roles")),
        ("catalog", ("revision_acl", "schemas")),
        ("exports", ("export_events", "export_members")),
    ):
        values = dict(reversed(list(getattr(seal(restored), section).items())))
        for key in keys:
            values[key] = [{"private-synthetic-value": "never printed"}]
        restored = amend(restored, **{section: values})
    expected = [
        "identities",
        "rows",
        "service.principals",
        "service.roles.roles",
        "service.roles.memberships",
        "service.catalog.schemas",
        "service.catalog.revision_acl",
        "service.exports.export_members",
        "service.exports.export_events",
    ]
    assert snapshot_difference_sections(before, restored) == expected
    assert snapshot_difference_sections(restored, before) == expected


def test_relation_catalog_sql_normalizes_only_null_supported_relation_acls() -> None:
    # SQL-source contract only: actual dump/restore ACL equivalence requires
    # PostgreSQL acceptance. COALESCE leaves an explicit empty ACL untouched.
    query = " ".join(CATALOG_QUERIES["relations"].split())
    assert (
        "CASE WHEN c.relkind IN ('r','p','v','m','f','S') THEN "
        "COALESCE(c.relacl,acldefault( "
        "CASE WHEN c.relkind='S' THEN 's'::\"char\" ELSE 'r'::\"char\" END,c.relowner)) "
        "ELSE c.relacl END"
    ) in query
    assert "NULLIF" not in query.upper()
    assert "c.relrowsecurity" in query and "c.relforcerowsecurity" in query

"""Pure restore admission/state grammar; no databases, dumps or network execution."""

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from restore_exercise import (
    ADMIN,
    AUTH,
    RUNTIME,
    TABLES,
    RestoreExercise,
    RestoreRefused,
    SafetySnapshot,
    database_name,
    require_ci,
    supported_delta,
)


def environment() -> dict[str, str]:
    return {
        "GITHUB_ACTIONS": "true",
        "EM_REQUIRE_SYNTHETIC_RESTORE": "true",
        "EM_TEST_ADMIN_DATABASE_URL": ADMIN,
        "EM_TEST_DATABASE_URL": RUNTIME,
        "EM_TEST_AUTH_DATABASE_URL": AUTH,
        "EM_TEST_POSTGRES_CONTAINER": "a" * 64,
    }


def snapshot() -> SafetySnapshot:
    return SafetySnapshot((uuid4(), uuid4()), {table: [] for table in TABLES}, [], [], [])


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_ACTIONS", "false"),
        ("EM_REQUIRE_SYNTHETIC_RESTORE", "false"),
        ("EM_TEST_ADMIN_DATABASE_URL", ADMIN.replace("127.0.0.1", "live.example.org")),
        ("EM_TEST_DATABASE_URL", ADMIN),
        ("EM_TEST_AUTH_DATABASE_URL", RUNTIME),
        ("EM_TEST_POSTGRES_CONTAINER", "foreign;rm -rf /"),
    ],
)
def test_restore_environment_refuses_ambient_or_foreign_targets(key: str, value: str) -> None:
    env = environment()
    env[key] = value
    with pytest.raises(RestoreRefused):
        require_ci(env)


def test_exact_disposable_context_and_database_grammar() -> None:
    assert require_ci(environment()) == "a" * 64
    assert database_name("em_restore_" + "a" * 32).startswith("em_restore_")


@pytest.mark.parametrize(
    "name", ["postgres", "customer", "em_restore_", "em_restore_" + "a" * 32 + '"']
)
def test_unknown_database_name_refuses(name: str) -> None:
    with pytest.raises(RestoreRefused):
        database_name(name)


@pytest.mark.parametrize(
    "table",
    ["memberships", "source_policy_heads", "resolution_accounts", "usage_events", "fixture_quota"],
)
def test_unreplayed_authority_or_accounting_drift_refuses(table: str) -> None:
    before = snapshot()
    current = replace(before, rows={**before.rows, table: [{"new": "unrepresented"}]})
    with pytest.raises(RestoreRefused):
        supported_delta(before, current)


@pytest.mark.parametrize("field", ["identities", "sessions", "catalog"])
def test_unreplayed_security_state_refuses(field: str) -> None:
    before = snapshot()
    updates: dict[str, Any] = {field: [{"changed": True}]}
    with pytest.raises(RestoreRefused):
        supported_delta(before, replace(before, **updates))


def test_missing_post_backup_job_anchor_refuses() -> None:
    before = snapshot()
    current = replace(before, rows={**before.rows, "jobs": [{"organization_id": "a", "id": "new"}]})
    with pytest.raises(RestoreRefused):
        supported_delta(before, current)


def test_open_and_url_are_unavailable_before_replay_validation() -> None:
    # Actual methods' guards run before touching any connection or subprocess.
    target = object.__new__(RestoreExercise)
    target.created, target.ready, target.validated = True, False, False
    with pytest.raises(RestoreRefused):
        target.open_after_validation()
    with pytest.raises(RestoreRefused):
        target.url(RUNTIME)


def test_snapshot_repr_never_includes_private_rows() -> None:
    value = replace(snapshot(), sessions=[{"secret": "private-session"}])
    assert "private-session" not in repr(value)


def test_restore_uses_same_pinned_service_tools_and_preserves_roles() -> None:
    source = (Path(__file__).parents[3] / "tests/restore_exercise.py").read_text()
    assert '"--exit-on-error"' in source and '"--single-transaction"' in source
    assert '"--format=custom"' in source
    for forbidden in (
        "--no-owner",
        "--no-acl",
        "--disable-triggers",
        "session_replication_role",
        "CREATE ROLE",
    ):
        assert forbidden not in source


@pytest.mark.parametrize("table", ["privacy_suppressions", "deletion_tombstones"])
def test_removed_safety_marker_never_makes_restore_ready(table: str) -> None:
    before = snapshot()
    rows = {**before.rows, table: [{"organization_id": "a", "id": "marker"}]}
    before = replace(before, rows=rows)
    with pytest.raises(RestoreRefused):
        supported_delta(before, replace(before, rows={**rows, table: []}))


def test_retention_deadline_cannot_move_later_during_replay() -> None:
    before = snapshot()
    row = {
        "organization_id": "a",
        "job_id": "job",
        "contact_deadline": "2026-01-01",
        "excerpt_deadline": "2026-01-01",
    }
    before = replace(before, rows={**before.rows, "lifecycle_job_deadlines": [row]})
    with pytest.raises(RestoreRefused):
        supported_delta(
            before,
            replace(
                before,
                rows={
                    **before.rows,
                    "lifecycle_job_deadlines": [{**row, "contact_deadline": "2027-01-01"}],
                },
            ),
        )


def test_privacy_key_must_remain_paired_with_captured_digest() -> None:
    before = snapshot()
    before = replace(
        before, rows={**before.rows, "privacy_keys": [{"organization_id": "a", "key": "old"}]}
    )
    with pytest.raises(RestoreRefused):
        supported_delta(
            before,
            replace(
                before,
                rows={**before.rows, "privacy_keys": [{"organization_id": "a", "key": "new"}]},
            ),
        )


@pytest.mark.parametrize("state", ["approved", "pending_review"])
def test_replay_cannot_expand_captured_source_permission(state: str) -> None:
    before = snapshot()
    row = {
        "organization_id": "a",
        "source_id": "synthetic-publisher",
        "version": 1,
        "policy": {},
        "created_by": "owner",
        "valid_until": "2026-01-01",
        "state": "revoked",
    }
    before = replace(before, rows={**before.rows, "source_policies": [row]})
    with pytest.raises(RestoreRefused):
        supported_delta(
            before,
            replace(before, rows={**before.rows, "source_policies": [{**row, "state": state}]}),
        )


def test_modified_archive_refuses_before_database_creation(tmp_path: Path) -> None:
    import hashlib

    target = object.__new__(RestoreExercise)
    target.created, target.ready = False, False
    target.archive = tmp_path / "owned.dump"
    target.archive.write_bytes(b"original")
    target.archive.chmod(0o600)
    target.archive_digest = hashlib.sha256(b"different").hexdigest()
    with pytest.raises(RestoreRefused, match="restore_archive_integrity_refused"):
        target.restore_closed()
    assert not target.created


@pytest.mark.parametrize("program", ["pg_dump", "pg_restore"])
@pytest.mark.parametrize("suffix", ["", " (Debian 17.11-1.pgdg12+1)"])
def test_exact_upstream_tool_version_accepts_bundled_debian_suffix(
    program: str, suffix: str
) -> None:
    from restore_exercise import require_tool_version

    require_tool_version(program, f"{program} (PostgreSQL) 17.11{suffix}")


@pytest.mark.parametrize(
    "value", ["17.12", "17.11extra", "17.11 (Debian 18.1-1)", "17.11\nignored"]
)
def test_tool_version_refuses_other_or_unbounded_output(value: str) -> None:
    from restore_exercise import require_tool_version

    with pytest.raises(RestoreRefused):
        require_tool_version("pg_dump", "pg_dump (PostgreSQL) " + value)


def test_org_content_tombstone_is_explicitly_outside_partial_profile() -> None:
    before = snapshot()
    current = replace(before, rows={**before.rows, "deletion_tombstones": [{"job_id": None}]})
    with pytest.raises(RestoreRefused, match="restore_org_tombstone_unsupported"):
        supported_delta(before, current)


@pytest.mark.parametrize(
    "table", ["execution_runs", "association_reviews", "association_outbox", "discovery"]
)
def test_unreplayed_business_frontier_refuses_even_with_same_job_anchors(table: str) -> None:
    before = snapshot()
    current = replace(
        before, frontier={table: [{"organization_id": "a", "job_id": "j", "digest": "changed"}]}
    )
    with pytest.raises(RestoreRefused, match="restore_unreplayed_business_frontier"):
        supported_delta(before, current)


def test_missing_privacy_key_is_not_silently_recreated_from_stale_archive() -> None:
    before = snapshot()
    before = replace(
        before, rows={**before.rows, "privacy_keys": [{"organization_id": "a", "key": "old"}]}
    )
    with pytest.raises(RestoreRefused, match="restore_privacy_key_change_refused"):
        supported_delta(before, replace(before, rows={**before.rows, "privacy_keys": []}))

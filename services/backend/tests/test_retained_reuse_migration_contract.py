"""Static migration contracts; no database or concurrency acceptance is implied."""

import importlib.util
import re
from pathlib import Path

import pytest
import sqlparse

ROOT = Path(__file__).resolve().parents[3]
VERSIONS = ROOT / "services/backend/migrations/versions"
SQL = (VERSIONS / "0022_retained_reuse.sql").read_text()


def function(source: str, name: str) -> str:
    match = re.search(
        r"CREATE (?:OR REPLACE )?FUNCTION emailmonitor\." + name + r"\([^\n]+\).*?\$\$;",
        source,
        re.S,
    )
    assert match is not None
    return match.group().replace("CREATE FUNCTION ", "CREATE OR REPLACE FUNCTION ", 1)


def test_existing_lifecycle_predicates_are_retained_and_narrowed() -> None:
    for name, prior in (
        ("privacy_job_allowed", "0011_lifecycle.sql"),
        ("privacy_job_state", "0014_service_authority.sql"),
    ):
        original = function((VERSIONS / prior).read_text(), name)
        updated = function(SQL, name)
        assert (
            updated.replace(" AND emailmonitor.retained_reuse_current(p_org,p_job)\n", "")
            == original
        )


def test_lineage_is_same_tenant_immutable_and_disabled_by_default() -> None:
    assert "FOREIGN KEY(organization_id,reused_from_job,article_url)" in SQL
    assert "FOREIGN KEY(organization_id,reused_source_batch)" in SQL
    assert "reused_from_job<>job_id" in SQL
    assert "source.reused_from_job IS NOT NULL" in SQL
    assert "prior.reused_from_job IS NOT NULL" in SQL
    assert "OLD.reused_from_job IS NOT NULL" in SQL
    assert "source.observation IS DISTINCT FROM NEW.observation" in SQL
    assert "source.source_digest<>NEW.source_digest" in SQL
    assert "d.checkpoint->'articles' IS DISTINCT FROM jsonb_build_array(NEW.article_url)" in SQL
    assert "NEW.observed_at:=source.observed_at" in SQL
    assert "NEW.expires_at:=LEAST(source.expires_at,b.expires_at)" in SQL
    assert "emailmonitor.privacy_excerpt_allowed" in SQL
    assert "retained_reuse_disabled CHECK" in SQL
    assert (
        "reused_from_job IS NULL AND reused_source_revision IS NULL AND reused_source_batch IS NULL"
        in SQL
    )
    assert not re.search(r"\bGRANT\s", SQL, re.I)


def test_source_privacy_fence_does_not_treat_policy_revocation_as_expiry() -> None:
    source = function(SQL, "retained_reuse_current")
    assert "emailmonitor.privacy_job_state(p_org,s.job_id)" in source
    assert "emailmonitor.publication_batch_state" not in source
    assert "t.expires_at>clock_timestamp()" in source


def test_cleanup_is_bounded_and_source_cannot_be_reported_purged_first() -> None:
    purge = function(SQL, "lifecycle_purge")
    assert "a.reused_from_job=marker.job_id ORDER BY a.job_id LIMIT 10" in purge
    assert purge.index("lifecycle_purge_job(p_org,item.job_id)") < purge.index(
        "lifecycle_purge_job(p_org,marker.job_id)"
    )
    assert "RETURN emailmonitor.lifecycle_receipt(p_org,p_id)" in purge
    assert "ORDER BY CASE WHEN EXISTS" in purge
    assert "lifecycle.fenced" in purge and "lifecycle.purged" in purge


def test_result_provenance_is_added_only_for_reused_observations() -> None:
    contact = function(SQL, "result_contact_document")
    outcome = function(SQL, "result_outcome_document")
    assert "CASE WHEN obs.reused_from_job IS NOT NULL" in contact
    assert "jsonb_build_object('observation_origin','reused') ELSE '{}'::jsonb END" in contact
    assert "CASE WHEN obs.reused_from_job IS NOT NULL" in outcome
    assert "'observation_origin','reused','observed_at',obs.observed_at" in outcome
    publication = function(SQL, "publication_outcome_state")
    projection = (
        "CASE WHEN obs.reused_from_job IS NOT NULL THEN "
        "jsonb_build_object('observation_origin','reused','observed_at',obs.observed_at) "
        "ELSE '{}'::jsonb END"
    )
    assert projection in outcome and projection in publication
    assert "emailmonitor.publication_job_state(p_org,p_job)" in publication


def test_start_refuses_reuse_without_current_materialized_input() -> None:
    start = function(SQL, "execution_start")
    assert "j.request ? 'reuse' AND NOT EXISTS" in start
    assert "a.reused_from_job IS NOT NULL" in start
    assert "emailmonitor.retained_reuse_current(p_org,p_job)" in start


def test_unsupported_reuse_continuation_refuses_before_creating_child() -> None:
    retry = function(SQL, "execution_retry")
    assert "emailmonitor.execution_control_fence(p_org,p_job)" in retry
    assert "j.request ? 'reuse'" in retry
    assert retry.index("EXECUTION_RETRY_DENIED") < retry.index("execution_retry_pre_entitlement")


def test_reuse_audit_requires_current_human_job_and_link() -> None:
    audit = function(SQL, "work_audit")
    assert "p_action='extraction.retained_reused'" in audit
    assert "emailmonitor.human_work_tenant_allowed(p_org)" in audit
    assert "emailmonitor.job_write_allowed(p_org,p_resource)" in audit
    assert "a.reused_from_job IS NOT NULL" in audit
    assert "emailmonitor.retained_reuse_current(p_org,p_resource)" in audit


def test_migration_is_forward_only_and_sql_statements_are_closed() -> None:
    path = VERSIONS / "0022_retained_reuse.py"
    spec = importlib.util.spec_from_file_location("reuse_migration_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0022_retained_reuse"
    assert module.down_revision == "0021_review_unlink"
    with pytest.raises(RuntimeError, match="forward repair"):
        module.downgrade()
    statements = sqlparse.split(SQL)
    assert statements[0].endswith("SET ROLE emailmonitor_owner;")
    assert statements[-1] == "RESET ROLE;"
    assert "'0022_retained_reuse'" in SQL

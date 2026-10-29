"""Real PostgreSQL schema checks; missing disposable URLs are explicit skips."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from emailmonitor.administration.admission import Admission
from emailmonitor.associations.reuse_materialization import materialize_draft
from emailmonitor.associations.reuse_preparation import prepare_reuse
from emailmonitor.associations.service import Associations
from emailmonitor.discovery.service import Discovery
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.lifecycle.models import DeletionRequest
from emailmonitor.lifecycle.service import Lifecycle
from emailmonitor.organizations.database import AuthorizationDenied, Database, TenantContext
from emailmonitor.organizations.roles import Capability
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_association_tenant import URL, prepared
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def test_actual_reuse_schema_preserves_runtime_grants(scenario: Scenario) -> None:
    service, job, batch = prepared(scenario)
    org = scenario.organizations[0]
    with service.database.tenant(service.token, org, Capability.READ_ORGANIZATION) as (c, _):
        row = c.execute(
            text(
                "SELECT reused_from_job,reused_source_revision,reused_source_batch "
                "FROM emailmonitor.article_observations "
                "WHERE organization_id=:org AND job_id=:job AND article_url=:url"
            ),
            {"org": org, "job": job, "url": URL},
        ).one()
        assert tuple(row) == (None, None, None)
        names: set[str] = set(
            c.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid='emailmonitor.article_observations'::regclass "
                    "AND conname LIKE 'retained_reuse_%'"
                )
            ).scalars()
        )
        assert names >= {
            "retained_reuse_shape",
            "retained_reuse_source_observation_fk",
            "retained_reuse_source_batch_fk",
        }
        # The current migration enables this candidate; the separate 0022
        # baseline receipt checked the disabled constraint before upgrading.
        assert "retained_reuse_disabled" not in names
        assert not c.execute(
            text(
                "SELECT has_function_privilege(current_user, "
                "'emailmonitor.retained_reuse_current(uuid,uuid)', 'EXECUTE')"
            )
        ).scalar_one()
    assert service.detail(org, batch).associations


def target_request_for_sql_guard_test(
    service: Associations, org: UUID, fresh_since: str = "2000-01-01T00:00:00Z", url: str = URL
) -> UUID:
    target = uuid4()
    body = {
        **request_body(),
        "input": {"type": "url", "url": url},
        "reuse": {"mode": "verified_retained", "fresh_since": fresh_since},
    }
    # Exercise the runtime SQL boundary directly; this does not bypass any
    # database predicate or provide a service identity.
    with service.database.tenant(service.token, org, Capability.ACQUIRE_SOURCE) as (c, ctx):
        assert isinstance(ctx, TenantContext)
        c.execute(
            text(
                "INSERT INTO emailmonitor.jobs (organization_id,id,created_by,kind,request,state) "
                "VALUES(:org,:job,:actor,'extraction',CAST(:body AS jsonb),'draft')"
            ),
            {"org": org, "job": target, "actor": ctx.identity_id, "body": json.dumps(body)},
        )
    discovery = Discovery(service.database, service.token, SETTINGS)
    discovery.plan(org, target, 1)
    return target


@pytest.mark.parametrize(
    "mutation",
    [
        "valid_but_disabled",
        "same_job",
        "wrong_batch",
        "stale_revision",
        "other_job",
        "cross_tenant",
        "reused_source",
    ],
)
def test_actual_runtime_lineage_forgery_refuses_before_any_target_copy(
    scenario: Scenario, mutation: str
) -> None:
    service, source_job, batch = prepared(scenario)
    org = scenario.organizations[0]
    if mutation == "valid_but_disabled":
        with service.database.tenant(service.token, org, Capability.READ_ORGANIZATION) as (c, _):
            disabled: bool = c.execute(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_constraint "
                    "WHERE conrelid='emailmonitor.article_observations'::regclass "
                    "AND conname='retained_reuse_disabled')"
                )
            ).scalar_one()
        if not disabled:
            pytest.skip("The disabled-link baseline applies to migration 0022 only")
    foreign_job, foreign_batch = uuid4(), uuid4()
    if mutation == "cross_tenant":
        identities = dict(scenario.identities)
        identities["owner"], identities["owner_b"] = identities["owner_b"], identities["owner"]
        foreign_scenario = replace(
            scenario, organizations=(scenario.organizations[1], org), identities=identities
        )
        _, foreign_job, foreign_batch = prepared(foreign_scenario)
    if mutation == "reused_source":
        foreign_job = target_request_for_sql_guard_test(service, org)
        assert materialize_draft(service, org, foreign_job, URL) == batch
        foreign_batch = service.derive(org, foreign_job, URL, 1)
    target = target_request_for_sql_guard_test(service, org)
    with service.database.tenant(service.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
        source = (
            c.execute(
                text(
                    "SELECT * FROM emailmonitor.article_observations "
                    "WHERE organization_id=:org AND job_id=:job AND article_url=:url"
                ),
                {"org": org, "job": source_job, "url": URL},
            )
            .mappings()
            .one()
        )
        target_row = Ledger._lock(c, org, target)
        checkpoint: int = c.execute(
            text(
                "SELECT revision FROM emailmonitor.discovery "
                "WHERE organization_id=:org AND job_id=:job"
            ),
            {"org": org, "job": target},
        ).scalar_one()
    params = {
        "org": org,
        "job": target,
        "url": URL,
        "generation": target_row["generation"],
        "deletion": target_row["deletion_generation"],
        "source": source["source_id"],
        "policy": source["policy_version"],
        "discovery": checkpoint,
        "digest": source["source_digest"],
        "observation": json.dumps(source["observation"]),
        "source_job": target
        if mutation == "same_job"
        else foreign_job
        if mutation in ("other_job", "cross_tenant", "reused_source")
        else source_job,
        "source_revision": int(source["revision"]) + (1 if mutation == "stale_revision" else 0),
        "source_batch": uuid4()
        if mutation == "wrong_batch"
        else foreign_batch
        if mutation in ("cross_tenant", "reused_source")
        else batch,
    }
    with pytest.raises(DBAPIError) as failure:
        with Admission(service.database, service.token, SETTINGS).fixture(org, target, URL):
            with service.database.tenant(service.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
                c.execute(
                    text("""
INSERT INTO emailmonitor.article_observations
(organization_id,job_id,article_url,generation,deletion_generation,source_id,policy_version,
 discovery_revision,source_digest,observation,reused_from_job,reused_source_revision,reused_source_batch)
VALUES(:org,:job,:url,:generation,:deletion,:source,:policy,:discovery,:digest,
 CAST(:observation AS jsonb),:source_job,:source_revision,:source_batch)
                """),
                    params,
                )
    original = failure.value.orig
    code = getattr(original, "sqlstate", None)
    if (
        code is None
        and original is not None
        and original.args
        and isinstance(original.args[0], dict)
    ):
        code = original.args[0].get("C")
    assert code == ("23514" if mutation == "valid_but_disabled" else "EM009")
    with service.database.tenant(service.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.article_observations "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": target},
            ).scalar_one()
            == 0
        )
    assert service.detail(org, batch).associations


def test_actual_source_delete_serializes_with_preparation(scenario: Scenario) -> None:
    service, source_job, batch = prepared(scenario)
    org = scenario.organizations[0]
    target = target_request_for_sql_guard_test(service, org)
    # Use a distinct one-connection pool so the concurrent transaction reaches
    # PostgreSQL instead of waiting for the preparation transaction's pool slot.
    second_database = Database(os.environ["EM_TEST_DATABASE_URL"])
    lifecycle = Lifecycle(second_database, service.token, SETTINGS)
    request = DeletionRequest(job_id=source_job, reason="privacy_request")
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            with service.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
                proposal = prepare_reuse(c, service, org, target, URL, batch)
                assert proposal.lineage.source_job_id == source_job
                with pytest.raises(DBAPIError) as blocked:
                    workers.submit(lifecycle.stage, org, request).result(timeout=5)
                original = blocked.value.orig
                code = getattr(original, "sqlstate", None)
                if (
                    code is None
                    and original is not None
                    and original.args
                    and isinstance(original.args[0], dict)
                ):
                    code = original.args[0].get("C")
                assert code == "55P03"
        assert lifecycle.stage(org, request).stage == "fenced"
        with pytest.raises(AuthorizationDenied):
            with service.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
                prepare_reuse(c, service, org, target, URL, batch)
    finally:
        second_database.engine.dispose()

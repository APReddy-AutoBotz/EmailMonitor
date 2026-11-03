"""Actual database baseline: independent reuse is not yet authorized or persisted."""

from datetime import timedelta
from uuid import uuid4

import pytest
from emailmonitor.associations.reuse_draft import independent_review_draft
from emailmonitor.associations.reuse_lineage import ReuseLineageDraft
from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.roles import Capability
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_association_tenant import URL, prepared, review_request
from test_durable_jobs import SETTINGS
from test_job_contracts import request_body
from test_tenant_foundation import Scenario
from test_tenant_foundation import scenario as scenario


def test_real_cross_job_copy_refused_and_review_draft_is_independent(scenario: Scenario) -> None:
    service, original_job, original_batch = prepared(scenario)
    org = scenario.organizations[0]
    source = service.review(
        org, original_batch, review_request(service, org, original_batch, action="reject")
    )
    assert source.associations[0].state == "rejected"
    ledger = Ledger(service.database, service.token, SETTINGS)
    target_job = ledger.create(org, JobRequest.model_validate(request_body()), str(uuid4()))
    target_batch = uuid4()
    with service.database.tenant(service.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
        service._lock(c, org, original_batch)
        row = (
            c.execute(
                text(
                    "SELECT *, clock_timestamp() AS checked_at "
                    "FROM emailmonitor.article_observations "
                    "WHERE organization_id=:org AND job_id=:job AND article_url=:url"
                ),
                {"org": org, "job": original_job, "url": URL},
            )
            .mappings()
            .one()
        )
    observation = row["observation"]
    lineage_values = {
        "organization_id": org,
        "source_job_id": original_job,
        "target_job_id": target_job,
        "source_id": row["source_id"],
        "article_url": row["article_url"],
        "source_revision": row["revision"],
        "source_policy_version": row["policy_version"],
        "source_generation": row["generation"],
        "deletion_generation": row["deletion_generation"],
        "acquisition_digest": observation["acquisition_digest"],
        "content_digest": observation["content_digest"],
        "observed_at": row["observed_at"],
        "expires_at": row["expires_at"],
        "fresh_since": row["observed_at"],
        "checked_at": row["checked_at"],
    }
    lineage = ReuseLineageDraft.model_validate(lineage_values)
    assert lineage.observed_at == row["observed_at"]
    with pytest.raises(ValidationError):
        ReuseLineageDraft.model_validate(
            {**lineage_values, "fresh_since": row["observed_at"] + timedelta(microseconds=1)}
        )
    draft = independent_review_draft(
        SETTINGS, org, org, original_job, target_job, ArticleObservation.model_validate(observation)
    )
    assert draft.associations[0].state == "needs_review"
    assert draft.associations[0].revision == 1
    assert draft.associations[0].id != source.associations[0].id
    with pytest.raises(DBAPIError) as failure:
        with service.database.tenant(service.token, org, Capability.ACQUIRE_SOURCE) as (c, _):
            c.execute(
                text("""
INSERT INTO emailmonitor.association_batches
(organization_id,id,job_id,article_url,source_revision,policy_version,generation,
 deletion_generation,snapshot,input_digest,expires_at)
SELECT organization_id,:new,:target,article_url,source_revision,policy_version,generation,
 deletion_generation,snapshot,input_digest,expires_at
FROM emailmonitor.association_batches WHERE organization_id=:org AND id=:source
                """),
                {"new": target_batch, "target": target_job, "org": org, "source": original_batch},
            )
    error = failure.value.orig
    code = getattr(error, "sqlstate", None)
    if code is None and error is not None and error.args and isinstance(error.args[0], dict):
        code = error.args[0].get("C")
    assert code == "EM009"
    assert service.detail(org, original_batch) == source
    with service.database.tenant(service.token, org, Capability.READ_ORGANIZATION) as (c, _):
        assert (
            c.execute(
                text(
                    "SELECT count(*) FROM emailmonitor.association_batches "
                    "WHERE organization_id=:org AND id=:batch"
                ),
                {"org": org, "batch": target_batch},
            ).scalar_one()
            == 0
        )

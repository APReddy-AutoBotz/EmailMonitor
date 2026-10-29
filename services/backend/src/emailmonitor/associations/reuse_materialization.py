"""Proposed draft-time reuse materialization; not yet exposed or enabled."""

import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from emailmonitor.administration.admission import Admission
from emailmonitor.associations.reuse_preparation import _SOURCE, prepare_reuse
from emailmonitor.associations.service import Associations
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest, URLInput
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability


def materialize_draft(service: Associations, org: UUID, target_job: UUID, url: str) -> UUID:
    """Stage one exact authored HTML observation for an opted-in draft job.

    This local candidate is unreachable from any route and depends on an
    unimplemented database lineage migration. It must not be enabled until SQL
    fences, real concurrency, retention and export acceptance have passed.
    The source is selected under the human caller's existing tenant scope; no
    cross-job worker authorization is granted by this function.
    """
    if url not in {
        "https://synthetic.publisher.example/article-a.html",
        "https://synthetic.publisher.example/article-b.html",
        "https://synthetic.publisher.example/no-contact.html",
    }:
        raise HTTPException(409, "Retained reuse is unavailable for this source route")
    with Admission(service.database, service.token, service.settings).fixture(org, target_job, url):
        with service.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            target = Ledger._lock(c, org, target_job)
            request = JobRequest.model_validate(target["request"])
            if (
                request.reuse is None
                or not isinstance(request.input, URLInput)
                or request.input.url != url
                or target["state"] != "draft"
            ):
                raise AuthorizationDenied()
            existing = (
                c.execute(
                    text(
                        "SELECT reused_from_job,reused_source_revision,reused_source_batch "
                        "FROM emailmonitor.article_observations WHERE organization_id=:org "
                        "AND job_id=:job AND article_url=:url FOR SHARE"
                    ),
                    {"org": org, "job": target_job, "url": url},
                )
                .mappings()
                .first()
            )
            if existing is not None and existing["reused_source_batch"] is None:
                raise HTTPException(409, "Existing observation has different lineage")
            selected = (
                existing["reused_source_batch"]
                if existing is not None
                else c.execute(
                    text("""
SELECT b.id FROM emailmonitor.association_batches b
JOIN emailmonitor.article_observations a ON a.organization_id=b.organization_id
 AND a.job_id=b.job_id AND a.article_url=b.article_url AND a.revision=b.source_revision
WHERE b.organization_id=:org AND b.job_id<>:target AND b.article_url=:url
 AND a.observed_at>=:cutoff AND a.expires_at>clock_timestamp()
 AND a.reused_from_job IS NULL AND a.observation->>'route'='html'
 AND a.observation->>'status' IN ('observed','no_contact')
ORDER BY a.observed_at DESC,b.id ASC LIMIT 1
                """),
                    {
                        "org": org,
                        "target": target_job,
                        "url": url,
                        "cutoff": request.reuse.fresh_since,
                    },
                ).scalar_one_or_none()
            )
            if selected is None:
                raise HTTPException(409, "No current retained observation meets the cutoff")
            candidate = prepare_reuse(c, service, org, target_job, url, selected)
            row = c.execute(_SOURCE, {"org": org, "batch": selected, "url": url}).mappings().one()
            if existing is not None:
                if (
                    existing["reused_from_job"] != candidate.lineage.source_job_id
                    or existing["reused_source_revision"] != candidate.lineage.source_revision
                    or existing["reused_source_batch"] != selected
                ):
                    raise HTTPException(409, "Existing observation has different lineage")
                return selected
            c.execute(
                text("""
INSERT INTO emailmonitor.article_observations
(organization_id,job_id,article_url,generation,deletion_generation,source_id,policy_version,
 discovery_revision,source_digest,observation,reused_from_job,reused_source_revision,reused_source_batch)
VALUES(:org,:job,:url,:generation,:deletion,:source,:policy,:discovery,:digest,
 CAST(:observation AS jsonb),:source_job,:source_revision,:source_batch)
                """),
                {
                    "org": org,
                    "job": target_job,
                    "url": url,
                    "generation": target["generation"],
                    "deletion": target["deletion_generation"],
                    "source": candidate.lineage.source_id,
                    "policy": candidate.lineage.source_policy_version,
                    "discovery": service.extraction._scope(c, org, target_job, url, browser=False)[
                        "revision"
                    ],
                    "digest": row["source_digest"],
                    "observation": json.dumps(row["observation"]),
                    "source_job": candidate.lineage.source_job_id,
                    "source_revision": candidate.lineage.source_revision,
                    "source_batch": selected,
                },
            )
            service._lock(c, org, selected)
            return selected

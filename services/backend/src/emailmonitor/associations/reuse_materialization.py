"""Human-scoped draft-time reuse materialization for authored fixtures."""

import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from emailmonitor.administration.admission import Admission
from emailmonitor.associations.reuse_adapters import (
    HTML_URLS,
    PDF_URLS,
    XML_URLS,
    Adapter,
    retained_plan,
)
from emailmonitor.associations.reuse_preparation import _SOURCE, prepare_reuse
from emailmonitor.associations.service import Associations
from emailmonitor.discovery.service import Discovery
from emailmonitor.discovery.state import DiscoveryState
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest, URLInput, canonical
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.runtime.database import ServiceDatabase


def materialize_draft(service: Associations, org: UUID, target_job: UUID, url: str) -> UUID:
    """Stage one exact authored retained observation for an opted-in draft job.

    Only explicitly opted-in authored fixture jobs reach this path. The source
    is selected under the human caller's existing tenant scope; no cross-job
    worker authorization is granted by this function. Hosted service, broker
    and installed acceptance are still required before release.
    """
    if isinstance(service.database, ServiceDatabase) or type(service.token) is not str:
        raise AuthorizationDenied()
    if url in HTML_URLS:
        adapter: Adapter = "html"
    elif url in PDF_URLS:
        adapter = "pdf"
    elif url in XML_URLS:
        adapter = "article_xml"
    else:
        raise HTTPException(409, "Retained reuse is unavailable for this source route")
    return _materialize_candidate(service, org, target_job, url, adapter)


def _stage_bound_reuse(
    discovery: Discovery, service: Associations, org: UUID, job: UUID, revision: int
) -> tuple[dict[str, object], UUID]:
    """Connect staged planning and bound materialization without exposing a route.

    A failed materialization never starts fresh acquisition. The existing SQL
    start fence requires a current copied observation; the database separately
    verifies any original XML/PDF execution binding.
    """
    if (
        discovery.database is not service.database
        or type(discovery.token) is not str
        or discovery.token != service.token
        or discovery.settings != service.settings
        or isinstance(service.database, ServiceDatabase)
    ):
        raise AuthorizationDenied()
    planned = discovery._plan_bound_reuse(org, job, revision)
    plan = planned.get("plan")
    if not isinstance(plan, dict) or (
        plan.get("classification") != "article" or plan.get("reason") != "retained_reuse_staged"
    ):
        raise HTTPException(409, "Retained reuse is unavailable for this source route")
    url = plan.get("start_url")
    if not isinstance(url, str):
        raise AuthorizationDenied()
    adapter: Adapter
    if url in PDF_URLS:
        adapter = "pdf"
    elif url in XML_URLS:
        adapter = "article_xml"
    else:
        raise AuthorizationDenied()
    checkpoint = DiscoveryState.model_validate(planned.get("checkpoint"))
    if (
        checkpoint.status != "completed"
        or checkpoint.reason != "single_article"
        or not checkpoint.discovery_complete
        or checkpoint.articles != [url]
    ):
        raise AuthorizationDenied()
    source_batch = _materialize_candidate(service, org, job, url, adapter)
    return planned, source_batch


def _materialize_candidate(
    service: Associations, org: UUID, target_job: UUID, url: str, adapter: Adapter
) -> UUID:
    """Shared adapter implementation; callers and SQL independently gate use.

    The public path remains restricted to the registered authored fixture
    adapters. Database guards independently check the original source binding.
    """
    if isinstance(service.database, ServiceDatabase) or type(service.token) is not str:
        raise AuthorizationDenied()
    with Admission(service.database, service.token, service.settings).fixture(org, target_job, url):
        with service.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            target = Ledger._lock(c, org, target_job)
            request = JobRequest.model_validate(target["request"])
            plan = retained_plan(request)
            if (
                plan is None
                or request.reuse is None
                or not isinstance(request.input, URLInput)
                or request.input.url != url
                or target["state"] != "draft"
                or plan.adapter != adapter
                or plan.article_url != url
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
            selected_value = (
                existing["reused_source_batch"]
                if existing is not None
                else c.execute(
                    text("""
SELECT b.id FROM emailmonitor.association_batches b
JOIN emailmonitor.article_observations a ON a.organization_id=b.organization_id
 AND a.job_id=b.job_id AND a.article_url=b.article_url AND a.revision=b.source_revision
WHERE b.organization_id=:org AND b.job_id<>:target AND b.article_url=:url
 AND a.observed_at>=:cutoff AND a.expires_at>clock_timestamp()
 AND a.reused_from_job IS NULL AND a.observation->>'route'=:route
 AND a.observation->>'status' IN ('observed','no_contact')
ORDER BY a.observed_at DESC,b.id ASC LIMIT 1
                """),
                    {
                        "org": org,
                        "target": target_job,
                        "url": url,
                        "cutoff": plan.fresh_since,
                        "route": adapter,
                    },
                ).scalar_one_or_none()
            )
            if selected_value is None:
                raise HTTPException(409, "No current retained observation meets the cutoff")
            selected = UUID(str(selected_value))
            candidate = prepare_reuse(c, service, org, target_job, url, selected)
            row = c.execute(_SOURCE, {"org": org, "batch": selected, "url": url}).mappings().one()
            if (
                canonical(row["observation"]) != candidate.evidence.document
                or row["source_digest"] != candidate.evidence.source_digest
                or row["job_id"] != candidate.evidence.source_job
            ):
                raise AuthorizationDenied()
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
            service.discovery._audit(c, org, target_job, "extraction.retained_reused")
            return selected

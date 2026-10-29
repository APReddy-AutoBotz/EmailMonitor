"""Transaction-local preparation only; execution and persistence remain unavailable."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, text

from emailmonitor.associations.models import Bundle
from emailmonitor.associations.reuse_draft import independent_review_draft
from emailmonitor.associations.reuse_lineage import ReuseLineageDraft
from emailmonitor.associations.service import Associations
from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.extraction.pdf_retained import RetainedPdf
from emailmonitor.extraction.xml_retained import RetainedXml
from emailmonitor.jobs.ledger import Ledger, canonical
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied


@dataclass(frozen=True)
class PreparedReuse:
    """A proposal for the caller's current transaction, never a reusable grant."""

    lineage: ReuseLineageDraft = field(repr=False)
    bundle: Bundle = field(repr=False)
    input_digest: str = field(repr=False)


_SOURCE = text("""
SELECT a.organization_id,a.job_id,a.article_url,a.revision,a.source_id,a.policy_version,
 a.generation,a.deletion_generation,a.discovery_revision,a.source_digest,a.observation,
 a.observed_at,a.expires_at,b.expires_at AS batch_expires_at
FROM emailmonitor.association_batches b JOIN emailmonitor.article_observations a
 ON a.organization_id=b.organization_id AND a.job_id=b.job_id
 AND a.article_url=b.article_url AND a.revision=b.source_revision
 AND a.generation=b.generation AND a.policy_version=b.policy_version
 AND a.deletion_generation=b.deletion_generation
WHERE b.organization_id=:org AND b.id=:batch AND a.article_url=:url
FOR SHARE OF a
""")


def prepare_reuse(
    c: Connection, service: Associations, org: UUID, target_job: UUID, url: str, source_batch: UUID
) -> PreparedReuse:
    """Build an unaccepted target review draft under existing current-work fences.

    This is not called by any route or worker. Its locks expire with the caller's
    transaction; a future persistence implementation must commit within that
    transaction and revalidate source and target on every later read/export.
    Current SQL still refuses a cross-job target batch. Lock ordering, live SQL
    behavior, revocation/deletion races and persistence are not yet validated.
    """
    target = Ledger._lock(c, org, target_job)
    request = JobRequest.model_validate(target["request"])
    if request.reuse is None:
        raise AuthorizationDenied()
    target_scope = service.extraction._scope(c, org, target_job, url, browser=False)
    service._lock(c, org, source_batch)
    params = {"org": org, "batch": source_batch, "url": url}
    first = c.execute(_SOURCE, params).mappings().first()
    if first is None or first["organization_id"] != org or first["job_id"] == target_job:
        raise AuthorizationDenied()
    if first["source_id"] != target_scope["source_id"] or first["policy_version"] != int(
        str(target_scope["policy_version"])
    ):
        raise AuthorizationDenied()
    raw = first["observation"]
    if not isinstance(raw, dict):
        raise AuthorizationDenied()
    encoded = json.dumps(raw)
    try:
        observed = (
            RetainedPdf.model_validate_json(encoded)
            if raw.get("route") == "pdf"
            else RetainedXml.model_validate_json(encoded)
            if raw.get("route") == "article_xml"
            else ArticleObservation.model_validate_json(encoded)
        )
    except ValueError:
        raise AuthorizationDenied() from None
    if observed.url != url:
        raise AuthorizationDenied()
    if isinstance(observed, (RetainedPdf, RetainedXml)) and (
        observed.binding.organization != org
        or observed.binding.job != first["job_id"]
        or observed.binding.generation != first["generation"]
        or observed.binding.deletion_generation != first["deletion_generation"]
        or observed.binding.policy_version != first["policy_version"]
        or observed.binding.discovery_revision != first["discovery_revision"]
    ):
        raise AuthorizationDenied()
    if observed.route == "browser_dom":
        service.extraction._scope(c, org, target_job, url, browser=True)
    acquisition = (
        first["source_digest"] if isinstance(observed, RetainedPdf) else observed.acquisition_digest
    )
    now: datetime = c.execute(text("SELECT clock_timestamp()")).scalar_one()
    try:
        lineage = ReuseLineageDraft.model_validate(
            {
                "organization_id": org,
                "source_job_id": first["job_id"],
                "target_job_id": target_job,
                "source_id": first["source_id"],
                "article_url": url,
                "source_revision": first["revision"],
                "source_policy_version": first["policy_version"],
                "source_generation": first["generation"],
                "deletion_generation": first["deletion_generation"],
                "acquisition_digest": acquisition,
                "content_digest": observed.content_digest,
                "observed_at": first["observed_at"],
                "expires_at": min(first["expires_at"], first["batch_expires_at"]),
                "fresh_since": request.reuse.fresh_since,
                "checked_at": now,
            }
        )
        bundle = independent_review_draft(
            service.settings, org, org, first["job_id"], target_job, observed
        )
    except ValueError:
        raise AuthorizationDenied() from None
    service._lock(c, org, source_batch)
    if c.execute(_SOURCE, params).mappings().first() != first:
        raise AuthorizationDenied()
    final_scope = service.extraction._scope(
        c, org, target_job, url, browser=observed.route == "browser_dom"
    )
    if (
        final_scope["source_id"] != first["source_id"]
        or int(str(final_scope["policy_version"])) != first["policy_version"]
    ):
        raise AuthorizationDenied()
    final_time: datetime = c.execute(text("SELECT clock_timestamp()")).scalar_one()
    try:
        lineage = ReuseLineageDraft.model_validate(
            {**lineage.model_dump(), "checked_at": final_time}
        )
    except ValueError:
        raise AuthorizationDenied() from None
    digest_value = lineage.model_dump(mode="json", exclude={"checked_at"})
    digest = hashlib.sha256(
        canonical([digest_value, bundle.model_dump(mode="json")]).encode("utf-8")
    ).hexdigest()
    return PreparedReuse(lineage, bundle, digest)

"""Transaction-local preparation of a source-bound reuse proposal."""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Connection, text

from emailmonitor.associations.models import Bundle
from emailmonitor.associations.reuse_adapters import retained_plan
from emailmonitor.associations.reuse_draft import independent_review_draft
from emailmonitor.associations.reuse_lineage import ReuseLineageDraft
from emailmonitor.associations.service import Associations
from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.extraction.pdf_retained import RetainedPdf
from emailmonitor.extraction.xml_retained import RetainedXml
from emailmonitor.fetching.safety import FetchDenied
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest, canonical
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.sources import provider_documents
from emailmonitor.sources.access import current_policy


@dataclass(frozen=True)
class OriginalRetainedEvidence:
    """Exact source evidence, not a target authorization or a new parse.

    XML/PDF retain the source execution item in their original parser binding.
    HTML has no parser-bound item. The serialized document remains the original
    JSON data; a later target scope must never rewrite that source binding.
    """

    route: str
    source_job: UUID
    source_item: UUID | None
    source_digest: str
    document: str = field(repr=False)


@dataclass(frozen=True)
class PreparedReuse:
    """A proposal for the caller's current transaction, never a reusable grant."""

    lineage: ReuseLineageDraft = field(repr=False)
    evidence: OriginalRetainedEvidence = field(repr=False)
    bundle: Bundle = field(repr=False)
    input_digest: str = field(repr=False)


_SOURCE = text("""
SELECT a.organization_id,a.job_id,a.article_url,a.revision,a.source_id,a.policy_version,
 a.generation,a.deletion_generation,a.discovery_revision,a.source_digest,a.observation,
 a.observed_at,a.expires_at,b.expires_at AS batch_expires_at,
 a.reused_from_job AS source_parent_job
FROM emailmonitor.association_batches b JOIN emailmonitor.article_observations a
 ON a.organization_id=b.organization_id AND a.job_id=b.job_id
 AND a.article_url=b.article_url AND a.revision=b.source_revision
 AND a.generation=b.generation AND a.policy_version=b.policy_version
 AND a.deletion_generation=b.deletion_generation
WHERE b.organization_id=:org AND b.id=:batch AND a.article_url=:url
FOR SHARE OF a
""")

# The retained XML/PDF binding identifies the *original* execution item. Never
# replace it with the target item or infer it from a parser result. This query
# runs only for bound adapters and uses the same human-scoped transaction.
# Its caller first holds the existing execution-read fence on the source job.
# Runtime has SELECT, not row-lock privileges, on execution_items; job writers
# serialize through the conflicting job fence and lifecycle purge also requires
# a prior source tombstone and the already-held source batch lock.
_SOURCE_ITEM = text("""
SELECT id FROM emailmonitor.execution_items
WHERE organization_id=:org AND job_id=:job AND id=:item AND input_url=:url
 AND work_kind='article' AND inherited_job_id IS NULL AND inherited_item_id IS NULL
 AND batch_id=:batch AND state IN ('succeeded','needs_review','no_contact')
""")


def _provider_matches_current_catalog(
    c: Connection, org: UUID, source: str, version: int, observed: RetainedXml
) -> bool:
    """Recheck the current retained-provider record; this never opens a transport."""
    if observed.provider is None:
        return True
    try:
        policy = current_policy(c, org, source)
        if policy.get("version") != version:
            return False
        registry = provider_documents.documents(policy.get("support"), source)
        found = [entry for entry in registry if entry.source_url == observed.url]
        if len(found) != 1:
            return False
        original = found[0]
        return bool(
            observed.provider.source_id == source
            and observed.requested_identifier == original.identifier
            and observed.content_digest == original.content_digest
            and observed.source_profile == original.source_profile
            and observed.provider.transport_url == original.request.url
            and observed.provider.request_fingerprint == original.request.fingerprint
        )
    except (HTTPException, FetchDenied, ValueError):
        return False


def prepare_reuse(
    c: Connection, service: Associations, org: UUID, target_job: UUID, url: str, source_batch: UUID
) -> PreparedReuse:
    """Build an unaccepted target review draft under existing current-work fences.

    The human-only draft materializer calls this inside its transaction. Locks
    expire with that transaction; later reads and exports require their own
    current fences. Synthetic SQL tests exercise specific lock and lifecycle
    cases, not every possible interleaving or the hosted service path.
    """
    target = Ledger._lock(c, org, target_job)
    request = JobRequest.model_validate(target["request"])
    plan = retained_plan(request)
    if request.reuse is None or plan is None or plan.article_url != url:
        raise AuthorizationDenied()
    target_scope = service.extraction._scope(c, org, target_job, url, browser=False)
    service._lock(c, org, source_batch)
    params = {"org": org, "batch": source_batch, "url": url}
    first = c.execute(_SOURCE, params).mappings().first()
    if (
        first is None
        or first["organization_id"] != org
        or first["job_id"] == target_job
        or first["source_parent_job"] is not None
    ):
        raise AuthorizationDenied()
    if (
        first["source_id"] != plan.source_id
        or first["source_id"] != target_scope["source_id"]
        or first["policy_version"] != int(str(target_scope["policy_version"]))
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
    if observed.url != url or observed.route != plan.adapter:
        raise AuthorizationDenied()
    if observed.status not in {"observed", "no_contact"}:
        # Partial, unsupported and unresolved observations cannot establish a
        # complete retained candidate or authorize a subsequent acquisition.
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
    if isinstance(observed, (RetainedPdf, RetainedXml)):
        # This existing security-definer operation rechecks current execution
        # authority and holds the source job, policy and session locks until the
        # transaction ends. It does not grant runtime writes to execution_items.
        c.execute(
            text("SELECT emailmonitor.execution_read_fence(:org,:job)"),
            {"org": org, "job": first["job_id"]},
        )
        item_params = {
            "org": org,
            "job": first["job_id"],
            "item": observed.binding.item,
            "url": url,
            "batch": source_batch,
        }
        if c.execute(_SOURCE_ITEM, item_params).scalar_one_or_none() != observed.binding.item:
            raise AuthorizationDenied()
        if isinstance(observed, RetainedXml) and not _provider_matches_current_catalog(
            c, org, plan.source_id, int(str(first["policy_version"])), observed
        ):
            raise AuthorizationDenied()
    acquisition = (
        first["source_digest"] if isinstance(observed, RetainedPdf) else observed.acquisition_digest
    )
    if acquisition != first["source_digest"] or (
        isinstance(observed, RetainedPdf) and observed.content_digest != first["source_digest"]
    ):
        raise AuthorizationDenied()
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
    if isinstance(observed, (RetainedPdf, RetainedXml)) and (
        c.execute(_SOURCE_ITEM, item_params).scalar_one_or_none() != observed.binding.item
    ):
        raise AuthorizationDenied()
    final_scope = service.extraction._scope(c, org, target_job, url, browser=False)
    if (
        final_scope["source_id"] != first["source_id"]
        or int(str(final_scope["policy_version"])) != first["policy_version"]
    ):
        raise AuthorizationDenied()
    if isinstance(observed, RetainedXml) and not _provider_matches_current_catalog(
        c, org, plan.source_id, int(str(first["policy_version"])), observed
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
    evidence = OriginalRetainedEvidence(
        route=observed.route,
        source_job=lineage.source_job_id,
        source_item=observed.binding.item
        if isinstance(observed, (RetainedPdf, RetainedXml))
        else None,
        source_digest=first["source_digest"],
        document=canonical(raw),
    )
    digest = hashlib.sha256(
        canonical([digest_value, evidence.document, bundle.model_dump(mode="json")]).encode("utf-8")
    ).hexdigest()
    return PreparedReuse(lineage, evidence, bundle, digest)

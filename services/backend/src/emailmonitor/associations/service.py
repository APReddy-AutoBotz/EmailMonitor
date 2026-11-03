"""Atomic relational receipts and current-tenant evidence-backed review.

Only identifiers reach HTTP handlers. Source facts come from retained, authorized
HTML/browser observations. The PDF mapper is pure; this service grants no PDF
acquisition/persistence route and cannot fetch, validate mailboxes or export.
"""

import hashlib
import json
from collections.abc import Callable
from typing import NoReturn, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from emailmonitor.associations.context_view import ContextView, project_context
from emailmonitor.associations.mapping import identifier, map_observation
from emailmonitor.associations.metadata import ArticleMetadata, project_metadata
from emailmonitor.associations.models import Bundle, Review
from emailmonitor.associations.quality import ObservationQuality, SourceBinding, project_quality
from emailmonitor.associations.review import apply_review
from emailmonitor.config import Settings
from emailmonitor.discovery.service import Discovery
from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.extraction.pdf_retained import RetainedPdf
from emailmonitor.extraction.service import Extraction
from emailmonitor.extraction.xml_retained import RetainedXml
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict, TenantContext
from emailmonitor.organizations.roles import Capability
from emailmonitor.runtime.access import WorkAuthority, WorkDatabase

View = TypeVar("View", ObservationQuality, ArticleMetadata)

RECORDS = {
    "authors": "association_authors",
    "candidates": "association_candidates",
    "evidence": "association_evidence",
    "associations": "author_email_associations",
}
LINKS = {
    "authors": ("association_author_evidence", "author_id"),
    "candidates": ("association_candidate_evidence", "candidate_id"),
    "associations": ("association_evidence_links", "association_id"),
}


def initial_bundle(
    settings: Settings,
    org: UUID,
    job: UUID,
    observed: ArticleObservation | RetainedPdf | RetainedXml,
    reused_from: UUID | None,
) -> Bundle:
    """Rebuild job-local review for reuse without transferring prior decisions."""
    if reused_from is None:
        return map_observation(settings, org, observed)
    from emailmonitor.associations.reuse_draft import independent_review_draft

    return independent_review_draft(settings, org, org, reused_from, job, observed)


def translate(error: DBAPIError) -> NoReturn:
    """Only our exact denial/conflict SQLSTATEs are translated, never other SQL failures."""
    original = error.orig
    code = getattr(original, "sqlstate", None)
    if (
        code is None
        and original is not None
        and original.args
        and isinstance(original.args[0], dict)
    ):
        code = original.args[0].get("C")
    if code == "EM009":
        raise AuthorizationDenied() from error
    if code == "EM409":
        raise RevisionConflict() from error
    raise error


class Associations:
    def __init__(self, database: WorkDatabase, token: WorkAuthority, settings: Settings) -> None:
        self.database, self.token, self.settings = database, token, settings
        self.discovery = Discovery(database, token, settings)
        self.extraction = Extraction(database, token, settings)

    @staticmethod
    def _lock(c: Connection, org: UUID, batch: UUID) -> None:
        try:
            c.execute(
                text("SELECT emailmonitor.lock_association_batch(:org,:batch)"),
                {"org": org, "batch": batch},
            )
        except DBAPIError as error:
            translate(error)

    def _bundle(self, c: Connection, org: UUID, batch: UUID) -> Bundle:
        self._lock(c, org, batch)
        snapshot = c.execute(
            text(
                """
SELECT snapshot FROM emailmonitor.association_batches WHERE organization_id=:org AND id=:batch
                """
            ),
            {"org": org, "batch": batch},
        ).scalar_one_or_none()
        if snapshot is None:
            raise AuthorizationDenied()
        document = dict(snapshot)
        for field, table in RECORDS.items():
            # Table names are server-owned constants, never request fields.
            order = "position" if field == "authors" else "id"
            document[field] = list(
                c.execute(
                    text(
                        f"""
SELECT record FROM emailmonitor.{table} WHERE organization_id=:org AND batch_id=:batch ORDER BY
{order}
                        """
                    ),
                    {"org": org, "batch": batch},
                ).scalars()
            )
        result = Bundle.model_validate_json(json.dumps(document))
        self._lock(c, org, batch)  # current permission/expiry recheck before release
        return result

    def derive(self, org: UUID, job: UUID, url: str, revision: int) -> UUID:
        try:
            return self._derive(org, job, url, revision)
        except DBAPIError as error:
            translate(error)

    def _derive(self, org: UUID, job: UUID, url: str, revision: int) -> UUID:
        with self.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            row = self.extraction._scope(c, org, job, url, browser=False)
            source = (
                c.execute(
                    text(
                        """
SELECT * FROM emailmonitor.article_observations WHERE organization_id=:org AND job_id=:job AND
article_url=:url FOR SHARE
                        """
                    ),
                    {"org": org, "job": job, "url": url},
                )
                .mappings()
                .first()
            )
            if source is None or source["revision"] != revision:
                raise RevisionConflict()
            # The scope/row generation and source policy are locked in this same transaction.
            if (
                source["generation"] != row["generation"] and not row["leased_execution"]
            ) or source["deletion_generation"] != row["deletion_generation"]:
                raise AuthorizationDenied()
            observed = (
                RetainedPdf.model_validate_json(json.dumps(source["observation"]))
                if source["observation"].get("route") == "pdf"
                else RetainedXml.model_validate_json(json.dumps(source["observation"]))
                if source["observation"].get("route") == "article_xml"
                else ArticleObservation.model_validate(source["observation"])
            )
            if observed.route == "browser_dom":
                self.extraction._scope(c, org, job, url, browser=True)
            bundle = initial_bundle(
                self.settings, org, job, observed, source.get("reused_from_job")
            )
            payload = bundle.model_dump_json()
            if len(payload.encode()) > 131072:
                raise ValueError("Retained association scope exceeds the bounded record ceiling")
            digest = hashlib.sha256(payload.encode()).hexdigest()
            batch = identifier(
                org, "association-batch", str(job), url, revision, observed.content_digest
            )
            existing = c.execute(
                text(
                    """
SELECT input_digest FROM emailmonitor.association_batches WHERE organization_id=:org AND
id=:batch
                    """
                ),
                {"org": org, "batch": batch},
            ).scalar_one_or_none()
            if existing is not None:
                if existing != digest:
                    raise RevisionConflict()
                self._bundle(c, org, batch)
                return batch  # reviews are not erased by replay
            c.execute(
                text("""INSERT INTO emailmonitor.association_batches
(organization_id,id,job_id,article_url,source_revision,policy_version,generation,deletion_generation,snapshot,input_digest,expires_at)
VALUES(:org,:batch,:job,:url,:revision,:policy,:generation,:deletion,
CAST(:snapshot AS jsonb),:digest,:expiry)"""),
                {
                    "org": org,
                    "batch": batch,
                    "job": job,
                    "url": url,
                    "revision": revision,
                    "policy": source["policy_version"],
                    "generation": source["generation"],
                    "deletion": source["deletion_generation"],
                    "snapshot": payload,
                    "digest": digest,
                    "expiry": source["expires_at"],
                },
            )
            document = bundle.model_dump(mode="json")
            # Evidence first, then authors/candidates, then their association FKs.
            for field in ("evidence", "authors", "candidates", "associations"):
                table = RECORDS[field]
                for record in document[field]:
                    c.execute(
                        text(
                            f"""
INSERT INTO emailmonitor.{table}(organization_id,batch_id,record)
VALUES(:org,:batch,CAST(:record AS jsonb))
                            """
                        ),
                        {"org": org, "batch": batch, "record": json.dumps(record)},
                    )
            for field, (table, column) in LINKS.items():
                for record in document[field]:
                    for evidence in record["evidence_ids"]:
                        c.execute(
                            text(
                                f"""
INSERT INTO emailmonitor.{table}(organization_id,batch_id,{column},evidence_id)
VALUES(:org,:batch,:entity,:evidence)
                                """
                            ),
                            {
                                "org": org,
                                "batch": batch,
                                "entity": UUID(record["id"]),
                                "evidence": UUID(evidence),
                            },
                        )
            for author in bundle.authors:
                for ordinal, institution in enumerate(author.affiliations, 1):
                    c.execute(
                        text(
                            """
INSERT INTO
emailmonitor.association_affiliations(organization_id,batch_id,author_id,ordinal,institution_name)
VALUES(:org,:batch,:author,:ordinal,:institution)
                            """
                        ),
                        {
                            "org": org,
                            "batch": batch,
                            "author": author.id,
                            "ordinal": ordinal,
                            "institution": institution,
                        },
                    )
            for candidate in bundle.candidates:
                for ordinal, raw in enumerate(candidate.raw_variants, 1):
                    c.execute(
                        text(
                            """
INSERT INTO
emailmonitor.association_raw_variants(organization_id,batch_id,candidate_id,ordinal,raw_address)
VALUES(:org,:batch,:candidate,:ordinal,:raw)
                            """
                        ),
                        {
                            "org": org,
                            "batch": batch,
                            "candidate": candidate.id,
                            "ordinal": ordinal,
                            "raw": raw,
                        },
                    )
            try:
                c.execute(
                    text("SELECT emailmonitor.seal_association_batch(:org,:batch)"),
                    {"org": org, "batch": batch},
                )
            except DBAPIError as error:
                translate(error)
            self._bundle(c, org, batch)
            return batch

    def detail(self, org: UUID, batch: UUID) -> Bundle:
        with self.discovery._tenant(org, Capability.READ_ORGANIZATION) as (c, _):
            return self._bundle(c, org, batch)

    def context_view(
        self,
        org: UUID,
        target_batch: UUID,
        association: UUID,
        revision: int,
        source_batch: UUID,
        evidence: UUID,
    ) -> ContextView:
        """Read both observations and audit access, without creating a link."""
        if target_batch == source_batch or type(self.token) is not str:
            raise AuthorizationDenied()
        with self.discovery._tenant(org, Capability.REVIEW_ASSOCIATIONS) as (c, ctx):
            if not isinstance(ctx, TenantContext):
                raise AuthorizationDenied()
            # Order shared locks consistently; both reads retain their RLS and source fences.
            for batch in sorted((target_batch, source_batch), key=lambda value: value.int):
                self._lock(c, org, batch)
            target = self._bundle(c, org, target_batch)
            source = self._bundle(c, org, source_batch)
            view = project_context(
                org, target_batch, target, association, revision, source_batch, source, evidence
            )
            # Re-read under RLS as well as the parent fence before returning. A
            # suppression/review change between the two reads must not release
            # an older context or target revision.
            current_target = self._bundle(c, org, target_batch)
            current_source = self._bundle(c, org, source_batch)
            current = project_context(
                org,
                target_batch,
                current_target,
                association,
                revision,
                source_batch,
                current_source,
                evidence,
            )
            if current != view:
                raise RevisionConflict()
            # The existing audit ledger contains identifiers only; neither the
            # citation nor a cross-observation reference is persisted here.
            # Failure to audit aborts the transaction and the response.
            for action, resource in (
                ("association.context_target_viewed", association),
                ("association.context_evidence_viewed", evidence),
            ):
                c.execute(
                    text("""INSERT INTO emailmonitor.audit_events
                    (organization_id,id,actor_id,action,resource_id)
                    VALUES(:org,:id,:actor,:action,:resource)"""),
                    {
                        "org": org,
                        "id": uuid4(),
                        "actor": ctx.identity_id,
                        "action": action,
                        "resource": resource,
                    },
                )
            return view

    def quality(self, org: UUID, batch: UUID) -> ObservationQuality:
        return self._observation_view(org, batch, project_quality)

    def metadata(self, org: UUID, batch: UUID) -> ArticleMetadata:
        return self._observation_view(org, batch, project_metadata)

    def _observation_view(
        self,
        org: UUID,
        batch: UUID,
        project: Callable[[UUID, UUID, Bundle, object, SourceBinding], View],
    ) -> View:
        with self.discovery._tenant(org, Capability.READ_ORGANIZATION) as (c, _):
            bundle = self._bundle(c, org, batch)
            # Ordinary runtime SELECT retains both tables' current restrictive RLS.
            # The old definer lock alone is not a privacy/suppression read grant.
            query = text("""
SELECT source.observation,source.job_id,source.generation,source.policy_version,
source.deletion_generation,source.source_digest,source.article_url,source.reused_from_job,
source.reused_source_revision,source.reused_source_batch FROM emailmonitor.association_batches batch
JOIN emailmonitor.article_observations source
ON source.organization_id=batch.organization_id AND source.job_id=batch.job_id
AND source.article_url=batch.article_url AND source.revision=batch.source_revision
AND source.generation=batch.generation AND source.policy_version=batch.policy_version
AND source.deletion_generation=batch.deletion_generation
WHERE batch.organization_id=:org AND batch.id=:batch
""")
            parameters = {"org": org, "batch": batch}
            row = c.execute(query, parameters).mappings().first()
            if row is None:
                raise AuthorizationDenied()
            origin_query = None
            origin_params = None
            origin = None
            item_query = None
            item_params = None
            binding = SourceBinding(
                row["job_id"], row["generation"], row["policy_version"], row["deletion_generation"]
            )
            document = row["observation"]
            if (
                row["reused_from_job"] is not None
                and isinstance(document, dict)
                and document.get("route") in {"pdf", "article_xml"}
            ):
                # An XML/PDF payload remains bound to its original item. The
                # normal RLS read and both batch fences establish current human
                # visibility; target-only workers gain no source-job grant.
                from emailmonitor.associations.reuse_preparation import (
                    _SOURCE,
                    _SOURCE_ITEM,
                    _source_execution_fence,
                )

                source_batch = row["reused_source_batch"]
                if source_batch is None or row["reused_source_revision"] is None:
                    raise AuthorizationDenied()
                self._lock(c, org, source_batch)
                origin_query = _SOURCE
                origin_params = {"org": org, "batch": source_batch, "url": row["article_url"]}
                origin = c.execute(origin_query, origin_params).mappings().first()
                if (
                    origin is None
                    or origin["job_id"] != row["reused_from_job"]
                    or origin["source_parent_job"] is not None
                    or origin["revision"] != row["reused_source_revision"]
                    or origin["source_digest"] != row["source_digest"]
                    or origin["observation"] != document
                ):
                    raise AuthorizationDenied()
                try:
                    observed = (
                        RetainedPdf.model_validate_json(json.dumps(document))
                        if document["route"] == "pdf"
                        else RetainedXml.model_validate_json(json.dumps(document))
                    )
                except ValueError:
                    raise AuthorizationDenied() from None
                if observed.binding.discovery_revision != origin["discovery_revision"]:
                    raise AuthorizationDenied()
                _source_execution_fence(c, org, origin["job_id"])
                item_query = _SOURCE_ITEM
                item_params = {
                    "org": org,
                    "job": origin["job_id"],
                    "item": observed.binding.item,
                    "url": row["article_url"],
                    "batch": source_batch,
                }
                if c.execute(item_query, item_params).scalar_one_or_none() != observed.binding.item:
                    raise AuthorizationDenied()
                binding = SourceBinding(
                    origin["job_id"],
                    origin["generation"],
                    origin["policy_version"],
                    origin["deletion_generation"],
                )
            try:
                result = project(
                    org,
                    batch,
                    bundle,
                    document,
                    binding,
                )
            except ValueError:
                raise AuthorizationDenied() from None
            self._lock(c, org, batch)
            # Recheck current row visibility at release (including retention time).
            if c.execute(query, parameters).mappings().first() != row:
                raise AuthorizationDenied()
            if origin_query is not None and origin_params is not None and origin is not None:
                self._lock(c, org, row["reused_source_batch"])
                if c.execute(origin_query, origin_params).mappings().first() != origin:
                    raise AuthorizationDenied()
                assert item_query is not None and item_params is not None
                if c.execute(item_query, item_params).scalar_one_or_none() != item_params["item"]:
                    raise AuthorizationDenied()
            return result

    def batches(self, org: UUID, job: UUID) -> list[dict[str, object]]:
        with self.discovery._tenant(org, Capability.READ_ORGANIZATION) as (c, _):
            if not c.execute(
                text("SELECT 1 FROM emailmonitor.jobs WHERE organization_id=:org AND id=:job"),
                {"org": org, "job": job},
            ).scalar_one_or_none():
                raise AuthorizationDenied()
            rows = (
                c.execute(
                    text(
                        """
SELECT id,article_url,source_revision,created_at,expires_at FROM
emailmonitor.association_batches WHERE organization_id=:org AND job_id=:job ORDER BY
article_url LIMIT 100
                        """
                    ),
                    {"org": org, "job": job},
                )
                .mappings()
                .all()
            )
            for row in rows:
                self._lock(c, org, row["id"])
            return [dict(row) for row in rows]

    def review(self, org: UUID, batch: UUID, request: Review) -> Bundle:
        with self.discovery._tenant(org, Capability.REVIEW_ASSOCIATIONS) as (c, _):
            current = self._bundle(c, org, batch)
            apply_review(self.settings, current, request)
            try:
                c.execute(
                    text("""
SELECT emailmonitor.review_association(:org,:batch,:association,:revision,
:action,:author,CAST(:evidence AS uuid[]),:reason,:review,:event)"""),
                    {
                        "org": org,
                        "batch": batch,
                        "association": request.association_id,
                        "revision": request.expected_revision,
                        "action": request.action,
                        "author": request.author_id,
                        "evidence": list(request.evidence_ids),
                        "reason": request.reason,
                        "review": uuid4(),
                        "event": uuid4(),
                    },
                )
            except DBAPIError as error:
                translate(error)
            return self._bundle(c, org, batch)

    def history(self, org: UUID, batch: UUID) -> list[dict[str, object]]:
        with self.discovery._tenant(org, Capability.READ_ORGANIZATION) as (c, _):
            self._lock(c, org, batch)
            rows = (
                c.execute(
                    text(
                        """
SELECT id,association_id,actor,action,expected_revision,reason,created_at FROM
emailmonitor.association_reviews WHERE organization_id=:org AND batch_id=:batch ORDER BY
created_at,id LIMIT 100
                        """
                    ),
                    {"org": org, "batch": batch},
                )
                .mappings()
                .all()
            )
            self._lock(c, org, batch)
            return [dict(row) for row in rows]

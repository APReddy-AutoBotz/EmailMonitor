"""Atomic relational receipts and current-tenant evidence-backed review.

Only identifiers reach HTTP handlers. Source facts come from retained, authorized
HTML/browser observations. The PDF mapper is pure; this service grants no PDF
acquisition/persistence route and cannot fetch, validate mailboxes or export.
"""

import hashlib
import json
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from emailmonitor.associations.mapping import identifier, map_observation
from emailmonitor.associations.models import Bundle, Review
from emailmonitor.associations.quality import ObservationQuality, SourceBinding, project_quality
from emailmonitor.associations.review import apply_review
from emailmonitor.config import Settings
from emailmonitor.discovery.service import Discovery
from emailmonitor.extraction.html import ArticleObservation
from emailmonitor.extraction.service import Extraction
from emailmonitor.extraction.xml_retained import RetainedXml
from emailmonitor.organizations.database import AuthorizationDenied, Database, RevisionConflict
from emailmonitor.organizations.roles import Capability

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
    def __init__(self, database: Database, token: str, settings: Settings) -> None:
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
                RetainedXml.model_validate_json(json.dumps(source["observation"]))
                if source["observation"].get("route") == "article_xml"
                else ArticleObservation.model_validate(source["observation"])
            )
            if observed.route == "browser_dom":
                self.extraction._scope(c, org, job, url, browser=True)
            bundle = map_observation(self.settings, org, observed)
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

    def quality(self, org: UUID, batch: UUID) -> ObservationQuality:
        with self.discovery._tenant(org, Capability.READ_ORGANIZATION) as (c, _):
            bundle = self._bundle(c, org, batch)
            # Ordinary runtime SELECT retains both tables' current restrictive RLS.
            # The old definer lock alone is not a privacy/suppression read grant.
            query = text("""
SELECT source.observation,source.job_id,source.generation,source.policy_version,
source.deletion_generation FROM emailmonitor.association_batches batch
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
            try:
                result = project_quality(
                    org,
                    batch,
                    bundle,
                    row["observation"],
                    SourceBinding(
                        row["job_id"],
                        row["generation"],
                        row["policy_version"],
                        row["deletion_generation"],
                    ),
                )
            except ValueError:
                raise AuthorizationDenied() from None
            self._lock(c, org, batch)
            # Recheck current row visibility at release (including retention time).
            if c.execute(query, parameters).mappings().first() != row:
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

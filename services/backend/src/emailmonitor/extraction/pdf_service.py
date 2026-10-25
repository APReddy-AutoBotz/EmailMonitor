"""Opt-in local fixture parsing through the isolated worker and current SQL fences."""

from typing import Protocol
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from emailmonitor.administration.admission import Admission
from emailmonitor.config import Settings
from emailmonitor.extraction.pdf import PdfObservation
from emailmonitor.extraction.pdf_fixture import pdf_bytes
from emailmonitor.extraction.pdf_retained import (
    PdfBinding,
    RetainedPdf,
    require_pdf_binding,
    retain_pdf,
)
from emailmonitor.extraction.service import Extraction
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.parsing.pdf_channel import parse_isolated
from emailmonitor.parsing.pdf_protocol import PdfExpectation
from emailmonitor.progress.binding import CURRENT
from emailmonitor.runtime.access import WorkAuthority, WorkDatabase


class PdfParser(Protocol):
    def __call__(
        self, settings: Settings, data: bytes, *, expected: PdfExpectation
    ) -> PdfObservation: ...


class PdfExtraction(Extraction):
    def __init__(
        self,
        database: WorkDatabase,
        token: WorkAuthority,
        settings: Settings,
        *,
        parser: PdfParser | None = None,
    ) -> None:
        super().__init__(database, token, settings)
        self.parser = parser

    def binding(self, org: UUID, job: UUID, url: str, context: dict[str, object]) -> PdfBinding:
        lease = CURRENT.get()
        if lease is None or lease.organization != org or lease.job != job:
            raise AuthorizationDenied()
        return PdfBinding(
            organization=org,
            job=job,
            item=lease.item,
            generation=lease.generation,
            deletion_generation=lease.deletion_generation,
            policy_version=int(str(context["policy_version"])),
            discovery_revision=int(str(context["revision"])),
        )

    def isolated_fixture(self, org: UUID, job: UUID, url: str, revision: int) -> dict[str, object]:
        from emailmonitor.extraction.pdf_fixture import DIGESTS

        context = self.prepare(org, job, url)
        if context["revision"] != revision:
            raise HTTPException(409, "Discovery revision conflict")
        scope = self.binding(org, job, url, context)
        # Reading local bytes is not an HTTP fetch. Only the explicit PDF operation admits it.
        with Admission(self.database, self.token, self.settings).fixture(org, job, url):
            name = url.rsplit("/", 1)[-1]
            expected = PdfExpectation(url=url, content_digest=DIGESTS[name])
            observed = (self.parser or parse_isolated)(
                self.settings, pdf_bytes(name), expected=expected
            )
            observed = PdfObservation.model_validate_json(observed.model_dump_json())
            expected.check_observation(observed)
            value = retain_pdf(observed, scope, permit_excerpts=bool(context["permit_excerpts"]))
            return self.commit_pdf(org, job, value)

    def commit_pdf(self, org: UUID, job: UUID, value: RetainedPdf) -> dict[str, object]:
        from emailmonitor.administration.binding import fence

        value = RetainedPdf.model_validate_json(value.model_dump_json())
        with self.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            fence(c, org, job, value.url)
            context = self._scope(c, org, job, value.url, browser=False)
            require_pdf_binding(
                value,
                self.binding(org, job, value.url, context),
                permit_excerpts=bool(context["permit_excerpts"]),
            )
            old = (
                c.execute(
                    text("""SELECT * FROM emailmonitor.article_observations
WHERE organization_id=:org AND job_id=:job AND article_url=:url FOR UPDATE"""),
                    {"org": org, "job": job, "url": value.url},
                )
                .mappings()
                .first()
            )
            if old is not None:
                if c.execute(
                    text("SELECT :expiry<=clock_timestamp()"), {"expiry": old["expires_at"]}
                ).scalar_one():
                    raise HTTPException(409, "Observation retention expired")
                if old["observation"] != value.model_dump(mode="json"):
                    raise HTTPException(409, "Immutable observation already committed")
                return dict(old)
            scope = value.binding
            c.execute(
                text("""INSERT INTO emailmonitor.article_observations
(organization_id,job_id,article_url,generation,deletion_generation,policy_version,
discovery_revision,source_digest,observation)
VALUES(:org,:job,:url,:generation,:deletion,:policy,:revision,:digest,CAST(:document AS jsonb))"""),
                {
                    "org": org,
                    "job": job,
                    "url": value.url,
                    "generation": scope.generation,
                    "deletion": scope.deletion_generation,
                    "policy": scope.policy_version,
                    "revision": scope.discovery_revision,
                    "digest": value.content_digest,
                    "document": value.model_dump_json(),
                },
            )
            self.discovery._audit(c, org, job, "extraction.observation_committed")
            return dict(
                c.execute(
                    text("""SELECT * FROM emailmonitor.article_observations
WHERE organization_id=:org AND job_id=:job AND article_url=:url"""),
                    {"org": org, "job": job, "url": value.url},
                )
                .mappings()
                .one()
            )

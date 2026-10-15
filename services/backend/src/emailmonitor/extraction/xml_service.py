"""Authorized synthetic XML acquisition→isolated parse→durable retained facts."""

import hashlib
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from emailmonitor.administration.admission import Admission
from emailmonitor.extraction.service import Extraction
from emailmonitor.extraction.xml_retained import (
    XML_DIGEST,
    XML_URL,
    RetainedXml,
    XmlBinding,
    retain_xml,
)
from emailmonitor.fetching.fixture import (
    ByteResponse,
    FetchLimits,
    FixtureByteTransport,
    FixtureGateway,
    TenantFixtureAuthorization,
)
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.parsing.xml_channel import parse_isolated
from emailmonitor.progress.binding import CURRENT
from emailmonitor.sources.policy import Operation


def fixture_bytes() -> bytes:
    from pathlib import Path

    root = Path(__file__).resolve().parents[5]
    data = (root / "fixtures/xml/sciencedirect-article.xml").read_bytes()
    if hashlib.sha256(data).hexdigest() != XML_DIGEST:
        raise ValueError("Authored XML digest mismatch")
    return data


def require_current_binding(
    value: RetainedXml, expected: XmlBinding, permit_excerpts: bool
) -> None:
    if value.binding != expected or (value.excerpts_retained and not permit_excerpts):
        raise AuthorizationDenied()


class XmlExtraction(Extraction):
    def binding(self, org: UUID, job: UUID, revision: int) -> tuple[XmlBinding, bool]:
        lease = CURRENT.get()
        if lease is None or lease.organization != org or lease.job != job:
            raise AuthorizationDenied()
        context = self.prepare(org, job, XML_URL)
        if context["revision"] != revision:
            raise HTTPException(409, "Discovery revision conflict")
        return XmlBinding(
            organization=org,
            job=job,
            item=lease.item,
            generation=lease.generation,
            deletion_generation=lease.deletion_generation,
            policy_version=int(str(context["policy_version"])),
            discovery_revision=revision,
        ), bool(context["permit_excerpts"])

    def isolated_fixture(self, org: UUID, job: UUID, revision: int) -> dict[str, object]:
        binding, excerpts = self.binding(org, job, revision)
        with Admission(self.database, self.token, self.settings).fixture(org, job, XML_URL):
            # All permission/admission checks precede opening the authored bytes.
            data = fixture_bytes()
            auth = TenantFixtureAuthorization(
                self.database, self.token, org, "synthetic-publisher", binding.policy_version
            )
            acquired = FixtureGateway(
                self.settings,
                FixtureByteTransport(
                    self.settings,
                    {
                        XML_URL: ByteResponse(
                            200, (data,), content_type="application/xml", content_length=len(data)
                        )
                    },
                ),
                auth,
                FetchLimits(max_bytes=32768),
            ).fetch(XML_URL, Operation.XML)
            observed = parse_isolated(self.settings, acquired)
            retained = retain_xml(observed, binding, excerpts)
            return self.commit_xml(org, job, retained)

    def commit_xml(self, org: UUID, job: UUID, value: RetainedXml) -> dict[str, object]:
        from emailmonitor.administration.binding import fence

        value = RetainedXml.model_validate_json(value.model_dump_json())
        payload = value.model_dump_json()
        if len(payload.encode()) > 131072:
            raise ValueError("Retained XML envelope exceeds bounded ceiling")
        with self.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (connection, _):
            fence(connection, org, job, XML_URL)
            context = self._scope(connection, org, job, XML_URL, browser=False)
            lease = CURRENT.get()
            if lease is None:
                raise AuthorizationDenied()
            expected = XmlBinding(
                organization=org,
                job=job,
                item=lease.item,
                generation=lease.generation,
                deletion_generation=lease.deletion_generation,
                policy_version=int(str(context["policy_version"])),
                discovery_revision=int(str(context["revision"])),
            )
            require_current_binding(value, expected, bool(context["permit_excerpts"]))
            old = (
                connection.execute(
                    text("""SELECT * FROM emailmonitor.article_observations
WHERE organization_id=:org AND job_id=:job AND article_url=:url FOR UPDATE"""),
                    {"org": org, "job": job, "url": XML_URL},
                )
                .mappings()
                .first()
            )
            if old is not None:
                if connection.execute(
                    text("SELECT :expiry<=clock_timestamp()"), {"expiry": old["expires_at"]}
                ).scalar_one():
                    raise HTTPException(409, "Observation retention expired")
                if old["observation"] != value.model_dump(mode="json"):
                    raise HTTPException(409, "Immutable observation already committed")
                return dict(old)
            connection.execute(
                text("""INSERT INTO emailmonitor.article_observations
(organization_id,job_id,article_url,generation,deletion_generation,policy_version,discovery_revision,source_digest,observation)
VALUES(:org,:job,:url,:generation,:deletion,:policy,:discovery,:digest,
CAST(:document AS jsonb))"""),
                {
                    "org": org,
                    "job": job,
                    "url": XML_URL,
                    "generation": expected.generation,
                    "deletion": expected.deletion_generation,
                    "policy": expected.policy_version,
                    "discovery": expected.discovery_revision,
                    "digest": XML_DIGEST,
                    "document": payload,
                },
            )
            self.discovery._audit(connection, org, job, "extraction.observation_committed")
            return dict(
                connection.execute(
                    text("""SELECT * FROM emailmonitor.article_observations
WHERE organization_id=:org AND job_id=:job AND article_url=:url"""),
                    {"org": org, "job": job, "url": XML_URL},
                )
                .mappings()
                .one()
            )

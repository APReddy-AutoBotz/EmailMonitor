"""Authorized Open Access JATS fixture acquisition -> isolated parse -> retained facts.

OA-029 (document 91), under the fixture-only ``europe-pmc`` catalog source since
OA-030 (document 92). Offline only: the bytes are committed synthetic fixtures
served through the fixture gateway for a registered synthetic article path. The
Europe PMC URL is recorded as provenance and never requested.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from emailmonitor.administration.admission import Admission
from emailmonitor.config import Settings
from emailmonitor.extraction.jats import JatsObservation
from emailmonitor.extraction.jats_retained import RetainedJats, retain_jats
from emailmonitor.extraction.xml_retained import XmlBinding
from emailmonitor.extraction.xml_service import XmlExtraction
from emailmonitor.fetching.fixture import (
    ByteResponse,
    FetchLimits,
    FixtureByteTransport,
    FixtureGateway,
    TenantFixtureAuthorization,
)
from emailmonitor.organizations.database import AuthorizationDenied
from emailmonitor.organizations.roles import Capability
from emailmonitor.parsing.jats_protocol import JatsExpectation
from emailmonitor.progress.binding import CURRENT
from emailmonitor.sources import open_access_documents as registry
from emailmonitor.sources.policy import Operation

JatsParser = Callable[[Settings, bytes, JatsExpectation], JatsObservation]
MAX_FIXTURE_BYTES = 65536


def isolated_parser(settings: Settings, data: bytes, expected: JatsExpectation) -> JatsObservation:
    from emailmonitor.parsing.jats_channel import parse_isolated

    return parse_isolated(settings, data, expected)


class OaExtraction(XmlExtraction):
    def isolated_open_access(
        self,
        org: UUID,
        job: UUID,
        url: str,
        revision: int,
        *,
        parser: JatsParser | None = None,
    ) -> dict[str, object]:
        document = registry.registered(url)
        if document is None:
            raise AuthorizationDenied()
        binding, excerpts = self.binding(org, job, revision, url)
        with Admission(self.database, self.token, self.settings).fixture(org, job, url):
            # All permission/admission checks precede opening the authored bytes.
            data = registry.fixture_bytes(document)
            auth = TenantFixtureAuthorization(
                self.database, self.token, org, registry.SOURCE, binding.policy_version
            )
            acquired = FixtureGateway(
                self.settings,
                FixtureByteTransport(
                    self.settings,
                    {
                        url: ByteResponse(
                            200, (data,), content_type="application/xml", content_length=len(data)
                        )
                    },
                ),
                auth,
                FetchLimits(max_bytes=MAX_FIXTURE_BYTES),
            ).fetch(url, Operation.XML)
            expected = JatsExpectation(
                requested_identifier=document.identifier, content_digest=document.content_digest
            )
            observed = (parser or isolated_parser)(self.settings, acquired, expected)
            retained = retain_jats(observed, document, binding, excerpts)
            return self.commit_jats(org, job, retained)

    def commit_jats(self, org: UUID, job: UUID, value: RetainedJats) -> dict[str, object]:
        from emailmonitor.administration.binding import fence

        value = RetainedJats.model_validate_json(value.model_dump_json())
        payload = value.model_dump_json()
        if len(payload.encode()) > 131072:
            raise ValueError("Retained JATS envelope exceeds bounded ceiling")
        with self.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (connection, _):
            fence(connection, org, job, value.url)
            context = self._scope(connection, org, job, value.url, browser=False)
            # New Open Access work is only ever recorded under its own source; a job
            # planned under another source (for example before 0028) is refused.
            if context["source_id"] != registry.SOURCE:
                raise AuthorizationDenied()
            from emailmonitor.sources.access import current_policy

            policy = current_policy(connection, org, str(context["source_id"]))
            support = policy["support"]
            entries = support.get("open_access_documents") if isinstance(support, dict) else None
            if not isinstance(entries, list) or not any(
                isinstance(entry, dict)
                and entry.get("source_url") == value.url
                and entry.get("content_digest") == value.content_digest
                and entry.get("canonical_url") == value.canonical_url
                for entry in entries
            ):
                raise AuthorizationDenied()
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
            if value.binding != expected or (
                value.excerpts_retained and not bool(context["permit_excerpts"])
            ):
                raise AuthorizationDenied()
            old = (
                connection.execute(
                    text("""SELECT * FROM emailmonitor.article_observations
WHERE organization_id=:org AND job_id=:job AND article_url=:url FOR UPDATE"""),
                    {"org": org, "job": job, "url": value.url},
                )
                .mappings()
                .first()
            )
            if old is not None:
                if connection.execute(
                    text("SELECT :expiry<=clock_timestamp()"), {"expiry": old["expires_at"]}
                ).scalar_one():
                    raise HTTPException(409, "Observation retention expired")
                if old["observation"] != json.loads(payload):
                    raise HTTPException(409, "Immutable observation already committed")
                return dict(old)
            connection.execute(
                text("""INSERT INTO emailmonitor.article_observations
(organization_id,job_id,article_url,source_id,generation,deletion_generation,policy_version,discovery_revision,source_digest,observation)
VALUES(:org,:job,:url,:source,:generation,:deletion,:policy,:discovery,:digest,
CAST(:document AS jsonb))"""),
                {
                    "org": org,
                    "job": job,
                    "url": value.url,
                    "source": registry.SOURCE,
                    "generation": expected.generation,
                    "deletion": expected.deletion_generation,
                    "policy": expected.policy_version,
                    "discovery": expected.discovery_revision,
                    "digest": value.content_digest,
                    "document": payload,
                },
            )
            self.discovery._audit(connection, org, job, "extraction.observation_committed")
            return dict(
                connection.execute(
                    text("""SELECT * FROM emailmonitor.article_observations
WHERE organization_id=:org AND job_id=:job AND article_url=:url"""),
                    {"org": org, "job": job, "url": value.url},
                )
                .mappings()
                .one()
            )

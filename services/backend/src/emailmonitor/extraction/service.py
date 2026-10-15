"""Tenant-fenced idempotent observations from the authored discovery frontier.

This test assembly does not start extraction jobs or substitute synthetic probe
effects for extraction. Browser observations enter only through trusted isolated
worker composition; the HTTP API accepts identifiers, never HTML or observations.
"""

import hashlib
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Connection, text

from emailmonitor.administration.admission import Admission
from emailmonitor.config import Settings
from emailmonitor.discovery.service import Discovery
from emailmonitor.discovery.state import DiscoveryState
from emailmonitor.extraction.fixture import BROWSER_ACQUISITION_DIGEST, DIGESTS, article_bytes
from emailmonitor.extraction.html import ArticleObservation, parse_article
from emailmonitor.fetching.fixture import (
    ByteResponse,
    FetchLimits,
    FixtureByteTransport,
    FixtureGateway,
    TenantFixtureAuthorization,
)
from emailmonitor.fetching.safety import classify_url
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest
from emailmonitor.organizations.database import AuthorizationDenied, Database
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import matches as execution_matches
from emailmonitor.sources.access import policy_decision
from emailmonitor.sources.policy import Evaluation, Operation, PolicyProposal


class Extraction:
    def __init__(self, database: Database, token: str, settings: Settings) -> None:
        self.discovery = Discovery(database, token, settings)
        self.database, self.token, self.settings = database, token, settings

    def _scope(
        self, c: Connection, org: UUID, job: UUID, url: str, *, browser: bool
    ) -> dict[str, object]:
        parent = Ledger._lock(c, org, job)
        row = Discovery._row(c, org, job)
        state = DiscoveryState.model_validate(row["checkpoint"])
        if (
            not execution_matches(c, org, job, "article", url)
            or parent["generation"] != row["generation"]
            or parent["deletion_generation"] != row["deletion_generation"]
            or url not in state.articles
        ):
            raise AuthorizationDenied()
        version = int(str(row["policy_version"]))
        policy = Discovery._authorize(c, org, job, version, url, False)
        safe = classify_url(url, frozenset({"synthetic.publisher.example"}))
        if not policy_decision(
            policy,
            Evaluation(
                expected_version=version,
                operation=Operation.EXTRACT,
                host=safe.host,
                path=safe.path,
                execution_mode="fixture",
            ),
        ):
            raise AuthorizationDenied()
        proposal = PolicyProposal.model_validate(policy["policy"])
        if JobRequest.model_validate(parent["request"]).purpose != proposal.purpose:
            raise AuthorizationDenied()
        if proposal.retention.contact_days <= 0:
            raise HTTPException(409, "Source does not permit observation retention")
        row["leased_execution"] = parent["state"] == "running"
        row["permit_excerpts"] = proposal.retention.excerpt_days > 0 and policy_decision(
            policy,
            Evaluation(
                expected_version=version,
                operation=Operation.EXCERPT,
                host=safe.host,
                path=safe.path,
                execution_mode="fixture",
            ),
        )
        options = JobRequest.model_validate(parent["request"]).options
        if browser and (
            url != "https://synthetic.publisher.example/tooltip.html"
            or not options.allow_browser
            or not policy_decision(
                policy,
                Evaluation(
                    expected_version=version,
                    operation=Operation.BROWSER,
                    host=classify_url(url, frozenset({"synthetic.publisher.example"})).host,
                    path="/tooltip.html",
                    execution_mode="fixture",
                ),
            )
        ):
            raise AuthorizationDenied()
        row["max_link_depth"] = min(options.max_link_depth, 2)
        return row

    def prepare(
        self, org: UUID, job: UUID, url: str, *, browser: bool = False
    ) -> dict[str, object]:
        with self.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            return self._scope(c, org, job, url, browser=browser)

    def commit(
        self,
        org: UUID,
        job: UUID,
        observation: ArticleObservation,
        *,
        expected_revision: int,
        source_digest: str,
    ) -> dict[str, object]:
        from emailmonitor.administration.binding import CURRENT as FIXTURE
        from emailmonitor.progress.binding import CURRENT as DURABLE

        if FIXTURE.get() is not None or DURABLE.get() is not None:
            return self._commit(
                org,
                job,
                observation,
                expected_revision=expected_revision,
                source_digest=source_digest,
            )
        with Admission(self.database, self.token, self.settings).fixture(org, job, observation.url):
            return self._commit(
                org,
                job,
                observation,
                expected_revision=expected_revision,
                source_digest=source_digest,
            )

    def _commit(
        self,
        org: UUID,
        job: UUID,
        observation: ArticleObservation,
        *,
        expected_revision: int,
        source_digest: str,
    ) -> dict[str, object]:
        # Internal trusted-worker API only. No user endpoint accepts this model.
        name = observation.url.rsplit("/", 1)[-1]
        if DIGESTS.get(name) != source_digest or (
            observation.route == "html" and observation.content_digest != source_digest
        ):
            raise ValueError("Authored source provenance required")
        if observation.acquisition_digest != (
            BROWSER_ACQUISITION_DIGEST if observation.route == "browser_dom" else source_digest
        ):
            raise ValueError("Registered acquisition provenance required")
        if observation.route == "browser_dom" and name != "tooltip.html":
            raise ValueError("Registered tooltip browser plan required")
        with self.discovery._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            from emailmonitor.administration.binding import fence

            fence(c, org, job, observation.url)
            context = self._scope(
                c, org, job, observation.url, browser=observation.route == "browser_dom"
            )
            if any(
                link.depth > int(str(context["max_link_depth"])) for link in observation.follow_up
            ):
                raise AuthorizationDenied()
            for link in observation.follow_up:
                Discovery._authorize(
                    c, org, job, int(str(context["policy_version"])), link.url, False
                )
            if context["revision"] != expected_revision:
                raise HTTPException(409, "Discovery revision conflict")
            old = (
                c.execute(
                    text("""SELECT * FROM emailmonitor.article_observations
WHERE organization_id=:org AND job_id=:job AND article_url=:url FOR UPDATE"""),
                    {"org": org, "job": job, "url": observation.url},
                )
                .mappings()
                .first()
            )
            if not context["permit_excerpts"]:
                document = observation.model_dump()

                def strip(value: object) -> None:
                    if isinstance(value, dict):
                        if "excerpt" in value:
                            value["excerpt"] = ""
                        for child in value.values():
                            strip(child)
                    elif isinstance(value, list):
                        for child in value:
                            strip(child)

                strip(document)
                observation = ArticleObservation.model_validate(document)
            document = observation.model_dump()
            if old is not None:
                if c.execute(
                    text("SELECT :expiry <= clock_timestamp()"), {"expiry": old["expires_at"]}
                ).scalar_one():
                    raise HTTPException(409, "Observation retention expired")
                if old["observation"] == document:
                    return dict(old)
                previous = ArticleObservation.model_validate(old["observation"])
                if (
                    previous.status != "requires_browser"
                    or observation.route != "browser_dom"
                    or observation.status != "observed"
                ):
                    raise HTTPException(409, "Immutable observation already committed")
                c.execute(
                    text("""UPDATE emailmonitor.article_observations SET
observation=CAST(:document AS jsonb), revision=revision+1, observed_at=clock_timestamp()
WHERE organization_id=:org AND job_id=:job AND article_url=:url"""),
                    {
                        "org": org,
                        "job": job,
                        "url": observation.url,
                        "document": observation.model_dump_json(),
                    },
                )
            else:
                c.execute(
                    text("""INSERT INTO emailmonitor.article_observations
(organization_id,job_id,article_url,generation,deletion_generation,policy_version,discovery_revision,source_digest,observation)
VALUES(:org,:job,:url,:generation,:deletion,:policy,:discovery,:digest,
CAST(:document AS jsonb))
ON CONFLICT(organization_id,job_id,article_url) DO NOTHING"""),
                    {
                        "org": org,
                        "job": job,
                        "url": observation.url,
                        "generation": context["generation"],
                        "deletion": context["deletion_generation"],
                        "policy": context["policy_version"],
                        "discovery": context["revision"],
                        "digest": source_digest,
                        "document": observation.model_dump_json(),
                    },
                )
            committed = (
                c.execute(
                    text("""SELECT * FROM emailmonitor.article_observations
WHERE organization_id=:org AND job_id=:job AND article_url=:url"""),
                    {"org": org, "job": job, "url": observation.url},
                )
                .mappings()
                .first()
            )
            if committed is None:
                raise HTTPException(409, "Observation already recorded or expired")
            Discovery._audit(c, org, job, "extraction.observation_committed")
            return dict(committed)

    def fixture(self, org: UUID, job: UUID, url: str, expected_revision: int) -> dict[str, object]:
        context = self.prepare(org, job, url)
        if context["revision"] != expected_revision:
            raise HTTPException(409, "Discovery revision conflict")
        with Admission(self.database, self.token, self.settings).fixture(org, job, url):
            payload = article_bytes(url.rsplit("/", 1)[-1])
            auth = TenantFixtureAuthorization(
                self.database,
                self.token,
                org,
                "synthetic-publisher",
                int(str(context["policy_version"])),
            )
            transport = FixtureByteTransport(
                self.settings, {url: ByteResponse(200, (payload,), content_length=len(payload))}
            )
            acquired = FixtureGateway(
                self.settings, transport, auth, FetchLimits(max_bytes=32768)
            ).fetch(url, Operation.HTML)
            observation = parse_article(
                self.settings, url, acquired, max_depth=int(str(context["max_link_depth"]))
            )
            return self.commit(
                org,
                job,
                observation,
                expected_revision=expected_revision,
                source_digest=hashlib.sha256(acquired).hexdigest(),
            )

    def read(self, org: UUID, job: UUID) -> list[dict[str, object]]:
        with self.discovery._tenant(org, Capability.READ_ORGANIZATION) as (c, _):
            if not c.execute(
                text("SELECT 1 FROM emailmonitor.jobs WHERE organization_id=:org AND id=:job"),
                {"org": org, "job": job},
            ).scalar_one_or_none():
                raise AuthorizationDenied()
            return [
                dict(row)
                for row in c.execute(
                    text("""SELECT * FROM emailmonitor.article_observations
WHERE organization_id=:org AND job_id=:job AND expires_at>clock_timestamp()
ORDER BY article_url LIMIT 500"""),
                    {"org": org, "job": job},
                ).mappings()
            ]

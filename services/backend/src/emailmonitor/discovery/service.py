"""Short tenant transactions and replay-safe page commits for synthetic discovery.

The API plans only. Trusted fixture test composition supplies page observations;
queue payloads and API callers cannot supply parsed HTML or arbitrary fetchers.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from uuid import UUID, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from emailmonitor.administration.models import Entitlements, effective_article_cap
from emailmonitor.config import Settings
from emailmonitor.discovery.planning import ARTICLE_PATHS, plan_input
from emailmonitor.discovery.search import SearchPage
from emailmonitor.discovery.state import DiscoveryState, advance
from emailmonitor.fetching.fixture import HOSTS, require_fixture
from emailmonitor.fetching.safety import classify_url
from emailmonitor.jobs.ledger import Ledger
from emailmonitor.jobs.models import JobRequest, canonical
from emailmonitor.organizations.database import AuthorizationDenied, Database, TenantContext
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import allowed as execution_allowed
from emailmonitor.progress.binding import matches as execution_matches
from emailmonitor.sources import provider_documents as provider
from emailmonitor.sources.access import current_policy, policy_decision
from emailmonitor.sources.policy import Evaluation, Operation, PolicyProposal


def policy_fence_denied(error: DBAPIError) -> bool:
    """Only our exact server fence code/reason maps to a sanitized denial."""
    args = getattr(error.orig, "args", ())
    detail = args[0] if args else None
    return isinstance(detail, dict) and (detail.get("C"), detail.get("M")) in {
        ("EM006", "DISCOVERY_POLICY_FENCE"),
        ("EM010", "EXECUTION_WORK_FENCE"),
        ("EM013", "FIXTURE_ADMISSION_FENCE"),
    }


class Discovery:
    def __init__(self, database: Database, token: str, settings: Settings):
        require_fixture(settings)
        self.database, self.token, self.settings = database, token, settings

    @contextmanager
    def _tenant(
        self, org: UUID, capability: Capability
    ) -> Iterator[tuple[Connection, TenantContext]]:
        try:
            with self.database.tenant(self.token, org, capability) as context:
                yield context
        except DBAPIError as error:
            if policy_fence_denied(error):
                raise AuthorizationDenied() from error
            raise

    @staticmethod
    def _authorize(
        c: Connection, org: UUID, job: UUID, version: int, url: str, search: bool
    ) -> dict[str, object]:
        safe = classify_url(url, HOSTS)
        # Runtime has no catalog write privilege. A fixed-source authorized
        # definer fence acquires current row locks without granting table writes.
        c.execute(
            text("SELECT emailmonitor.discovery_source_fence(:org,:job,:version)"),
            {"org": org, "job": job, "version": version},
        )
        policy = current_policy(c, org, "synthetic-publisher")
        operation = (
            Operation.XML
            if safe.path == "/article-xml.xml" or url in provider.ARTICLE_URLS
            else Operation.HTML
        )
        operations = (
            (
                (Operation.SEARCH,)
                if url == provider.SEARCH_URL
                else (Operation.HTML, Operation.SEARCH)
            )
            if search
            else (operation,)
        )
        for operation in operations:
            if not policy_decision(
                policy,
                Evaluation(
                    expected_version=version,
                    operation=operation,
                    host=safe.host,
                    path=safe.path,
                    execution_mode="fixture",
                ),
            ):
                raise AuthorizationDenied()
        return policy

    @staticmethod
    def _row(c: Connection, org: UUID, job: UUID) -> dict[str, object]:
        row = (
            c.execute(
                text("""SELECT * FROM emailmonitor.discovery
WHERE organization_id=:org AND job_id=:job FOR UPDATE"""),
                {"org": org, "job": job},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise HTTPException(409, "Plan discovery first")
        return dict(row)

    def plan(self, org: UUID, job: UUID, expected_revision: int) -> dict[str, object]:
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            parent = Ledger._lock(c, org, job)
            if parent["kind"] != "extraction" or parent["state"] != "draft":
                raise HTTPException(409, "Draft extraction request required")
            if parent["row_version"] != expected_revision:
                raise HTTPException(409, "Job revision conflict")
            request = JobRequest.model_validate(parent["request"])
            plan = plan_input(request)
            if plan.start_url is None:
                return {
                    "plan": asdict(plan),
                    "checkpoint": DiscoveryState(
                        status="needs_refinement"
                        if plan.classification == "needs_refinement"
                        else "unsupported",
                        reason=plan.reason,
                    ).model_dump(),
                    "persisted": False,
                }
            existing = (
                c.execute(
                    text("""SELECT * FROM emailmonitor.discovery
WHERE organization_id=:org AND job_id=:job"""),
                    {"org": org, "job": job},
                )
                .mappings()
                .first()
            )
            policy = current_policy(c, org, "synthetic-publisher")
            version = int(str(policy["version"]))
            self._authorize(
                c, org, job, version, plan.start_url, plan.classification == "search_results"
            )
            if existing is not None:
                if existing["policy_version"] != version:
                    raise HTTPException(409, "Plan policy version conflict; create a new job")
                return dict(existing)
            proposal = PolicyProposal.model_validate(policy["policy"])
            configured: object = c.execute(
                text("SELECT emailmonitor.administration_plan(:org,:job)"), {"org": org, "job": job}
            ).scalar_one()
            if not isinstance(configured, dict):
                raise ValueError("Bounded effective configuration required")
            limits = Entitlements.model_validate(configured["entitlements"])
            cap = effective_article_cap(
                limits, proposal.limits.max_articles_per_job, request.options.max_articles
            )
            if cap == 0 or limits.max_running_jobs == 0 or limits.monthly_resolution_units == 0:
                raise HTTPException(409, "Current entitlement budget is unavailable")
            state = DiscoveryState(
                status="pending" if plan.classification == "search_results" else "completed",
                reason="first_page"
                if plan.classification == "search_results"
                else "single_article",
                next_url=plan.start_url if plan.classification == "search_results" else None,
                articles=[] if plan.classification == "search_results" else [plan.start_url],
                discovery_complete=plan.classification == "article",
                completeness="unknown"
                if plan.classification == "search_results"
                else "single_article",
            )
            c.execute(
                text("""INSERT INTO emailmonitor.discovery
(organization_id,job_id,generation,deletion_generation,source_id,policy_version,plan,checkpoint,
max_pages,max_articles)
VALUES(:org,:job,:generation,:deletion,'synthetic-publisher',:version,CAST(:plan AS jsonb),
CAST(:checkpoint AS jsonb),:pages,:articles)"""),
                {
                    "org": org,
                    "job": job,
                    "generation": parent["generation"],
                    "deletion": parent["deletion_generation"],
                    "version": version,
                    "plan": canonical(asdict(plan)),
                    "checkpoint": state.model_dump_json(),
                    "pages": request.options.max_search_pages,
                    "articles": cap,
                },
            )
            if state.status == "pending":
                self._schedule(c, org, job, int(str(parent["generation"])), 1)
            if state.discovery_complete:
                self._complete(c, org, job)
            self._audit(c, org, job, "discovery.planned")
            return self._row(c, org, job)

    @staticmethod
    def _audit(c: Connection, org: UUID, job: UUID, event: str) -> None:
        c.execute(
            text("""INSERT INTO emailmonitor.audit_events
(organization_id,id,actor_id,action,resource_id)
VALUES(:org,:id,emailmonitor.job_actor(),:event,:job)"""),
            {"org": org, "job": job, "event": event, "id": uuid4()},
        )

    def prepare(self, org: UUID, job: UUID) -> dict[str, object]:
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            parent = Ledger._lock(c, org, job)
            row = self._row(c, org, job)
            if (
                not execution_allowed(c, org, job)
                or parent["generation"] != row["generation"]
                or parent["deletion_generation"] != row["deletion_generation"]
            ):
                raise AuthorizationDenied()
            state = DiscoveryState.model_validate(row["checkpoint"])
            if state.status != "pending" or state.next_url is None:
                raise HTTPException(409, "Discovery has stopped")
            if not execution_matches(c, org, job, "discover", state.next_url):
                raise AuthorizationDenied()
            self._authorize(c, org, job, int(str(row["policy_version"])), state.next_url, True)
            return row

    def commit(
        self, org: UUID, job: UUID, expected_revision: int, page: SearchPage
    ) -> dict[str, object]:
        from emailmonitor.administration.admission import Admission
        from emailmonitor.administration.binding import CURRENT as FIXTURE
        from emailmonitor.progress.binding import CURRENT as DURABLE

        if FIXTURE.get() is not None or DURABLE.get() is not None:
            return self._commit(org, job, expected_revision, page)
        with Admission(self.database, self.token, self.settings).fixture(org, job, page.url):
            return self._commit(org, job, expected_revision, page)

    def _commit(
        self, org: UUID, job: UUID, expected_revision: int, page: SearchPage
    ) -> dict[str, object]:
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            parent = Ledger._lock(c, org, job)
            row = self._row(c, org, job)
            from emailmonitor.administration.binding import fence

            fence(c, org, job, page.url)
            if (
                not execution_allowed(c, org, job)
                or parent["generation"] != row["generation"]
                or parent["deletion_generation"] != row["deletion_generation"]
            ):
                raise AuthorizationDenied()
            version = int(str(row["policy_version"]))
            authorized = self._authorize(c, org, job, version, page.url, True)
            state = DiscoveryState.model_validate(row["checkpoint"])
            if not execution_matches(c, org, job, "discover", page.url):
                raise AuthorizationDenied()
            # Retransmitting an already committed identical observation is a no-op.
            if page.url in state.pages:
                index = state.pages.index(page.url)
                if state.digests[index] != page.digest:
                    raise HTTPException(409, "Committed page changed")
                return row
            if row["revision"] != expected_revision:
                raise HTTPException(409, "Discovery revision conflict")
            for article in page.articles:
                if (
                    classify_url(article, HOSTS).path not in ARTICLE_PATHS
                    and article not in provider.ARTICLE_URLS
                ):
                    raise AuthorizationDenied()
                self._authorize(c, org, job, version, article, False)
            if page.next_url is not None:
                self._authorize(c, org, job, version, page.next_url, True)
            updated = advance(
                state, page, int(str(row["max_pages"])), int(str(row["max_articles"]))
            )
            requested = JobRequest.model_validate(parent["request"]).options.max_articles
            if updated.reason == "article_cap" and int(str(row["max_articles"])) < requested:
                source_cap = PolicyProposal.model_validate(
                    authorized["policy"]
                ).limits.max_articles_per_job
                reason = (
                    "source_cap"
                    if int(str(row["max_articles"])) == source_cap
                    else "entitlement_cap"
                )
                updated = updated.model_copy(update={"reason": reason})
            c.execute(
                text("""UPDATE emailmonitor.discovery SET checkpoint=CAST(:state AS jsonb),
revision=revision+1
WHERE organization_id=:org AND job_id=:job"""),
                {"state": updated.model_dump_json(), "org": org, "job": job},
            )
            if updated.status == "pending":
                self._schedule(c, org, job, int(str(row["generation"])), expected_revision + 1)
            if updated.discovery_complete:
                self._complete(c, org, job)
            self._audit(c, org, job, "discovery.page_committed")
            return self._row(c, org, job)

    @staticmethod
    def _schedule(c: Connection, org: UUID, job: UUID, generation: int, revision: int) -> None:
        parent_state: object = c.execute(
            text("SELECT state FROM emailmonitor.jobs WHERE organization_id=:org AND id=:job"),
            {"org": org, "job": job},
        ).scalar_one()
        if parent_state != "draft":
            # Started extraction uses its atomic execution frontier/outbox, not the
            # legacy single-page fixture outbox. The current lease already fenced commit.
            if not execution_allowed(c, org, job):
                raise AuthorizationDenied()
            return
        event = uuid5(job, canonical([str(org), generation, revision, "discovery.page"]))
        c.execute(
            text("""INSERT INTO emailmonitor.discovery_outbox
(organization_id,job_id,event_id,generation,revision) VALUES(:org,:job,:event,:generation,:revision)
ON CONFLICT DO NOTHING"""),
            {
                "org": org,
                "job": job,
                "event": event,
                "generation": generation,
                "revision": revision,
            },
        )

    def pending(self, org: UUID) -> list[dict[str, object]]:
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            return [
                dict(row)
                for row in c.execute(
                    text("""SELECT o.* FROM emailmonitor.discovery_outbox o
JOIN emailmonitor.jobs j ON (j.organization_id,j.id)=(o.organization_id,o.job_id)
JOIN emailmonitor.discovery d ON (d.organization_id,d.job_id)=(o.organization_id,o.job_id)
JOIN emailmonitor.source_policy_heads h
ON (h.organization_id,h.source_id)=(d.organization_id,d.source_id)
JOIN emailmonitor.source_policies p
ON (p.organization_id,p.source_id,p.version)=(d.organization_id,d.source_id,d.policy_version)
JOIN emailmonitor.source_catalog s ON s.source_id=d.source_id
WHERE h.current_version=d.policy_version AND p.state='approved' AND p.valid_until>clock_timestamp()
AND s.enabled AND p.policy->'allowed_operations' ? 'fetch_html'
AND p.policy->'allowed_operations' ? 'search' AND o.organization_id=:org AND j.state='draft'
AND o.generation=j.generation AND o.revision=d.revision
AND d.checkpoint->>'status'='pending' AND emailmonitor.job_write_allowed(o.organization_id,o.job_id)
ORDER BY o.event_id LIMIT 100"""),
                    {"org": org},
                ).mappings()
            ]

    def event_matches(self, org: UUID, job: UUID, event: UUID, revision: int) -> bool:
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            parent = Ledger._lock(c, org, job)
            if parent["state"] != "draft":
                raise AuthorizationDenied()
            return bool(
                c.execute(
                    text("""SELECT EXISTS(SELECT 1 FROM emailmonitor.discovery_outbox
WHERE organization_id=:org AND job_id=:job AND event_id=:event
AND revision=:revision AND generation=:generation)"""),
                    {
                        "org": org,
                        "job": job,
                        "event": event,
                        "revision": revision,
                        "generation": parent["generation"],
                    },
                ).scalar_one()
            )

    def received(self, org: UUID, job: UUID, event: UUID) -> None:
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            Ledger._lock(c, org, job)
            self._audit(c, org, event, "discovery.delivery.received")

    def confirmed(self, org: UUID, job: UUID, event: UUID) -> None:
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as (c, _):
            Ledger._lock(c, org, job)
            c.execute(
                text("""UPDATE emailmonitor.discovery_outbox SET published_at=clock_timestamp()
WHERE organization_id=:org AND job_id=:job AND event_id=:event AND published_at IS NULL"""),
                {"org": org, "job": job, "event": event},
            )

    @staticmethod
    def _complete(c: Connection, org: UUID, job: UUID) -> None:
        c.execute(
            text("""UPDATE emailmonitor.jobs SET discovery_complete=true
WHERE organization_id=:org AND id=:job AND NOT discovery_complete"""),
            {"org": org, "job": job},
        )

    def read(self, org: UUID, job: UUID) -> dict[str, object]:
        with self._tenant(org, Capability.READ_ORGANIZATION) as (c, _):
            row = (
                c.execute(
                    text("""SELECT * FROM emailmonitor.discovery
WHERE organization_id=:org AND job_id=:job"""),
                    {"org": org, "job": job},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise AuthorizationDenied()
            return dict(row)

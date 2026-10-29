"""Synthetic durable orchestration; queue and streams never replace PostgreSQL authority."""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, NoReturn
from uuid import UUID, uuid4

from sqlalchemy import Connection, Result, text
from sqlalchemy.exc import DBAPIError

from emailmonitor.associations.service import Associations
from emailmonitor.config import Settings
from emailmonitor.discovery.fixture import step_fixture
from emailmonitor.discovery.service import Discovery
from emailmonitor.discovery.state import DiscoveryState
from emailmonitor.extraction.pdf_service import PdfParser
from emailmonitor.extraction.service import Extraction
from emailmonitor.fetching.fixture import require_fixture
from emailmonitor.organizations.database import AuthorizationDenied, RevisionConflict
from emailmonitor.organizations.roles import Capability
from emailmonitor.progress.binding import Lease, bound
from emailmonitor.progress.models import Event, Item, Snapshot
from emailmonitor.progress.state import Outcome, counts, percentage
from emailmonitor.progress.timing import JobTiming, project_timing
from emailmonitor.runtime.access import WorkAuthority, WorkDatabase
from emailmonitor.runtime.delegation import ServiceBindings


def row_pairs[Value](rows: Result[str, Value]) -> dict[str, Value]:
    """Consume result rows explicitly; Result.keys is metadata, not a mapping."""
    return {row[0]: row[1] for row in rows}


def translate(error: DBAPIError) -> NoReturn:
    original = getattr(error, "orig", None)
    args = getattr(original, "args", ())
    data = args[0] if args else None
    code = getattr(original, "sqlstate", None) or (
        data.get("C") if isinstance(data, dict) else None
    )
    reason = getattr(original, "message", None) or (
        data.get("M") if isinstance(data, dict) else None
    )
    if code == "EM409" and reason in {"EXECUTION_REVISION", "EXECUTION_CONTROL_STATE"}:
        raise RevisionConflict() from error
    if code == "EM010" and reason in {
        "EXECUTION_SCOPE_DENIED",
        "EXECUTION_START_DENIED",
        "EXECUTION_WORK_FENCE",
        "EXECUTION_RETRY_DENIED",
    }:
        raise AuthorizationDenied() from error
    raise error


@dataclass(frozen=True)
class Work:
    lease: Lease
    kind: Literal["discover", "article"]
    url: str
    discovery_revision: int


class Progress:
    def __init__(
        self,
        database: WorkDatabase,
        token: WorkAuthority,
        settings: Settings,
        *,
        bindings: ServiceBindings | None = None,
    ) -> None:
        require_fixture(settings)
        self.database, self.token, self.settings = database, token, settings
        self.bindings = bindings
        self.discovery = Discovery(database, token, settings)
        self.extraction = Extraction(database, token, settings)
        self.associations = Associations(database, token, settings)

    @contextmanager
    def _tenant(self, org: UUID, capability: Capability) -> Iterator[Connection]:
        try:
            with self.database.tenant(self.token, org, capability) as (connection, _):
                yield connection
        except DBAPIError as error:
            translate(error)

    @staticmethod
    def _read_scope(connection: Connection, org: UUID, job: UUID) -> None:
        connection.execute(
            text("SELECT emailmonitor.execution_read_fence(:org,:job)"),
            {"org": org, "job": job},
        )

    def authorize(self, org: UUID, job: UUID) -> None:
        with self._tenant(org, Capability.READ_ORGANIZATION) as connection:
            self._read_scope(connection, org, job)

    def timing(self, org: UUID, job: UUID) -> JobTiming:
        with self._tenant(org, Capability.READ_ORGANIZATION) as c:
            self._read_scope(c, org, job)
            row = (
                c.execute(
                    text("""
SELECT j.state, j.row_version, j.generation,
 q.occurred_at AS queued_at, q.sequence AS queued_sequence,
 t.occurred_at AS terminal_at, t.sequence AS terminal_sequence,
 t.aggregate_version AS terminal_revision
FROM emailmonitor.jobs j
LEFT JOIN LATERAL (
 SELECT occurred_at, sequence FROM emailmonitor.execution_events
 WHERE organization_id=j.organization_id AND job_id=j.id AND event_type='job.queued'
 ORDER BY sequence LIMIT 1
) q ON true
LEFT JOIN LATERAL (
 SELECT occurred_at, sequence, aggregate_version FROM emailmonitor.execution_events
 WHERE organization_id=j.organization_id AND job_id=j.id
 AND event_type=CASE WHEN j.state='cancelled' THEN 'job.cancelled' ELSE 'job.finished' END
 ORDER BY sequence DESC LIMIT 1
) t ON true
WHERE j.organization_id=:org AND j.id=:job
"""),
                    {"org": org, "job": job},
                )
                .mappings()
                .one()
            )
            result = project_timing(
                org,
                job,
                row["state"],
                row["row_version"],
                row["generation"],
                row["queued_at"],
                row["terminal_at"],
                row["queued_sequence"],
                row["terminal_sequence"],
                row["terminal_revision"],
            )
            self._read_scope(c, org, job)
            current = c.execute(
                text("""SELECT row_version, generation FROM emailmonitor.jobs
WHERE organization_id=:org AND id=:job"""),
                {"org": org, "job": job},
            ).one()
            if tuple(current) != (result.revision, result.generation):
                raise RevisionConflict()
            return result

    def snapshot(self, org: UUID, job: UUID) -> Snapshot:
        with self._tenant(org, Capability.READ_ORGANIZATION) as c:
            self._read_scope(c, org, job)
            parent = (
                c.execute(
                    text(
                        """
SELECT state, row_version, generation FROM emailmonitor.jobs WHERE organization_id=:org
AND id=:job
"""
                    ),
                    {"org": org, "job": job},
                )
                .mappings()
                .one()
            )
            checkpoint: object = c.execute(
                text(
                    """
SELECT checkpoint FROM emailmonitor.discovery WHERE organization_id=:org AND job_id=:job
"""
                ),
                {"org": org, "job": job},
            ).scalar_one()
            state = DiscoveryState.model_validate(checkpoint)
            run = (
                c.execute(
                    text(
                        """
SELECT selected_urls, last_sequence FROM emailmonitor.execution_runs WHERE
organization_id=:org AND job_id=:job
"""
                    ),
                    {"org": org, "job": job},
                )
                .mappings()
                .first()
            )
            selected = run["selected_urls"] if run else None
            articles = [url for url in state.articles if selected is None or url in selected]
            durable: dict[str, Outcome] = row_pairs(
                c.execute(
                    text(
                        """
SELECT input_url, state FROM emailmonitor.execution_items WHERE organization_id=:org AND
job_id=:job AND work_kind='article'
"""
                    ),
                    {"org": org, "job": job},
                )
            )
            quota_stopped: bool = c.execute(
                text("""SELECT EXISTS(SELECT 1 FROM emailmonitor.execution_items
WHERE organization_id=:org AND job_id=:job AND reason='quota_exhausted')"""),
                {"org": org, "job": job},
            ).scalar_one()
            # An unscheduled durable frontier entry is pending, never silently omitted.
            item_counts = counts([durable.get(url, "pending") for url in articles])
            quality: dict[str, int] = row_pairs(
                c.execute(
                    text("""
SELECT a.state, count(*) FROM emailmonitor.author_email_associations a
JOIN emailmonitor.association_batches b ON b.organization_id=a.organization_id AND b.id=a.batch_id
WHERE a.organization_id=:org AND (b.job_id=:job OR EXISTS(
SELECT 1 FROM emailmonitor.execution_items i WHERE i.organization_id=a.organization_id
AND i.job_id=:job AND i.batch_id=a.batch_id)) GROUP BY a.state
"""),
                    {"org": org, "job": job},
                )
            )
            document = Snapshot(
                organization_id=org,
                job_id=job,
                state=parent["state"],
                revision=parent["row_version"],
                generation=parent["generation"],
                discovery_pages=len(state.pages),
                source_reported_total=state.reported_total,
                unique_articles=len(articles),
                duplicates=state.duplicates,
                discovery_complete=state.discovery_complete,
                completeness=state.completeness,
                discovery_stop_reason="quota_exhausted" if quota_stopped else state.reason,
                counts=item_counts,
                accepted_associations=quality.get("accepted", 0),
                review_needed_associations=quality.get("needs_review", 0)
                + quality.get("unmatched", 0),
                progress_percent=percentage(item_counts, state.discovery_complete),
                last_sequence=run["last_sequence"] if run else 0,
            )
            self._read_scope(c, org, job)
            return document

    def start(self, org: UUID, job: UUID, revision: int) -> Snapshot:
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as c:
            c.execute(
                text("""
SELECT emailmonitor.execution_start(:org, :job, :revision, :event)
"""),
                {"org": org, "job": job, "revision": revision, "event": uuid4()},
            )
            if self.bindings is not None:
                self.bindings.issue(c, org, job, "extraction")
        return self.snapshot(org, job)

    def control(
        self, org: UUID, job: UUID, revision: int, action: Literal["pause", "resume", "cancel"]
    ) -> None:
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as c:
            c.execute(
                text("""
SELECT emailmonitor.execution_control(:org, :job, :revision, :action, :event)
"""),
                {"org": org, "job": job, "revision": revision, "action": action, "event": uuid4()},
            )
            if action == "resume" and self.bindings is not None:
                self.bindings.issue(c, org, job, "extraction")

    def retry(self, org: UUID, job: UUID, revision: int) -> UUID:
        continuation = uuid4()
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as c:
            result: UUID = c.execute(
                text("SELECT emailmonitor.execution_retry(:org,:job,:revision,:new,:event)"),
                {
                    "org": org,
                    "job": job,
                    "revision": revision,
                    "new": continuation,
                    "event": uuid4(),
                },
            ).scalar_one()
            if self.bindings is not None and result == continuation:
                self.bindings.issue(c, org, result, "extraction")
        return result

    def pending(self, org: UUID) -> list[dict[str, object]]:
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as c:
            return [
                dict(row)
                for row in c.execute(
                    text("""
SELECT o.job_id, o.event_id, o.item_id, o.generation, i.work_kind
FROM emailmonitor.execution_outbox o JOIN emailmonitor.execution_items i
USING(organization_id, job_id)
JOIN emailmonitor.jobs j ON j.organization_id=o.organization_id AND j.id=o.job_id
WHERE o.organization_id=:org AND i.id=o.item_id AND i.state IN ('pending', 'retry_wait')
AND i.attempts<3
AND o.generation=j.generation AND j.state IN ('queued', 'running') AND o.published_at IS
NULL
AND emailmonitor.job_write_allowed(o.organization_id, o.job_id) ORDER BY o.job_id,
o.item_id LIMIT 100
"""),
                    {"org": org},
                ).mappings()
            ]

    def claim(
        self,
        org: UUID,
        job: UUID,
        item: UUID,
        event: UUID,
        seconds: int = 30,
        generation: int | None = None,
    ) -> Work | None:
        token = uuid4()
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as c:
            row = (
                c.execute(
                    text(
                        """
SELECT * FROM emailmonitor.execution_claim(:org, :job, :item, :event, :token, :seconds, :generation)
"""
                    ),
                    {
                        "org": org,
                        "job": job,
                        "item": item,
                        "event": event,
                        "token": token,
                        "seconds": seconds,
                        "generation": generation,
                    },
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            if row["work_kind"] not in {"discover", "article"}:
                raise ValueError("Registered work kind required")
            return Work(
                Lease(org, job, item, token, row["generation"], row["deletion_generation"]),
                row["work_kind"],
                row["input_url"],
                row["discovery_revision"],
            )

    def finish(
        self,
        work: Work,
        batch: UUID | None = None,
        failure: Literal["worker_failure", "source_policy_changed"] | None = None,
    ) -> str:
        scope = work.lease
        with bound(scope), self._tenant(scope.organization, Capability.ACQUIRE_SOURCE) as c:
            return str(
                c.execute(
                    text(
                        """
SELECT emailmonitor.execution_finish(:org, :job, :item, :token, :batch, :failure,
:event)
"""
                    ),
                    {
                        "org": scope.organization,
                        "job": scope.job,
                        "item": scope.item,
                        "token": scope.token,
                        "batch": batch,
                        "failure": failure,
                        "event": uuid4(),
                    },
                ).scalar_one()
            )

    def process_fixture(
        self,
        work: Work,
        after_observation: Callable[[], None] | None = None,
        *,
        pdf_parser: PdfParser | None = None,
    ) -> str:
        from emailmonitor.fetching.safety import IsolationUnavailable
        from emailmonitor.sources.provider_documents import URLS

        if work.url in URLS:
            raise IsolationUnavailable("controlled_provider_dispatch_required")
        scope = work.lease
        with bound(scope):
            current, request = self.discovery.read_for_work(scope.organization, scope.job)
            state = DiscoveryState.model_validate(current["checkpoint"])
            if work.kind == "discover":
                if work.url not in state.pages:
                    step_fixture(
                        self.discovery, scope.organization, scope.job, int(str(current["revision"]))
                    )
                return self.finish(work)
            existing = next(
                (
                    r
                    for r in self.extraction.read(scope.organization, scope.job)
                    if r["article_url"] == work.url
                ),
                None,
            )
            if existing is None:
                if request.reuse is not None:
                    raise AuthorizationDenied()
                if work.url.endswith(".pdf"):
                    from emailmonitor.extraction.pdf_service import PdfExtraction

                    existing = PdfExtraction(
                        self.database, self.token, self.settings, parser=pdf_parser
                    ).isolated_fixture(
                        scope.organization, scope.job, work.url, int(str(current["revision"]))
                    )
                elif work.url == "https://synthetic.publisher.example/article-xml.xml":
                    from emailmonitor.extraction.xml_service import XmlExtraction

                    existing = XmlExtraction(
                        self.database, self.token, self.settings
                    ).isolated_fixture(scope.organization, scope.job, int(str(current["revision"])))
                else:
                    existing = self.extraction.fixture(
                        scope.organization, scope.job, work.url, int(str(current["revision"]))
                    )
            if after_observation is not None:
                after_observation()
            batch = self.associations.derive(
                scope.organization, scope.job, work.url, int(str(existing["revision"]))
            )
            # Static fixtures never impersonate an actual browser. A dynamic result
            # enters through the separately trusted isolated composition only.
            return self.finish(work, batch)

    def confirmed(self, org: UUID, job: UUID, event: UUID) -> None:
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as c:
            c.execute(
                text("""
SELECT emailmonitor.execution_confirmed(:org, :job, :event)
"""),
                {"org": org, "job": job, "event": event},
            )

    def reconcile(self, org: UUID, job: UUID) -> None:
        with self._tenant(org, Capability.ACQUIRE_SOURCE) as c:
            c.execute(
                text("""
SELECT emailmonitor.execution_reconcile(:org, :job, :event)
"""),
                {"org": org, "job": job, "event": uuid4()},
            )

    def items(self, org: UUID, job: UUID) -> list[Item]:
        with self._tenant(org, Capability.READ_ORGANIZATION) as c:
            self._read_scope(c, org, job)
            rows = c.execute(
                text(
                    "SELECT id,work_kind,state,reason,attempts,batch_id,completed_at,"
                    "inherited_job_id,inherited_item_id "
                    "FROM emailmonitor.execution_items WHERE organization_id=:org "
                    "AND job_id=:job ORDER BY id LIMIT 100"
                ),
                {"org": org, "job": job},
            ).mappings()
            result = [Item.model_validate(dict(row)) for row in rows]
            self._read_scope(c, org, job)
            return result

    def events(self, org: UUID, job: UUID, after: int) -> list[Event]:
        if type(after) is not int or not 0 <= after <= 9223372036854775807:
            raise ValueError("Bounded replay sequence required")
        with self._tenant(org, Capability.READ_ORGANIZATION) as c:
            self._read_scope(c, org, job)
            latest = c.execute(
                text(
                    "SELECT last_sequence FROM emailmonitor.execution_runs "
                    "WHERE organization_id=:org AND job_id=:job"
                ),
                {"org": org, "job": job},
            ).scalar_one_or_none()
            if after > (latest or 0):
                raise ValueError("Future replay cursor denied")
            rows = c.execute(
                text("""
SELECT organization_id, job_id, sequence, event_id, event_type,
aggregate_version, item_id, batch_id, association_id, occurred_at FROM
emailmonitor.execution_events
WHERE organization_id=:org AND job_id=:job AND sequence>:after ORDER BY sequence LIMIT
100
"""),
                {"org": org, "job": job, "after": after},
            ).mappings()
            result = [
                Event.model_validate_json(
                    json.dumps(
                        {**dict(row), "occurred_at": row["occurred_at"].isoformat()}, default=str
                    )
                )
                for row in rows
            ]
            self._read_scope(c, org, job)
            return result

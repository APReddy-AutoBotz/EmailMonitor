"""Short authoritative transactions; queue delivery never authorizes tenant access."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import Connection, text

from emailmonitor.config import Settings
from emailmonitor.jobs.models import JobRequest, canonical, effect_key
from emailmonitor.organizations.database import AuthorizationDenied, Database
from emailmonitor.organizations.roles import Capability
from emailmonitor.sources.access import current_policy, policy_decision
from emailmonitor.sources.policy import Evaluation, Operation, PolicyProposal


@dataclass(frozen=True)
class Work:
    organization: UUID
    job: UUID
    item: UUID
    event: UUID

    def message(
        self, kind: str = "job.queued", generation: int = 1, occurred_at: datetime | None = None
    ) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "event_id": str(self.event),
            "event_type": kind,
            "occurred_at": (occurred_at or datetime.now(UTC)).isoformat(),
            "organization_id": str(self.organization),
            "aggregate_type": "job",
            "aggregate_id": str(self.job),
            "aggregate_version": generation,
            "correlation_id": str(self.job),
            "causation_id": None,
            "payload": {"job_id": str(self.job), "item_id": str(self.item)},
        }

    @classmethod
    def parse(cls, body: dict[str, object]) -> "Work":
        required = {
            "schema_version",
            "event_id",
            "event_type",
            "occurred_at",
            "organization_id",
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
            "correlation_id",
            "causation_id",
            "payload",
        }
        payload = body.get("payload")
        if (
            set(body) != required
            or body["schema_version"] != "1.0"
            or body["aggregate_type"] != "job"
            or body["event_type"] not in {"job.queued", "job.item_terminal"}
            or not isinstance(payload, dict)
            or set(payload) != {"job_id", "item_id"}
            or type(body["aggregate_version"]) is not int
            or int(str(body["aggregate_version"])) < 1
            or body["causation_id"] is not None
        ):
            raise ValueError("Bounded identifier-only event envelope required")
        if body["aggregate_id"] != payload["job_id"] or body["correlation_id"] != payload["job_id"]:
            raise ValueError("Event aggregate identifiers must agree")
        timestamp = datetime.fromisoformat(str(body["occurred_at"]))
        if timestamp.tzinfo is None:
            raise ValueError("Event timestamp must be timezone-aware")
        return cls(
            UUID(str(body["organization_id"])),
            UUID(str(payload["job_id"])),
            UUID(str(payload["item_id"])),
            UUID(str(body["event_id"])),
        )


@dataclass(frozen=True)
class Lease:
    work: Work
    token: UUID
    generation: int
    input_digest: str
    deletion_generation: int


class Ledger:
    def __init__(self, database: Database, token: str, settings: Settings) -> None:
        self.database, self.token, self.settings = database, token, settings

    def _fixture(self) -> None:
        if self.settings.environment != "test" or not self.settings.fixture_mode:
            raise ValueError("Diagnostic worker requires explicit synthetic fixture test mode")

    @staticmethod
    def _lock(c: Connection, organization: UUID, job: UUID) -> dict[str, object]:
        c.execute(
            text(
                "SELECT set_config('lock_timeout','2000ms',true), "
                "set_config('statement_timeout','5000ms',true)"
            )
        )
        row = (
            c.execute(
                text("""
SELECT j.*, o.deletion_generation FROM emailmonitor.jobs j
JOIN emailmonitor.organizations o ON o.id=j.organization_id
WHERE j.organization_id=:org AND j.id=:job AND
emailmonitor.job_write_allowed(:org, :job) FOR UPDATE OF j
"""),
                {"org": organization, "job": job},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise AuthorizationDenied()
        c.execute(
            text("SELECT emailmonitor.job_permission_fence(:org,:job)"),
            {"org": organization, "job": job},
        )
        return dict(row)

    @staticmethod
    def _finish(c: Connection, organization: UUID, job: UUID) -> None:
        counts = (
            c.execute(
                text("""SELECT count(*) AS total,
count(*) FILTER (WHERE state NOT IN ('succeeded','failed','cancelled')) AS active,
count(*) FILTER (WHERE state='succeeded') AS succeeded FROM emailmonitor.job_items
WHERE organization_id=:org AND job_id=:job"""),
                {"org": organization, "job": job},
            )
            .mappings()
            .one()
        )
        if not counts["total"] or counts["active"]:
            return
        state = (
            "completed"
            if counts["succeeded"] == counts["total"]
            else "completed_partial"
            if counts["succeeded"]
            else "failed"
        )
        # A resumed exhausted job may have no claimable item; preserve legal transitions.
        c.execute(
            text("""UPDATE emailmonitor.jobs SET state='running'
WHERE organization_id=:org AND id=:job AND state='queued'"""),
            {"org": organization, "job": job},
        )
        c.execute(
            text("""UPDATE emailmonitor.jobs SET state=:state
WHERE organization_id=:org AND id=:job AND state='running'"""),
            {"org": organization, "job": job, "state": state},
        )

    @staticmethod
    def _policy(c: Connection, organization: UUID, job: dict[str, object]) -> None:
        row = current_policy(c, organization, str(job["source_id"]))
        if not policy_decision(
            row,
            Evaluation(
                expected_version=int(str(job["policy_version"])),
                execution_mode="fixture",
                operation=Operation.HTML,
                host="synthetic.publisher.example",
                path="/article-a.html",
            ),
        ):
            raise AuthorizationDenied()

    @staticmethod
    def _event(
        c: Connection,
        org: UUID,
        job: UUID,
        item: UUID,
        generation: int,
        attempt: int,
        kind: str = "job.queued",
    ) -> Work:
        event = uuid5(job, canonical([str(item), generation, attempt, kind]))
        c.execute(
            text("""
INSERT INTO emailmonitor.job_outbox (organization_id, event_id, job_id, item_id,
generation, event_type, aggregate_version)
VALUES(:org, :event, :job, :item, :generation, :kind,
(SELECT row_version FROM emailmonitor.jobs WHERE organization_id=:org AND id=:job))
ON CONFLICT DO NOTHING
"""),
            {
                "org": org,
                "event": event,
                "job": job,
                "item": item,
                "generation": generation,
                "kind": kind,
            },
        )
        return Work(org, job, item, event)

    def create(self, organization: UUID, request: JobRequest, key: str) -> UUID:
        if not 1 <= len(key) <= 200 or not key.isascii() or any(ord(c) < 33 for c in key):
            raise ValueError("Bounded printable idempotency key required")
        body = canonical(request.model_dump(mode="json", exclude_none=True))
        payload, key_hash = (
            hashlib.sha256(body.encode()).hexdigest(),
            hashlib.sha256(key.encode()).hexdigest(),
        )
        with self.database.tenant(self.token, organization, Capability.ACQUIRE_SOURCE) as (c, ctx):
            # Serialize the same actor/key without retaining the raw key.
            lock = int(
                hashlib.sha256(
                    canonical([str(organization), str(ctx.identity_id), key_hash]).encode()
                ).hexdigest()[:15],
                16,
            )
            c.execute(
                text("""
SELECT pg_advisory_xact_lock(:lock)
"""),
                {"lock": lock},
            )
            params = {"org": organization, "actor": ctx.identity_id, "key": key_hash}
            c.execute(
                text("""
DELETE FROM emailmonitor.job_idempotency WHERE organization_id=:org AND actor_id=:actor
AND route='jobs.create' AND key_hash=:key AND expires_at<=now()
"""),
                params,
            )
            prior = (
                c.execute(
                    text("""
SELECT job_id, payload_hash FROM emailmonitor.job_idempotency WHERE organization_id=:org
AND actor_id=:actor AND route='jobs.create' AND key_hash=:key
"""),
                    params,
                )
                .mappings()
                .first()
            )
            if prior:
                if prior["payload_hash"] != payload:
                    raise HTTPException(409, "Idempotency key payload conflict")
                return UUID(str(prior["job_id"]))
            job = uuid4()
            c.execute(
                text("""
INSERT INTO emailmonitor.jobs (organization_id, id, created_by, kind, request, state)
VALUES(:org, :job, :actor, 'extraction', CAST(:body AS jsonb), 'draft')
"""),
                {**params, "job": job, "body": body},
            )
            self._lock(c, organization, job)
            c.execute(
                text("""
INSERT INTO emailmonitor.job_idempotency (organization_id, actor_id, route, key_hash,
payload_hash, job_id) VALUES(:org, :actor, 'jobs.create', :key, :payload, :job)
"""),
                {**params, "payload": payload, "job": job},
            )
            c.execute(
                text("""INSERT INTO emailmonitor.audit_events
(organization_id,id,actor_id,action,resource_id)
VALUES(:org,:id,:actor,'job.created',:job)"""),
                {"org": organization, "id": uuid4(), "actor": ctx.identity_id, "job": job},
            )
            return job

    def create_probe(self, organization: UUID, version: int, count: int = 1) -> UUID:
        self._fixture()
        if type(count) is not int or not 1 <= count <= 20:
            raise ValueError("Fixture probe count must be 1..20")
        job = uuid4()
        with self.database.tenant(self.token, organization, Capability.ACQUIRE_SOURCE) as (c, ctx):
            policy = current_policy(c, organization, "synthetic-publisher")
            self._policy(
                c, organization, {"source_id": "synthetic-publisher", "policy_version": version}
            )
            if count > PolicyProposal.model_validate(policy["policy"]).limits.max_articles_per_job:
                raise AuthorizationDenied()
            c.execute(
                text("""
INSERT INTO emailmonitor.jobs (organization_id, id, created_by, kind, request,
source_id, policy_version, state, discovery_complete) VALUES(:org, :job, :actor,
'fixture_probe', '{"diagnostic":"persistence-only"}',  'synthetic-publisher', :version,
'queued', true)
"""),
                {"org": organization, "job": job, "actor": ctx.identity_id, "version": version},
            )
            self._lock(c, organization, job)
            self._policy(
                c, organization, {"source_id": "synthetic-publisher", "policy_version": version}
            )
            for index in range(count):
                item = uuid5(job, str(index))
                value = hashlib.sha256(f"synthetic-unit-{index}".encode()).hexdigest()
                c.execute(
                    text("""
INSERT INTO emailmonitor.job_items (organization_id, job_id, id, input_digest, state)
VALUES(:org, :job, :item, :digest, 'pending')
"""),
                    {"org": organization, "job": job, "item": item, "digest": value},
                )
                c.execute(
                    text("""
SELECT emailmonitor.fixture_reserve(:org, :job, :item)
"""),
                    {"org": organization, "job": job, "item": item},
                )
                self._event(c, organization, job, item, 1, 0)
        return job

    def claim(self, work: Work, lease_seconds: int = 30) -> Lease | None:
        self._fixture()
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
            raise ValueError("Lease duration must be bounded")
        with self.database.tenant(self.token, work.organization, Capability.ACQUIRE_SOURCE) as (
            c,
            ctx,
        ):
            job = self._lock(c, work.organization, work.job)
            event = (
                c.execute(
                    text("""
SELECT generation, event_type FROM emailmonitor.job_outbox WHERE organization_id=:org
AND event_id=:event AND job_id=:job AND item_id=:item
"""),
                    {
                        "org": work.organization,
                        "event": work.event,
                        "job": work.job,
                        "item": work.item,
                    },
                )
                .mappings()
                .first()
            )
            if event is None:
                return None
            c.execute(
                text("""INSERT INTO emailmonitor.audit_events
(organization_id,id,actor_id,action,resource_id)
VALUES(:org,:id,:actor,'fixture.delivery.received',:event)"""),
                {
                    "org": work.organization,
                    "id": uuid4(),
                    "actor": ctx.identity_id,
                    "event": work.event,
                },
            )
            if job["kind"] != "fixture_probe" or job["state"] not in ("queued", "running"):
                return None
            self._policy(c, work.organization, job)
            if (
                not event
                or event["generation"] != job["generation"]
                or event["event_type"] != "job.queued"
            ):
                return None
            lease = uuid4()
            row = c.execute(
                text("""
UPDATE emailmonitor.job_items SET state='running',  lease_token=:lease,
lease_until=clock_timestamp()+make_interval(secs=>:seconds), lease_generation=:generation,
lease_deletion_generation=:deletion,
attempts=attempts+1 WHERE organization_id=:org AND job_id=:job AND id=:item AND state IN
('pending', 'retry_wait') AND attempts<5 RETURNING input_digest
"""),
                {
                    "org": work.organization,
                    "job": work.job,
                    "item": work.item,
                    "lease": lease,
                    "seconds": lease_seconds,
                    "generation": job["generation"],
                    "deletion": job["deletion_generation"],
                },
            ).scalar()
            if row is None:
                return None
            if job["state"] == "queued":
                c.execute(
                    text(
                        """
UPDATE emailmonitor.jobs SET state='running' WHERE organization_id=:org AND id=:job
"""
                    ),
                    {"org": work.organization, "job": work.job},
                )
            return Lease(
                work,
                lease,
                int(str(job["generation"])),
                str(row),
                int(str(job["deletion_generation"])),
            )

    def commit(self, lease: Lease) -> bool:
        self._fixture()
        work = lease.work
        with self.database.tenant(self.token, work.organization, Capability.ACQUIRE_SOURCE) as (
            c,
            _,
        ):
            job = self._lock(c, work.organization, work.job)
            if (
                job["state"] != "running"
                or job["generation"] != lease.generation
                or job["deletion_generation"] != lease.deletion_generation
            ):
                return False
            self._policy(c, work.organization, job)
            effect = effect_key(
                str(work.organization), str(work.job), str(work.item), lease.input_digest
            )
            changed = c.execute(
                text("""
UPDATE emailmonitor.job_items SET state='succeeded',  result=CAST(:result AS jsonb),
effect_key=:effect, completed_lease_token=:lease, lease_token=NULL, lease_until=NULL,
lease_generation=NULL, lease_deletion_generation=NULL WHERE
organization_id=:org AND job_id=:job AND id=:item AND state='running' AND
lease_token=:lease AND lease_generation=:generation AND lease_deletion_generation=:deletion
AND lease_until>clock_timestamp() AND
input_digest=:digest RETURNING id
"""),
                {
                    "org": work.organization,
                    "job": work.job,
                    "item": work.item,
                    "lease": lease.token,
                    "generation": lease.generation,
                    "deletion": lease.deletion_generation,
                    "digest": lease.input_digest,
                    "effect": effect,
                    "result": canonical({"diagnostic": "persistence-only"}),
                },
            ).scalar()
            if changed is None:
                return False
            c.execute(
                text("""
SELECT emailmonitor.fixture_settle(:org, :job, :item, :effect)
"""),
                {"org": work.organization, "job": work.job, "item": work.item, "effect": effect},
            )
            self._finish(c, work.organization, work.job)
            self._event(
                c, work.organization, work.job, work.item, lease.generation, 0, "job.item_terminal"
            )
            return True

    def outbox(self, organization: UUID) -> list[Work]:
        self._fixture()
        with self.database.tenant(self.token, organization, Capability.ACQUIRE_SOURCE) as (c, _):
            rows = c.execute(
                text("""
SELECT job_id, item_id, event_id FROM emailmonitor.job_outbox WHERE organization_id=:org
AND published_at IS NULL AND emailmonitor.job_write_allowed(:org, job_id) ORDER BY
created_at LIMIT 100
"""),
                {"org": organization},
            ).mappings()
            return [
                Work(
                    organization,
                    UUID(str(r["job_id"])),
                    UUID(str(r["item_id"])),
                    UUID(str(r["event_id"])),
                )
                for r in rows
            ]

    def envelope(self, work: Work) -> dict[str, object]:
        self._fixture()
        with self.database.tenant(self.token, work.organization, Capability.ACQUIRE_SOURCE) as (
            c,
            _,
        ):
            row = (
                c.execute(
                    text("""SELECT aggregate_version,event_type,created_at
FROM emailmonitor.job_outbox WHERE organization_id=:org AND event_id=:event
AND job_id=:job AND item_id=:item AND emailmonitor.job_write_allowed(:org,:job)"""),
                    {
                        "org": work.organization,
                        "event": work.event,
                        "job": work.job,
                        "item": work.item,
                    },
                )
                .mappings()
                .one()
            )
            return work.message(
                str(row["event_type"]), int(row["aggregate_version"]), row["created_at"]
            )

    def confirmed(self, work: Work) -> None:
        self._fixture()
        with self.database.tenant(self.token, work.organization, Capability.ACQUIRE_SOURCE) as (
            c,
            _,
        ):
            c.execute(
                text("""
UPDATE emailmonitor.job_outbox SET published_at=now() WHERE organization_id=:org AND
event_id=:event AND job_id=:job AND item_id=:item
"""),
                {"org": work.organization, "event": work.event, "job": work.job, "item": work.item},
            )

    def control(self, organization: UUID, job_id: UUID, action: str, revision: int) -> None:
        with self.database.tenant(self.token, organization, Capability.ACQUIRE_SOURCE) as (c, ctx):
            job = self._lock(c, organization, job_id)
            if job["row_version"] != revision:
                raise HTTPException(409, "Job revision conflict")
            c.execute(
                text("""INSERT INTO emailmonitor.audit_events
(organization_id,id,actor_id,action,resource_id) VALUES(:org,:id,:actor,:action,:job)"""),
                {
                    "org": organization,
                    "id": uuid4(),
                    "actor": ctx.identity_id,
                    "action": "job." + action,
                    "job": job_id,
                },
            )
            state = str(job["state"])
            if action == "cancel" and state == "draft":
                c.execute(
                    text(
                        """
UPDATE emailmonitor.jobs SET state='cancelled', generation=generation+1 WHERE
organization_id=:org AND id=:job
"""
                    ),
                    {"org": organization, "job": job_id},
                )
                return
            if job["kind"] != "fixture_probe":
                raise HTTPException(409, "Extraction planning is not implemented")
            target = {"pause": "pausing", "cancel": "cancelling", "resume": "queued"}.get(action)
            allowed = (action in ("pause", "cancel") and state in ("queued", "running")) or (
                action in ("resume", "cancel") and state == "paused"
            )
            if not target or not allowed:
                raise HTTPException(409, "Job state conflict")
            if action == "resume":
                self._policy(c, organization, job)
            increment = int(action != "resume")
            c.execute(
                text(
                    """
UPDATE emailmonitor.jobs SET state=:state, generation=generation+:increment WHERE
organization_id=:org AND id=:job
"""
                ),
                {"org": organization, "job": job_id, "state": target, "increment": increment},
            )
            rows = (
                c.execute(
                    text("""
UPDATE emailmonitor.job_items SET state=CASE WHEN :state='cancelled' THEN 'cancelled'
WHEN attempts>=5 THEN 'failed' ELSE 'pending' END, lease_token=NULL, lease_until=NULL,
lease_generation=NULL, lease_deletion_generation=NULL WHERE organization_id=:org
AND job_id=:job AND state IN
('pending', 'running', 'retry_wait') RETURNING id, attempts, state
"""),
                    {
                        "org": organization,
                        "job": job_id,
                        "state": "cancelled" if action == "cancel" else "pending",
                    },
                )
                .mappings()
                .all()
            )
            for row in rows:
                item = UUID(str(row["id"]))
                if action == "cancel" or row["state"] == "failed":
                    c.execute(
                        text("""
SELECT emailmonitor.fixture_settle(:org, :job, :item, NULL)
"""),
                        {"org": organization, "job": job_id, "item": item},
                    )
                elif action == "resume":
                    self._event(
                        c,
                        organization,
                        job_id,
                        item,
                        int(str(job["generation"])),
                        int(row["attempts"]),
                    )
            if action != "resume":
                c.execute(
                    text(
                        """
UPDATE emailmonitor.jobs SET state=:state WHERE organization_id=:org AND id=:job
"""
                    ),
                    {
                        "org": organization,
                        "job": job_id,
                        "state": "cancelled" if action == "cancel" else "paused",
                    },
                )
            else:
                self._finish(c, organization, job_id)

    def reconcile(self, organization: UUID, job_id: UUID) -> int:
        self._fixture()
        with self.database.tenant(self.token, organization, Capability.ACQUIRE_SOURCE) as (c, _):
            job = self._lock(c, organization, job_id)
            if job["state"] not in ("queued", "running"):
                return 0
            self._policy(c, organization, job)
            c.execute(
                text("""
UPDATE emailmonitor.job_items SET state=CASE WHEN attempts>=5 THEN 'failed' ELSE
'retry_wait' END, lease_token=NULL, lease_until=NULL, lease_generation=NULL,
lease_deletion_generation=NULL WHERE
organization_id=:org AND job_id=:job AND ((state='running' AND lease_until<=clock_timestamp())
OR (state IN ('pending','retry_wait') AND attempts>=5))
"""),
                {"org": organization, "job": job_id},
            )
            rows = (
                c.execute(
                    text(
                        """
SELECT id, attempts, state FROM emailmonitor.job_items WHERE organization_id=:org AND
job_id=:job AND state IN ('pending', 'retry_wait', 'failed')
"""
                    ),
                    {"org": organization, "job": job_id},
                )
                .mappings()
                .all()
            )
            for row in rows:
                item = UUID(str(row["id"]))
                if row["state"] == "failed":
                    c.execute(
                        text("""
SELECT emailmonitor.fixture_settle(:org, :job, :item, NULL)
"""),
                        {"org": organization, "job": job_id, "item": item},
                    )
                    continue
                work = self._event(
                    c, organization, job_id, item, int(str(job["generation"])), int(row["attempts"])
                )
                c.execute(
                    text(
                        """
UPDATE emailmonitor.job_outbox SET published_at=NULL WHERE organization_id=:org AND
event_id=:event
"""
                    ),
                    {"org": organization, "event": work.event},
                )
            self._finish(c, organization, job_id)
            return len(rows)

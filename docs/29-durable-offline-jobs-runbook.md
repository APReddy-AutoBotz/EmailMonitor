# 29 — Durable offline jobs runbook

## Boundary

EM-005 adds PostgreSQL jobs/items, identifier-only domain event envelopes, transactional outbox, deterministic persistence effects, quota reservations, usage records, lease/attempt fences, pause/cancel/recovery and organization deletion generations. The original keyword/URL request can be created only as a **draft** in the explicit test foundation API. Planning/start/continuation remain unavailable until EM-006. The default CLI and UI remain metadata-only/unavailable extraction.

Diagnostic `fixture_probe` jobs persist only a `persistence-only` marker. They do not fetch, parse, discover articles, create contacts or measure extraction accuracy. A finite explicit diagnostic list is the only exhaustion evidence; its completion cannot be reported as an extraction UAT result. No network-dependent task bypasses full EM-004.

## Database and privileges

Apply the third Alembic migration with the separate disposable admin connection, then use the existing direct non-owner runtime connection. All seven new tables enable and force tenant RLS. Composite keys bind child resources to their tenant/job. Operator mutation is limited to jobs they created; owner/admin/steward can manage tenant jobs. Read-only members cannot create or claim work. Quota/reservation/usage tables have no direct runtime mutation grants: bounded definer functions authorize the current tenant/job, serialize quota changes and require a committed fixture result before consuming one diagnostic unit. This is a synthetic capacity test budget, not a commercial entitlement or billing policy.

The permission-fence function only locks/revalidates existing organization, membership, identity, session and current source-policy rows. It cannot create identities/sessions or assume authentication/owner roles. Result transactions hold those locks through commit, while diagnostic work occurs outside transactions. Transactions use bounded lock/statement timeouts. Policy expiry is checked at commit; stale versions, lifecycle barriers and revoked sessions deny commits.

Offboarding/deleted transitions increment the organization's deletion generation. Job pause/cancel increments its generation; stale leases fail generation/token/expiry checks. Terminal jobs/items cannot be reopened or overwritten. A shared finalizer inspects every item before closing a job; live leases prevent terminalization, mixed success/exhaustion is partial completion, and a final-attempt pause settles its exhausted reservation. The SQL success guard requires the captured prior lease token, unexpired lease, current job/deletion generations and locked current source permission. Record tombstones, artifacts and actual retention deletion remain EM-014; the generation primitive does not claim those features.

Migration downgrade intentionally refuses destructive removal of durable jobs/usage/audit. Recover with reviewed forward repair; never drop a customer schema. Empty-schema rebuilds in tests use only disposable synthetic state.

## Local checks

Use the PostgreSQL setup and three explicit test URLs from [tenant runbook](26-tenant-foundation-runbook.md), then run `scripts/check_tenant_foundation.sh`. Without a disposable RabbitMQ URL, four real-broker tests explicitly skip and broker acceptance remains pending. `EM_REQUIRE_REAL_BROKER=true` converts a missing broker into a failure. Never point test URLs at a real account, customer database or external broker.

The worker import target `emailmonitor.jobs.fixture_worker:app` requires `EM_FIXTURE_WORKER=true` and a temporary JSON file selected by `EM_FIXTURE_WORKER_CONFIG`. `FixtureWorkerConfig` accepts only environment `test`, loopback PostgreSQL/pyamqp URLs, bounded diagnostic delay/lease and an isolated `em-fixture-*` queue. Tests create/remove that file with a synthetic session obtained through the normal fixture login. Do not store it in Git or configure a real identity. Each transaction revalidates that current session and tenant; queue messages carry no session, credentials, source URL, article or contact data. A future production worker principal and verifier/process isolation need a separate reviewed design before production activation.

## Actual broker CI gate

Application CI starts pinned official disposable PostgreSQL and RabbitMQ images. RabbitMQ uses an isolated synthetic user and durable quorum queues; JSON-only Celery tasks use publisher confirms, persistent delivery, late acknowledgements, worker-loss redelivery and prefetch one. Remote control/result backend are disabled. Outbox publication marks acceptance only after a confirmed send. An uncertain send can be replayed; unique effects/usage—not Celery's acknowledgement setting—prevent duplicate persistence.

Four tests use an actual Celery subprocess and real RabbitMQ: duplicate publish; process kill after lease before commit with expiry/reconciliation; explicit fixture exit after commit before acknowledgement followed by observed original-message broker redelivery, without a manual duplicate masking that evidence; and stop/start of the workflow's own ephemeral RabbitMQ application with unpublished outbox recovery. The last test accepts only GitHub Actions and its provided alphanumeric service-container ID; it never changes host network/security settings. Delays/exit injection are synthetic failure instrumentation, unavailable outside the test-only worker configuration. Broker/service success must be observed on the exact published tree before acceptance.

Production transport, commercial billing, fair shared source admission, long-running extraction lease heartbeats, extraction result persistence, real source acquisition and full EM-004 isolation are separate gates. See [evidence](../reports/em005-validation.md).

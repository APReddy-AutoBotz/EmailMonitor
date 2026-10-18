# 57 — EM-017g owned test outbox publisher

## Scope

This bounded [runtime prerequisite](56-owned-test-runtime.md) owns the transport resources for one finite execution/export outbox publication pass. It is trusted Python test composition, with explicit disposable loopback configuration. It adds no listener, supervisor, worker identity, account, credential registration, migration or deployment. Existing production and real-source refusals remain.

The caller retains its Celery application, SQL pools, worker processes and source gateway. The publisher owns only its independently constructed broker connection, channel and producer. It never deletes queues, closes the borrowed application or performs global pool cleanup.

## Configuration and transport

The frozen configuration excludes the broker URL from representation. Entry-time revalidation requires explicit test mode, a single credentialed loopback pyamqp endpoint with explicit port/vhost, and the existing synthetic queue namespace. Effective application broker targets must match, including Celery environment overrides. Current JSON, publisher confirms and configured/effective owned durable quorum declarations are checked before transport acquisition. Configured/effective custom routing and result backends refuse; cached result backends must be the exact disabled implementation. Explicit ignored results prevent backend task callbacks while preserving the normal Celery protocol. SQL session/tenant checks remain authoritative.

The private adapter supplies an explicitly owned concrete producer to the existing public Celery send_task path. Existing execution/export publishers retain identifier-only bodies, fixed server-owned phases, persistent mandatory delivery, retry=False and SQL publication markers only after confirmed send returns. Celery still accesses lazy global pool metadata; the scoped guarantee is no pooled producer/connection acquisition for these sends, not absence of any pool reference.

One pass invokes the existing bounded execution snapshot, then the existing bounded export snapshot. Initial explicit connection establishment uses no retry; the subsequent public Kombu channel call can reconnect if its local connection state was cleared. Publication retry remains disabled. Fixed socket/publish/confirmation timeouts do not create a total pass deadline: SQL calls and channel operations retain their separate behavior. No broad broker retry loop or alternate transport is introduced.

## Failure and cleanup

A send or SQL-marker failure stops the pass. Earlier committed markers remain; uncertain or unmarked messages remain eligible for replay through the durable outbox. Duplicate delivery remains expected, with existing worker leases/effect keys providing idempotency.

The private adapter is invalidated before cleanup. Channel and connection cleanup are both attempted after normal execution or partial failure; a cleanup failure cannot prevent the other attempt. Public errors use fixed categories rather than broker credentials. A producer release alone is insufficient with the pinned Kombu implementation and is not treated as connection cleanup.

## Acceptance and limits

[Validation](../reports/em017g-validation.md) distinguishes pure lifecycle/protocol tests, actual SQL/RabbitMQ partial-publication and replay checks, and the normal controlled operator journey. Failure injection is identified precisely; a nonexistent exchange is a broker channel error, not proof of a broker outage or Nack. Actual connection/channel closure and caller-resource survival are required alongside durable effects.

The operator acceptance changes only its publication composition. Its authenticated create/plan/start, protected HTTPS, isolated parser, tenant review and CSV/XLSX path remains required, as do all seven own-head workflows. Existing browser/static/provider deadlines, source-policy preconditions and sole-worker pipe ownership remain unchanged.

This is test-only lifecycle preparation. Real worker service identity, private regional storage/secrets, complete hosted/dedicated runtime assembly, staging upgrades/restores and authorized real-source samples remain separate gates. Rollback removes the optional helper and restores prior caller publication; there is no migration or deployed state.

# ADR-0004 — Durable jobs, outbox and idempotent effects

Date: 2026-10-08. Status: selected design baseline.

## Context

A search can produce thousands of article URLs. Workers can crash; queues can redeliver; users can cancel; source permissions can change. An in-memory script or queue-only state cannot support reliable customer operations.

## Decision

PostgreSQL stores job/item/checkpoint state, reservations, usage effects and outbox. RabbitMQ carries minimal JSON task references. Workers claim expiring leases with fencing tokens, validate authoritative tenant/job/policy state and commit results plus successor outbox events transactionally. Unique effect keys prevent duplicate durable records/usage under replay. Reconciler repairs stale leases/unpublished work.

Delivery is at least once, not exactly once. No long database transaction spans an internet fetch. Pause/cancel/deletion are generation-aware and checked before final commit. Broker loss is recoverable from the database ledger. Explicit finite deadlines and resource quotas apply to every work unit.

## Consequences

Extra ledger/reconciliation code is necessary, but it makes recovery and customer-visible progress auditable. Do not rely on Celery acknowledgement settings alone. Separate operational attempts from billable units. Test failure before/after commit, not only ordinary successful runs.

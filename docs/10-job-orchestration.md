# 10 — Job lifecycle, queues and recovery

**Baseline:** 2026-10-08. PostgreSQL is authoritative; Celery/RabbitMQ transports work. At-least-once delivery requires idempotent effects, explicit timeouts and worker-loss handling [S02].

## Job states

`draft`, `awaiting_approval`, `ready`, `queued`, `running`, `pausing`, `paused`, `cancelling`, `cancelled`, `completed`, `completed_partial`, `failed`.

| From | Event/condition | To |
|---|---|---|
| draft | Valid plan and current source/purpose approval | ready |
| draft | Valid input but permission/credential review needed | awaiting_approval |
| awaiting_approval | Approval and preflight succeed | ready |
| ready | Start with quota reservation committed | queued |
| queued | First lease accepted | running |
| queued/running | User/source/tenant pause | pausing |
| pausing | In-flight units drained or fenced | paused |
| paused | Resume revalidates scope/policy/quota | queued |
| draft/awaiting_approval/ready/queued/running/pausing/paused | Cancel | cancelling |
| cancelling | New work blocked and outstanding units fenced | cancelled |
| running | Discovery exhausted and all items terminal without execution gaps | completed |
| running | Work ended with truncation/access/policy/unsupported/failed gaps | completed_partial |
| queued/running | Fatal unrecoverable planning/infrastructure failure prevents useful execution | failed |

Terminal job states do not silently reopen. Retry creates an auditable continuation attempt linked to the original job; item effect keys and retained results prevent double charging. A source or tenant revocation always overrides a previously ready/queued plan.

A job may be `completed` while some articles genuinely have no contact or some associations await review: execution completeness and data/identity quality are different dimensions. `completed_partial` explicitly means enumeration or execution gaps, not simply 'some authors lack email'.

## Item states and stages

Item states: `pending`, `running`, `retry_wait`, `succeeded`, `no_contact`, `needs_review`, `policy_blocked`, `access_blocked`, `unsupported`, `skipped`, `failed`, `cancelled`.

Stages: discover, fetch, parse, associate, persist. Export is a separate job type linked to a result snapshot. Terminal item states are all states except pending/running/retry_wait. An item can contain accepted and unresolved authors; its paper-level outcome and association-level counts remain distinct.

No-contact applies only after all selected permitted routes finish without an observed eligible address. If a necessary route is blocked/capped, report that limitation instead of asserting there is no email.

## Work-unit and lease design

Each stage has an immutable work ID and unique effect key derived from organization/job/item/stage/input digest/implementation version. Attempt number is operational metadata, not a new billing identity. Claim a lease transactionally; include fencing token, expiry and job/deletion generation. Heartbeat long work within bounds. A late worker cannot overwrite a newer attempt or resurrect cancelled/deleted data.

Worker flow: load authoritative tenant/job → verify membership-derived authority/source/purpose/current policy/quota → claim lease → fetch/parse bounded input → recheck cancellation/revocation/generation → commit results/effects/outbox/state → acknowledge task. Never hold a database transaction open for a slow internet fetch.

## Outbox and recovery

Producer writes job change and outbox in one transaction. Dispatcher publishes durable JSON messages with confirmation and marks publication. Duplicate publishes are safe. Reconciler inspects unpublished events, expired leases and missing scheduled work; it can rebuild tasks after broker loss. Poison tasks enter a bounded dead-letter/review queue rather than infinite retry.

PostgreSQL backups plus evidence storage recovery determine RPO; RabbitMQ is not the sole record of unfinished work. Avoid `acks_late` as a substitute for reconciliation or idempotency. Configure visibility/lease/timeouts coherently and test actual worker termination, not only mocked retry calls.

## Retry matrix

| Failure | Action |
|---|---|
| 429 / explicit provider Retry-After | Pause shared source bucket; respect delay; retry within attempt/job deadline |
| Connection reset, temporary DNS, 502/503/504 | Bounded exponential backoff with jitter; default max 3 attempts |
| 401/403, login, CAPTCHA, access denial | Mark access_blocked or pause for authorized credential review; no alternate-identity retries |
| Source permission revoked/expired | policy_blocked; stop pending work and invalidate affected exports |
| Parser corruption/resource limit | One controlled retry only if transient evidence supports it; otherwise unsupported/failed with reason |
| Unknown HTML after structural change | Connector degraded; preserve safe metadata; do not call it an empty search |
| Unsafe URL / internal network redirect | Reject; security event; no automatic retry |
| Worker crash | Lease expiry/reconciler; replay same effect key |
| Quota/job wall limit | Stop discovery/scheduling; settle reservations; partial result with exact stop reason |

## Counters and completion

Counters come from durable rows/events: discovery pages, source-reported total nullable, unique articles discovered, pending, active, retry_wait, terminal by outcome, accepted associations, review-needed associations, duplicates, bytes, browser seconds and PDF pages. Reconciliation checks terminal + nonterminal = discovered item total.

`discovery_complete` is true only with positive exhaustion evidence. Stop reasons are a list: exhausted, article_limit, page_limit, depth_limit, source_result_cap, repeated_cursor, repeated_page, no_new_results, quota_exhausted, time_limit, source_blocked, connector_changed, user_cancelled, source_policy_changed. Multiple reasons can apply. Do not convert discovery caps into a fictitious 100% total.

## Fairness and quotas

Separate HTTP, browser, parsing and export worker queues. Enforce a deployment-wide source bucket plus tenant-source and tenant-total budgets. Round-robin/weighted admission prevents a high-volume tenant consuming every browser slot. Source-global limits count browser requests and retries, not just successfully extracted records. Tenant usage ledger separately tracks the billable unit defined in the contract; do not charge the same article resolution twice because of a retry.

Default limits are document 21 proposals. Capacity tests must show that one blocked website or large PDF does not stall every organization.

## Cancellation and data lifecycle

Pause stops new leases and lets bounded work finish; cancellation fences new result commits and terminates browser/download work within configured deadlines. Retain already committed allowed results. Deletion additionally tombstones target records, increments generation, revokes export artifacts and rejects queued stale writes. Every stage checks lifecycle immediately before committing.

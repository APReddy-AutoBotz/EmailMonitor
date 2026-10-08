# 13 — Deployment, delivery and operations

**Baseline:** 2026-10-08. No environment has been deployed. Commands/images/infrastructure are implemented and tested in the backlog, not assumed to exist today.

## Supported topology plan

Development: API, web, PostgreSQL, RabbitMQ, local evidence storage adapter and isolated fixture server/transport. External crawling, AI and mail are off. Authentication fixtures are test-only and production startup must reject them.

Hosted pilot: same application images; TLS ingress; real OIDC provider; managed or operated PostgreSQL/broker; private object storage; secret management; separate HTTP/browser/parser/export workers; controlled egress; backups and centralized redacted telemetry. Multiple organizations share a deployment cell with enforced isolation.

Dedicated customer: separate network/account or customer infrastructure; customer-specific database, broker, storage and keys; approved outbound source routes; same tenant-aware schema and images. Do not create a customer fork. Use an agreed software/support update channel; no silent remote support or license telemetry outside the contract.

## Environment separation

Local, CI, staging and production use separate secrets, identities, storage and source entitlements. Real contact data must not be copied to CI or public fixtures. Production fixtures, insecure cookies, wildcard CORS, disabled TLS and unrestricted egress flags cause startup failure. No default admin password. Database migration identity is separate from runtime roles.

## Configuration and secrets

Validated server configuration with explicit schema; see document 21. Secret values come from a secret manager or tightly permissioned deployment files/environment injection, never a tenant-editable JSON blob. Store reference, scope, last rotated and status only. Rotate source tokens and encryption keys independently. Redact diagnostics and prevent secrets from entering container layers/build args.

## CI/CD requirements

EM-001 introduces actual tested commands for lint/type checks, unit/contract tests, build and docs validation. Later tasks add PostgreSQL integration/RLS tests, broker replay, controlled browser fixtures, security tests and E2E. A CI job should not claim it tests live publisher integration when it runs fixtures.

Use least-privilege workflow tokens, reviewed actions pinned to immutable revisions, dependency lockfiles and cache keys. Pull requests from untrusted forks do not receive production secrets. Never run untrusted PR code with write secrets through pull_request_target. Add SBOM, vulnerability/license scanning and signed image/provenance checks before production. Do not bypass protected-branch checks to publish.

Release flow: reviewed PR → tests → immutable image and migration artifact → staging migration/smoke → source canary under approved limits → owner release gate → gradual deployment → health/tenant-boundary verification. Roll back application image only where schema compatibility permits; otherwise use documented forward repair. Never assume a destructive migration is reversibly safe.

## Initial capacity and SLOs

Reference pilot should document vCPU/RAM, worker counts, broker/database/storage versions, source quotas, article sizes and browser mix. Separate control-plane latency from website processing time. Proposed application API p95 target and restore targets are in the PRD; do not sell them as contractual SLAs before load/restore tests.

Track queue age, tenant wait time, source rate-limit saturation, bytes/pages, browser seconds, parser resource failures, outbox lag, expired leases, association review rate, missing evidence, exports invalidated, object deletion backlog and storage growth. Avoid PII labels and high-cardinality contact-level metrics.

## Health and alerts

Liveness indicates process health, not every external publisher. Readiness checks required local dependencies and version/migration compatibility. A single publisher outage degrades its connector, not every tenant. Alerts: sustained outbox lag; exhausted worker pool; abnormal source 403/429; connector structural drift; failed backup; restore gap; tenant-boundary/security event; deletion backlog exceeding policy; unexpected PII/secrets in logs.

## Runbooks

**Publisher layout change:** disable affected connector version, pause affected jobs, retain checkpoints, reproduce using authorized/synthetic evidence, patch adapter with regression fixtures, canary, then resume with audited version change. Do not silently change query semantics.

**Rate limiting:** respect Retry-After, reduce shared source bucket, inspect aggregate tenant traffic, communicate delayed/partial completion. Do not add sender identities or proxies.

**Worker/broker failure:** fence expired leases, restore broker if needed, replay outbox, reconcile pending/terminal counts and usage effects, verify no duplicate export/contact effect.

**Suspected tenant leak/secret exposure:** stop affected access, revoke credentials/grants, preserve minimal forensic evidence, scope impact, follow contractual/legal notification procedure with counsel, remediate and independently retest. Do not assert a fixed legal deadline across jurisdictions.

**Unsafe document:** quarantine isolated task artifact, terminate parser/browser, record non-content reason, check resource boundaries, delete per policy, add a synthetic regression case.

## Backup and disaster recovery

Back up database plus object manifest/evidence with encryption and restore permissions. Test recovery in an isolated environment with the same RLS/runtime roles. Restore tombstones/suppressions and policy revocations before serving data or resuming jobs. Rebuild broker work from durable ledgers. Verify sample tenant boundaries, artifact hashes, job counts and usage reconciliation.

Proposed pilot RPO is 24 hours and RTO is 8 hours; record actual values in an exercise, including exclusions. Backups may retain deleted information until expiry; don't claim complete erasure until the applicable backup window passes. Customer-specific legal holds require explicit review and restricted access.

## Tenant onboarding/offboarding operations

Provision owner, region, entitlements, identity connection, source policies/credential references and retention. Run a two-tenant boundary check for each new release, not necessarily each customer. On offboarding, suspend new work, provide allowed export, revoke credentials/support grants, execute deletion, record outstanding backup expiry and customer acknowledgement.

## Support model

Maintain severity definitions, named responsibility, response targets and supported version window in customer contracts. The baseline does not promise 24/7 staffing. No remote access by default. Customer-specific failures are reproduced with sanitized fixtures, not copied production contact lists.

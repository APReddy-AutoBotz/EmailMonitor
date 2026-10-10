# 27 — EM-003 offline source registry and policy

Date: 2026-10-10. EM-003 is stacked on reviewed, CI-verified Draft EM-002 head `bed184b`. This task uses synthetic PostgreSQL state and adds no external access, secret manager, paid dependency, live source approval or acquisition client.

## Implemented scope

The server-owned `synthetic-publisher` catalog manifest is read-only to runtime, version 1.0.0, exact host `synthetic.publisher.example`. Its support matrix lists the six committed fixture paths, planned keyword/search/article input classes and truthful acquisition/extraction flags (`false`). No PDF fixture/parser or live route is claimed. The migration/operator principal controls the platform enable flag; tenant approval cannot override it.

Per-organization policies have append-only configuration versions and a locked monotonic current-version head. A proposal creates a new pending-review version and immediately fences any older approval. State changes preserve original configuration/history and increment revision. Pending review may be approved or revoked; approval may be suspended, expired or revoked; suspended may only be revoked. Reapproval requires a new version and explicit review. Historical approved versions never authorize a request for a stale version. Expiry is computed from UTC on every read/evaluation even if the stored historical state remains approved. Review identity/date come from the authorized session/database clock.

Only owners/data stewards may propose and approve source policy. Admin/operator/reviewer/viewer roles can read their authorized tenant's catalog/history but cannot approve. Forced RLS covers both policy heads and versions; composite tenant keys constrain membership and policy relationships. No context or another tenant's session exposes policy rows. Audit records contain tenant/actor/action/resource IDs, no page contents or secrets. The API keeps the existing same-origin/CSRF/session/lifecycle checks.

All fixture policy config is bounded by platform ceilings: one concurrent request, minimum five seconds per request, at most 500 articles, raw retention at most 24 hours, excerpts 30 days, contacts 90 days; explicit operations, exact host, test-only region, fixed fixture/no-network robots handling. These are enforcement ceilings, not measured throughput or actual retention processing. Unknown operation/path mappings or live execution, weaker caps, arbitrary hosts/regions and unimplemented PDF operations are rejected. SQL guards also enforce the immutable fields, allowed config shape/ceilings and transition rules. `evaluate` is a read-only governance decision: `policy_authorized` can be true for a fixture plan while `execution_available` is always false. It creates no job, fetch or export.

## Permission and credentials boundary

The permission reference is a bounded opaque artifact ID, never an uploaded contract or URL carrying credentials. Approval requires a nonempty reference and expiry within 365 days. An ID does not establish legal permission; only synthetic fixture permission is representable here. Acquisition, processing, retention, export and later contact permissions remain distinct operations/fields. No outreach permission is implied.

The contract has a credential-reference field for future source onboarding. The only implemented source requires no credential, so its value must be null. No actual secret/reference resolver, external secret-manager grant or customer publisher token exists. Supporting a credentialed real source requires its approved manifest, tenant-scoped opaque references, protected fetch handling and security/operator review. Do not paste secrets into policy fields/issues. Unknown sources remain unavailable instead of receiving a blanket permission.

## API and validation

The existing explicit test-only Foundation assembly mounts tenant routes:

- GET organization sources: read-only support matrix
- GET source policies: most recent 100 versions, effective expiry/export status
- POST source policies: expected current version plus bounded policy proposal
- POST source policy-state: expected version/revision plus approval/suspension/revocation
- POST source evaluate: expected version, exact host/path/operation and fixture/live mode; no side effect

Normal CLI is still metadata-only, and production refuses identity-stub/provider assembly. There is no source UI pretending the extractor works. Run `scripts/check_tenant_foundation.sh` with the three disposable admin/authentication/runtime URLs from [EM-002 runbook](26-tenant-foundation-runbook.md). It applies both migrations, repeats upgrade and runs the complete real SQL/API/scaffold/contract/fixture/frontend gates. Without URLs, integration skips are not acceptance. [Validation evidence](../reports/em003-validation.md) records actual output and remaining review/CI gates.

## Migration and next gate

`0002_source_policy` creates catalog, heads and policy versions, composite foreign keys, forced RLS, trigger guards and narrowly granted functions/tables. Runtime/authentication separation from EM-002 is preserved. The existing migration role remains required; no runtime automatic migration. No real database was changed. Destructive policy/audit downgrade is unsupported; reviewed forward repair/authorized restore is required for real state.

EM-004 protected fetch gateway is next after review/CI acceptance. Live network remains disabled until its technical boundary and explicit source authorization exist. Later jobs/extraction/export tasks must consult current policy version/expiry/revocation/platform enable state at actual execution time rather than trust a stale successful evaluation or job snapshot.

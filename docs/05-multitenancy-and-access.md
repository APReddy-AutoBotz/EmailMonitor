# 05 — Multi-tenancy, authorization and customer isolation

**Baseline:** 2026-10-08. **Invariant:** no customer data, credentials, workflow state or support access is implicitly shared between organizations.

## Tenant boundary

`organization_id` is the tenant key. Every business row, job item, evidence reference, contact association, review, export, usage entry, policy snapshot, secret reference, deletion request and audit record carries it. Composite foreign keys `(organization_id, resource_id)` prevent cross-organization relationships even when an ID is guessed.

A user may belong to multiple organizations. The active organization is a selected context, not an authorization grant. Backend checks authenticated membership, role, tenant status and operation on every API request and event subscription. Changing an HTTP header or body field never grants access. IDs are unguessable but are not security controls.

## Database enforcement

Use PostgreSQL RLS on tenant business tables with both USING and WITH CHECK predicates. Runtime roles must be non-owner and lack BYPASSRLS; migrations use a separate controlled role. Enable and FORCE row security where appropriate; never test only as the owner/superuser. PostgreSQL documents the owner/BYPASSRLS exceptions [S01].

Set tenant context with transaction-local settings only after server authorization. Missing context fails closed. Do not leave session-level tenant variables in a pooled connection. Integration tests must reuse pooled connections across organizations and exercise joins, writes, deletion, export and background jobs. Constraint errors are sanitized to avoid revealing existence of other tenants' rows.

Authentication/membership bootstrap needs a tightly bounded identity lookup before a tenant context exists. Design separate queries/roles for it; do not expose an unrestricted all-tenant repository helper to regular application code.

## Roles and capabilities

| Capability | Owner | Admin | Data steward | Operator | Reviewer | Viewer |
|---|---|---|---|---|---|---|
| Read permitted tenant results/jobs | Yes | Yes | Yes | Yes | Yes | Yes |
| Create/start/pause/cancel own or assigned jobs | Yes | Yes | Yes | Yes | No | No |
| Manage all tenant jobs | Yes | Yes | Yes | No | No | No |
| Review/correct associations | Yes | Yes | Yes | No | Yes | No |
| Approve source collection/export policies | Yes* | No | Yes* | No | No | No |
| Request contact export | Yes | Yes | Yes | Granted separately | Granted separately | No |
| Manage membership and non-owner roles | Yes | Yes | No | No | No | No |
| Assign/transfer owner | Yes | No | No | No | No | No |
| Configure secret references | Yes | Yes | No | No | No | No |
| Read secret plaintext after saving | No | No | No | No | No | No |
| Manage retention/deletion | Yes | No | Yes | No | No | No |
| See audit | Yes | Yes | Yes | Own job events | Own review events | No |
| Approve support access | Yes | No | No | No | No | No |

`*` Source approval also requires a valid platform-supported route and documentary permission/purpose; no role can override hard security restrictions or fabricate a license. Separate capability grants handle export instead of creating many bespoke roles. A user's organization role is never accepted from a browser token without trusted server-side validation.

## Other boundaries

**Workers:** queue payload contains job/item identifiers and expected generation. Resolve organization from authoritative job ownership; compare supplied context; re-check tenant status, permission revision, source state and lease. Long-running jobs stop when tenant or source is suspended.

**Storage:** tenant-prefixed object keys plus metadata and storage-policy checks. Downloads go through an authenticated handler. For the core release do not expose bearer presigned object URLs that bypass current suppression/deletion policy. A streaming handler may use internal scoped URLs but must reauthorize the current artifact. No cross-tenant deduplication of contact-bearing documents.

**Caches and events:** cache keys include tenant, permission revision and data revision. Cursor tokens bind tenant, filter snapshot and resource. SSE reconnect IDs are tenant-bound and replayed only after reauthorization. Metrics can share aggregate infrastructure but do not expose another tenant's identifiers or activity.

**Credentials:** one tenant cannot reuse another tenant's publisher token. Store references to a secret manager, not plaintext in application tables or task payloads. Grant a worker only the exact source token for its task.

**Search and export:** every query and artifact is tenant-filtered. Export generation and download both re-evaluate policy. No global autocomplete or contact lookup leaks matches between organizations.

## Platform operator versus customer admin

The platform operator can view service health, tenant identifiers, plan usage and failures without contact content. Human support data access is off by default. Exceptional access requires customer-owner approval, specific scope, reason, expiry, audit and immediate revocation. It never silently changes customer roles. Hosted infrastructure administrators technically control infrastructure; contracts and operational controls must acknowledge this rather than claiming impossible cryptographic isolation.

## Organization lifecycle

`provisioning → active → suspended → offboarding → deleted`. Activation requires an owner, deployment region, policy defaults and entitlements. Suspension disables new jobs and pauses executing work; configured read/export access may remain solely for authorized recovery/offboarding. Offboarding revokes tokens, cancels queued work, freezes new data, permits an approved final export, then runs deletion and certificate/report generation. Tombstone/generation checks prevent in-flight tasks from resurrecting deleted data.

## Multi-customer configuration

Per organization: legal/display name, branding, timezone, source policies and credentials, allowed regions, roles/capabilities, retention, privacy purpose, source/domain limits, job budgets, export permissions, quotas and optional AI settings. Plan entitlements cannot relax security/source rules. Shared deployments enforce provider-global rate limits across all tenants; separate private installations still must respect each customer's source limits.

## Mandatory tests

Tenant A cannot list/read/update/delete B's jobs, contacts, authors, evidence, reviews, exports, source secrets, usage or audit. Include guessed UUIDs, altered cursors, stale sessions, changed memberships, broker messages, pooled connections and object paths. Run the same suite on a two-tenant dedicated installation; single-customer deployments are not an excuse to remove isolation.

# 09 — API, contracts and event specification

**Baseline:** 2026-10-08. Proposed API, not deployed endpoints. JSON Schemas in `contracts/` define initial request/record shapes; EM-001 validates examples and later tasks generate/test OpenAPI against actual handlers.

## Transport and authorization

Same-origin HTTPS API under `/api/v1`. Browser uses backend-managed secure HttpOnly session with CSRF protection on mutating actions. Machine access uses revocable, scoped credentials stored hashed, tied to one organization and explicit capabilities. OIDC issuer/audience/state/nonce/redirect validation is required. No tokens in localStorage or query strings.

Organization path parameters select a resource scope, not authorization. Every request checks membership, organization state and capability. Use generic 404/403 behavior that does not reveal another tenant's resource existence. Cursor tokens bind organization, actor permissions, resource/filter snapshot and expiry.

## Endpoint inventory

| Method/path | Behavior |
|---|---|
| GET /me | Identity and authorized organization memberships only |
| GET/PATCH /organizations/{org} | Tenant profile and allowed settings |
| GET/POST/PATCH /organizations/{org}/members[/{member}] | Membership lifecycle with owner safeguards |
| GET /organizations/{org}/sources | Source support/approval/health matrix |
| POST /organizations/{org}/source-policies | Create a pending reviewable policy version |
| POST /organizations/{org}/source-policies/{id}/approve | Steward approval with permission evidence and expiry |
| POST /organizations/{org}/source-policies/{id}/revoke | Immediate revocation and affected-work invalidation |
| POST /organizations/{org}/jobs | Validate input, create draft/preflight; no unrestricted fetch |
| GET /organizations/{org}/jobs[/{job}] | Lists/detail with lifecycle, counters and truthful stop reasons |
| POST /organizations/{org}/jobs/{job}/plan | Bounded preflight under approved source policy |
| POST /organizations/{org}/jobs/{job}/start | Reserve quota, commit queued state and outbox |
| POST /organizations/{org}/jobs/{job}/pause | Stop new work and drain bounded in-flight work |
| POST /organizations/{org}/jobs/{job}/resume | Recheck policy/quotas and continue checkpoint |
| POST /organizations/{org}/jobs/{job}/cancel | Fence future commits and preserve permitted partial results |
| POST /organizations/{org}/jobs/{job}/retry | Select eligible failed items; do not repeat policy-denied requests |
| GET /organizations/{org}/jobs/{job}/items | Article-level outcomes including no-contact/blocked |
| GET /organizations/{org}/jobs/{job}/events | Authenticated SSE with tenant-bound replay IDs |
| GET /organizations/{org}/contacts[/{id}] | Filtered accepted/review records as authorized |
| GET /organizations/{org}/evidence/{id} | Safe excerpt/locator; never uncontrolled raw HTML rendering |
| POST /organizations/{org}/reviews | Evidence-backed accept/reject/correct with expected revision |
| POST /organizations/{org}/exports | Async export from approved snapshot and purpose |
| GET /organizations/{org}/exports[/{id}] | Export state, allowed counts and expiry |
| GET /organizations/{org}/exports/{id}/download | Reauthorize current data/policy; regenerate or deny stale artifact |
| POST /organizations/{org}/exports/{id}/revoke | Revoke access and enqueue deletion |
| POST /organizations/{org}/suppressions | Create approved tenant suppression and invalidate artifacts |
| POST /organizations/{org}/deletion-requests | Audited lifecycle request, not an immediate broad SQL delete |
| GET /organizations/{org}/usage | Unit ledger and remaining budgets |
| GET /organizations/{org}/audit | Authorized filtered audit |
| GET /health/live and /health/ready | Minimal service health without tenant/config secrets |

Bracketed paths above are shorthand for distinct list/detail routes, not literal routing syntax. Generate an explicit OpenAPI inventory when implemented. Future mailbox/send endpoints are deliberately absent.

## Idempotency and concurrency

Require `Idempotency-Key` for job creation, start, retry and export. Store tenant + actor + route + key + canonical payload digest + resulting response for a configurable window (default 24 hours). Same key/same payload returns the original result; changed payload returns 409. Idempotency does not bypass current authorization. Business uniqueness and worker effect keys outlive the request window.

Use ETag/If-Match or explicit `expected_revision` on review and policy/settings changes. Return 409 for stale versions. List pagination defaults to 50/max 200; use opaque cursors, not client-supplied SQL offsets on huge tables.

## Responses and errors

202 for queued asynchronous operations; 201 for created resources; 200 for completed reads; 400 malformed input; 401 unauthenticated; 403 unauthorized/policy refusal; 404 unavailable resource; 409 state/idempotency/revision conflict; 413 oversized input; 422 semantic validation; 429 API quota/rate limit; 503 unavailable dependency.

Standard error body: `code`, safe `message`, `request_id`, `retryable`, optional safe field errors and `retry_after_seconds`. Codes include INPUT_NEEDS_REFINEMENT, UNSUPPORTED_SOURCE, SOURCE_APPROVAL_REQUIRED, SOURCE_PERMISSION_EXPIRED, URL_NOT_ALLOWED, QUOTA_EXCEEDED, INVALID_STATE, REVISION_CONFLICT, EXPORT_INVALIDATED and DEPENDENCY_UNAVAILABLE. Never return raw upstream bodies, credentials, database constraints or internal network addresses.

## Event envelope

Fields: schema_version, event_id, event_type, occurred_at, organization_id, aggregate_type, aggregate_id, aggregate_version, correlation_id, causation_id nullable, payload of IDs/counts/reason codes. No email addresses, raw URLs containing secrets, full HTML/PDF, API tokens or manuscript bytes in messages.

Initial event types: job.created, job.queued, job.discovery_progress, job.item_terminal, job.paused, job.cancelled, job.finished, association.reviewed, export.ready, export.revoked, source.policy_changed, organization.suspended, data.deletion_requested, data.deletion_completed. Delivery is at least once; consumers deduplicate event_id and guard aggregate_version. UI can always reconcile from GET job state.

## SSE and storage

SSE revalidates access at connection and periodically/at permission changes; reconnection uses an authorized cursor. No process-local memory as the only event source. An event stream is progress delivery, not durable job authority. Do not attach raw contact payloads to telemetry.

Download URLs are authenticated API routes, not public object storage links. Validate policy/data revision and suppression before serving bytes. For large streaming downloads, recheck at bounded chunk/time intervals when revocation requirements demand it; cancel revoked streams. Data already downloaded to a customer's device cannot be remotely erased—document this limitation.

## Contract evolution

Schema `1.0` uses explicit nulls and enums. Additive optional fields require tests for older clients; incompatible semantics require a versioned contract/migration. Backend validation models and generated frontend clients must match committed contracts. Do not maintain a disconnected fictional OpenAPI file that passes no integration tests.

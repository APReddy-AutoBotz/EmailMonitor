# ADR 0006 — Bounded service authority for durable application work

Status: Implementation decision, validation pending, 2026-10-20.

Scope: partial EM-017 runnable application/runtime candidate. This decision
supersedes only ADR 0005 offline worker authority's use of a synthetic human
session for the new runtime. Existing fixture helpers and their refusal tests
remain supported. This is not production activation or full EM-017 acceptance.

## Requirements and decision

Documents 04 and 05 require authoritative PostgreSQL job ownership, current
permission checks, minimal queue references and non-owner, non-BYPASSRLS runtime
roles. Documents 10, 11 and ADR 0004 require durable recovery, finite work units,
revocation, lease fencing and idempotent effects. Document 13 requires independently
runnable processes, explicit migrations and refusal of unsafe production settings.
Document 21 proposes a 21,600-second job wall bound. It labels this a conservative
starting value, not an agreed SLA, provider limit or measured capacity.

The new worker and publisher use an independently authenticated database service
principal and explicit bounded delegations. They do not receive a human browser
token, CSRF token, authenticator connection or session-minting capability.
Queue messages remain identifiers, never authority or credentials. A known grant
ID, forged tenant ID or transaction setting is not authentication.

An authorized human start or explicit continuation creates its delegation in the
same transaction as the accepted run and outbox changes. The delegation binds:

- Organization, exact job/run, generation and deletion generation
- Delegating identity, current permission and membership revision, original
  session revocation anchor, service principal and purpose
- Exact source/policy revision and an explicit allowed stage/operation set
- Issue time, immutable absolute deadline and explicit revocation state

The initial implementation permits a lower configured duration, with a ceiling of
21,600 seconds and any earlier applicable source, run or grant deadline. It never
uses contact retention or `execution_runs.expires_at` as machine-authority lifetime.
Heartbeats, redelivery, worker restart, idempotent start retries and pause do not
extend the wall deadline. Continuation requires current human authorization.

Natural expiry of the originating browser session ends human API/stream access.
It does not itself invalidate an unexpired delegation. Explicit logout or session
revocation **does** invalidate outstanding delegations, including active work
before protected release or commit. The server retains the revocation anchor
through the delegation's lifetime; missing anchors fail closed. Human
`resolve_session`, CSRF and session expiry semantics remain unchanged.

Identity disablement or permission revision change, membership removal or revision
change, tenant suspension/offboarding, service-principal or delegation revocation,
source/policy expiry or replacement, entitlement reduction, purpose mismatch,
generation changes, suppression and deletion all remain effective. Rechecks occur
at publication, claim, resource admission, protected-byte release, persistence,
successor publication and final commit. Locks/revalidation serialize consequential
commits against revocation. Slow acquisition does not hold a database transaction;
physical cancellation remains bounded by the work-unit deadline.

## Least privilege

Service SQL authority is separate from the human runtime and authenticator roles.
It cannot assume owner, authenticator or human runtime authority. It receives only
the exact execution surface needed by its bound purpose and resource, with forced
RLS on tenant tables. It cannot administer membership, approve source policy,
review associations, create arbitrary exports, grant support access or initiate
deletion on behalf of an owner delegator.

Export execution requires a separately authorized exact export request and its
current policy/requester checks. Retention execution similarly requires its own
bounded purpose. Extraction authority never implicitly permits either. Human
read/review/download operations retain their existing session authorization.
Services do not obtain tenant-wide powers by returning an owner's human role.
SQL NULL-valued role comparisons must not become an authorization fall-through.

## Migration and restore

Use additive forward-only migration after 0013. Do not rewrite applied migrations,
modify serialized association bundles, change parser attribution or backfill
authority onto historical jobs, outbox rows, exports or lifecycle work.
Migration defines empty authority structures and NOLOGIN role definitions only;
it creates no actual service login, credentials, source entitlement or live grant.
Legacy work remains on its existing path or fails closed until explicit supported
reauthorization; installing an upgrade does not silently authorize work.

Fresh install and populated upgrade must converge on schema, ACL and forced-RLS
state. New authority and revocation state belongs in the protected restore seal;
until covered, restore must refuse it. An older backup cannot revive a revoked
delegation or principal. Downgrade is not destructive rollback: stop new runtime
admission and use compatible forward repair, preserving audit and revocation data.

## Installation boundary

Deliver separate API/web, finite publisher and worker entrypoints and a reference
installation that uses them. Explicit migration execution uses a separate identity;
API startup never migrates or provisions credentials. Readiness reports dependency
and schema readiness honestly. Shutdown stops admission and closes owned resources.
An authored synthetic acceptance profile packages its fixtures explicitly, without
repository-relative test imports or a production fixture escape hatch.

Actual IdP registration, database/service logins, secret installation, region/storage
selection, source grants, deployment and customer access are external activation
steps. Code and disposable synthetic test identities do not perform those actions.
Real sources remain unavailable unless their independent certification and access
requirements are satisfied.

## Required acceptance

1. Fresh install and populated 0013 upgrade; zero automatic historical grants;
   identical schema/ACL/forced-RLS outcomes and restore refusal/seal coverage.
2. Two-tenant API, direct SQL, publisher and worker tests using actual non-owner
   roles; forged identifiers/purposes, contextless access, pool reuse, role
   escalation and unrelated owner-capability attempts fail.
3. Natural human expiry permits only still-valid bounded work; explicit logout,
   grant/principal expiry/revocation, changed membership/identity/source,
   entitlement reduction and deletion deny new work and stale commits.
4. Actual broker/worker crashes before commit and after commit before ACK,
   redelivery and reconstruction preserve one committed effect/usage identity;
   stale leases and revoked authority cannot execute or reconstruct work.
5. The packaged installation supports the normal keyboard operator flow:
   synthetic sign-in, source policy, keyword/direct URL, partial/no-contact
   outcomes, evidence/review, scoped export and restart/recovery. It must use
   application entrypoints rather than an acceptance-only Scenario service.
6. All inherited normal/fresh checks, security/parser/browser/operator gates and
   exact-head CI. Missing service/container evidence remains explicitly pending.

Full EM-017 remains incomplete without actual staging, deployment-specific
identity/storage/egress validation and measured restore RPO/RTO. No merge, deploy,
release, real source acquisition or live access creation follows from this ADR.

## Implemented reference profile clarification

The initial installed service dispatcher is explicitly authored HTML-only. Starts
requiring XML, PDF or dynamic-browser executors are refused transactionally before
a service grant is committed. Existing isolated executors and their one-shot
controls remain separate and unchanged. The reference API uses fixed loopback TLS
PKCE endpoints and pinned public verification keys; this is not real IdP activation.
The runnable process contract and migration/restore restrictions are documented in
[document 66](../66-durable-service-reference-runtime.md).

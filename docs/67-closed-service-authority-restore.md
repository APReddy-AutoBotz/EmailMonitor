# 67 — Closed synthetic service-authority restore seal

## Scope and prerequisites

This is a bounded code/test EM-017 candidate after the accepted installed reference
runtime. [ADR 0006](adr/0006-durable-service-authority.md) requires restored service
principals, delegations and audit to preserve revocation. Documents 05/11/13/16 and
[the legacy exercise](44-synthetic-restore-exercise.md) require current tenant,
privacy, source, lease and accounting controls before recovery can serve data.

The new `tests/service_restore_exercise.py` profile is trusted test support, not an
application endpoint, deployment command, customer upload or production restore
facility. It reuses the exact disposable PostgreSQL 17.11 image/tools, same-cluster
roles, private bounded custom archive, ownership marker and cleanup discipline.
It accepts exactly two authored tenants. All service state in the archive must
belong to them; unrelated service authority refuses rather than being ignored.
The legacy `capture` and `RestoreExercise` still refuse every populated service
principal, delegation or service audit table.

No application, migration, credential, persistent role, source grant, deployment,
real acquisition or live access is activated. This profile never grants CONNECT,
opens the target, or returns a runtime URL. Its database remains connection-limited
to zero and closed to ordinary fixture logins for its entire lifetime. It is not a
service recovery/resumption procedure or production readiness claim.

## Supported authority window

The fixture creates its exact synthetic resources and existing disposable roles
before capture. It owns and quiesces all relevant processes and closes their pools.
No workers, publishers or source consumers run during the window. A repeatable-read
snapshot and absence of active leases alone do not establish this quiescence.
The baseline capture must equal the actual restored archive before any replay.

Only these service changes are supported after the backup:

- A principal is unchanged, or changes from active to disabled with exactly one
  revision increment. Its ID, organization, login OID/name and kind are immutable.
  Reactivation, revision jumps, no-op revision increments and new/missing principals
  refuse. The existing revision trigger performs replay; triggers are not bypassed.
- A delegation is unchanged, or changes once from no revocation timestamp to its
  captured revocation timestamp. Every other field is immutable, including issue
  time, absolute deadline, original principal revision, purpose, resource,
  generation, deletion generation and human/session/source anchors. Already
  revoked rows are never updated. No new grant or automatic reauthorization occurs.
- All baseline audit rows remain identical. Each grant has its coherent delegated
  event and, when revoked, one matching revoked event. Exactly one new revoked
  audit row must match each newly revoked grant's tenant and principal. New
  transaction/delegated events, missing/extra revocations or edited history refuse.
  Existing revoke_service_work cannot reproduce captured UUIDs/timestamps; replay
  uses guarded updates and exact captured audit insertion in one transaction.

All legacy refusals remain: unsupported identities/sessions/membership, source
versions, tenant controls, accounting and business-frontier changes cannot be
silently rolled back. Existing same-version source restriction and job privacy
replay remain supported. Absolute service deadlines are never renewed or converted
into browser-session expiry. Current service SQL continues to evaluate its original
session-revocation anchor, current membership, source, privacy and work predicates.

## Protected seal and ordering

The private seal covers bounded global service rows; their tenant/resource/identity/
session/policy anchors; the exact schema head; portable schema/function/table/column
ACLs, owners, triggers and forced RLS; cluster role OIDs, attributes, expiry,
configuration and membership edges; and all seven export-owned child tables.
Role credential verifiers are neither queried nor recorded. Catalog capture has a
separate finite row bound; service and export data retain the 500-row bound.

The export frontier includes members, outcomes, artifacts, requests, outbox,
effects and events. For a tenant with a current job tombstone, the existing lifecycle
replay can invalidate/purge its exports. The resulting complete export seal must
still equal the current source exactly. This does not permit arbitrary new export
work or omitted post-backup effects.

Replay checks the ownership marker and closed database state, validates the exact
source seal, then checks baseline versus restored state. It applies permitted
service revocations/audit and current privacy replay while closed, reconciles
service/export/job/accounting state, and rechecks source and target. Repeated replay
accepts only the identical validated inputs and unchanged source/target. Every
failure leaves the target closed. Later writes require a fresh reviewed exercise,
not treating an old validation result as continuing authority.

The seal is an in-memory private integrity comparison inside an owned disposable
exercise. It is not a signed backup manifest, external revocation service, malicious
administrator defense, or general point-in-time business-history merge.

## Required evidence and limits

Pure contract tests cover monotonic transitions, malformed/coherence/anchor errors,
audit history, immutable fields, deadlines, role/catalog/export drift and permanent
open/URL refusal. They do not prove SQL or dump/restore behavior.

Actual hosted tests must run the pinned dump/restore with populated authority,
verify closed CONNECT and ownership, replay exact revocation/privacy state, reject
source/target drift, prove no revived work under current SQL predicates and clean
up only the owned target/archive. Trusted fresh connections use SET SESSION
AUTHORIZATION to the existing exact synthetic role and assert both session_user and
current_user. Positive probes roll back, including service_begin's audit insert,
so the target seal remains unchanged. These are actual SQL role-behavior proofs,
not login authentication proofs; the original superuser connection can reset its
session authorization. Existing actual-login, service broker and installed operator
checks remain mandatory for their separate claims.

Local Docker/PostgreSQL absence produces explicit infrastructure skips. Full normal
and fresh serial local gates, exact-head hosted SQL/legacy restore/service/packaging/
parser/browser/operator gates, and independent source/evidence review remain
required. [Candidate evidence](../reports/em017-service-restore-validation.md)
records outcomes without treating skips as passes. Production RPO/RTO, staging,
real credentials, storage and serving a restored deployment remain unproved and
outside this milestone.

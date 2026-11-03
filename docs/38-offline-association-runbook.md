# 38 — Offline association and review foundation

## Boundary

EM-009 maps actual bounded HTML/browser and PDF observations into separate ordered author instances, candidates, affiliations, evidence and identity associations. It is synthetic/test-only. The persistence API consumes identifiers for retained authorized HTML/browser observations; pure PDF mapping does not introduce PDF acquisition or persistence permissions. The UI remains unavailable. No DNS/MX/SMTP, delivery check, outreach, sending, export or live/production activation occurs.

First author and explicit corresponding roles remain distinct. Multiple correspondents remain separate associations. Same-name instances are never automatically merged. Automatic acceptance requires completed source observations, valid syntax, explicit source-backed correspondence and nonempty candidate/author evidence. Ambiguous or missing evidence stays unresolved; no heuristic probability is emitted. Human correction selects an observed author and evidence, never supplies a new address or role fact.

## Normalization and tenant deduplication

Original Unicode strings are retained. Explicit locked idna 3.20 implements conservative UTS46/nontransitional IDNA domain conversion; the existing dependency/license inventory already contains this exact BSD dependency. See the [official IDNA implementation](https://github.com/kjd/idna). Local-part case, plus tags and dots are preserved. Unicode local parts, quoted local parts and literal domains are explicitly unsupported; malformed input is invalid. Domain status stays not_checked, delivery unverified and outreach not_assessed.

Candidate identifiers and comparison keys are tenant-scoped. Within a retained article observation batch, repeated addresses share a candidate and preserve raw variants; normalization collisions block automatic acceptance. Replaying the identical source revision returns the same sealed batch and preserves reviews. Relational rows retain per-batch provenance; a tenant comparison-key index supports lookup across batches. This is not a global person registry or cross-job identity consolidation. Different people can retain the same mailbox without merging author instances.

## Transactions, authorization and retention

Migration 0006 adds forced-RLS batches, authors, candidates, evidence, associations, affiliation/variant/citation relations, immutable reviews and an identifier-only transactional outbox. Composite tenant/batch foreign keys preserve relationships. Bounded JSON records are canonical receipts alongside actual relational columns/links. Sealing verifies complete record/link counts atomically; incomplete batches remain unreadable. The migration is forward-only; destructive rollback is intentionally unavailable.

Current server session, identity/membership revision, catalog ceilings, approved source policy/version/purpose/expiry, retention, source revision and organization deletion epoch are checked in narrowly scoped owner functions with fixed search paths. Runtime receives no catalog UPDATE, association UPDATE/DELETE, table ownership or bypass privilege. Owner/admin/data-steward/reviewer can review; operator/viewer cannot. Existing permitted observations remain readable/reviewable after cancellation, but cancellation prevents new derivation. Source revocation, policy replacement/expiry, session expiry and deletion/offboarding refuse access.

Review uses expected_revision and one transaction for association/citation update, immutable history, minimal audit and association.reviewed outbox. Duplicate source replay cannot erase a correction. The outbox contains IDs/counts only and remains pending for later event integration; no broker-delivered review event is claimed. Stored evidence/reason follows source retention and deletion controls.

## Test-only API and validation

Under /api/v1: POST organizations/{organization}/jobs/{job}/associations derives from one registered article URL and expected observation revision; GET lists current batches. GET organizations/{organization}/association-batches/{batch} returns actual retained facts. POST organizations/{organization}/reviews accepts association ID, expected revision, accept/reject/correct, optional observed author ID, citation IDs and bounded reason. GET association-batches/{batch}/reviews returns immutable review metadata. Mutations require existing CSRF and server tenant context; production refuses before database access.

JSON Schemas enforce structural shape and prohibited probability/mailbox claims. Runtime additionally validates normalization, source/evidence relationships, accepted citation completeness, geometry and review semantics, which JSON Schema cannot fully express. Validate trusted-worker results with Bundle.model_validate_json, not schema alone.

Run scripts/check.sh and the four test_association* modules. Required published-head CI must execute all real PostgreSQL cases without skips, including role matrix, RLS, current permission/deletion, replay, concurrent review and transactional rollback, alongside existing broker/transport/browser/parser/docs gates. Local skipped service tests are not acceptance. [Validation](../reports/em009-validation.md). EM-010 depends on independent review and actual scoped EM-009 acceptance.

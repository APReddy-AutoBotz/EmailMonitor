# EM-002 local validation evidence

Date: 2026-10-10. Stacked implementation baseline: reviewed/published EM-001 head `88e34a790c732507afbf362d8f9cb481ea242f3a`, tree `09fdfab0ce3bbd9953726e433a1c680425e4651c`. PR #1 remains Draft and unchanged; this is a distinct task/branch.

Environment: Linux x86_64, Python 3.12.14, Node 24.19.0, uv 0.12.23, pnpm 11.25.0, PostgreSQL 17.11 built from verified official source. All identities, organization data, keys and sessions are synthetic. No real IdP, credentials, source data, email, external AI or deployment.

## Actual checks

- `scripts/check_tenant_foundation.sh` with separate disposable PostgreSQL admin/authentication/runtime URLs: migrations upgrade from empty and repeated upgrade succeeded; complete aggregate checks passed
- PostgreSQL tests use a direct non-owner/no-BYPASSRLS login. Two-tenant API/SQL reads and writes, missing/forged context, pooled connection reuse, six-role permissions, CSRF, revisions, stale/revoked/expired sessions, last-owner rejection, owner transfer, concurrent last-owner removals using separate pools, lifecycle and provider-stub production refusal are exercised
- OIDC adversarial tests cover issuer/audience/nonce/time/authorized-party/required-claim/algorithm/key rejection and ignore forged role/organization claims; browser-flow tests cover cookie binding, PKCE and callback replay
- Final local aggregate: 64 Python tests passed without warnings/skips; Ruff lint/format and strict mypy passed; docs/contracts/fixture consistency and 48 Python/159 JavaScript inventory parity passed; frontend peers/type/lint/1 component test/build passed
- Clean copy with no virtualenv/node_modules/build output, migration from empty and repeated upgrade: same complete aggregate passed with 64 Python tests, no warnings/skips, 1 frontend test and all checks/build

Trials are not conflated with final evidence: initial Unix-socket startup was unavailable; Psycopg integration tests passed but the driver was replaced with pg8000; pg8000 exposed a test's caught-error/failed-transaction issue, repaired with an explicit savepoint; deprecated TestClient was replaced with ASGITransport. The final driver/migration/check combination must pass independently.

## Privilege correction

Initial independent review identified an overbroad session-bootstrap grant to tenant runtime. The candidate was held and never published. Static privilege inspection drove a scoped correction: bootstrap functions belong only to a separate trusted authentication role/connection; tenant runtime cannot inherit/SET ROLE to it or the owner. Defensive catalog assertions verify function/table permissions and role isolation; normal signed synthetic login still succeeds. No denied exploit validation was reproduced or rerouted. This protects the tenant SQL principal, not a fully compromised trusted verifier process. Production credential/process isolation remains a separate security gate.

## Pending / limits

Final aggregate and clean-install/from-empty migration evidence passed. Fresh independent review and exact published-head CI remain pending. Production IdP/database assembly is intentionally unavailable; migration/provisioning, real-provider network/key refresh and customer security decisions are not performed. No jobs, extraction, source registry/fetch gateway, queues, exports, live data or customer deployment are claimed. The unchanged UI still says extraction is unavailable.

Migration impact: first tenant foundation migration on disposable synthetic state only. Destructive downgrade is explicitly unsupported; reviewed forward repair is required for a real migrated database. Next task after acceptance: EM-003.

# 26 — EM-002 offline identity and tenant foundation

Verified locally 2026-10-10. This is the next dependency slice after the reviewed EM-001 scaffold. It implements and tests the identity/session, membership, lifecycle and PostgreSQL tenant boundaries with synthetic identities. It does not enable a customer identity provider or production database, create live accounts/grants, fetch publishers, extract contacts or deploy anything.

## Implemented boundary

- OIDC authorization-code interface with S256 PKCE, browser-bound one-use state, nonce, pinned RSA verification keys and exact issuer/audience/redirect checks. PyJWT enforces signature, fixed RS256 algorithm, expiry/issued-at and required claims; untrusted token roles/organization fields are not authorization
- PostgreSQL-backed pending flows and one-hour hashed opaque sessions, five-minute flow expiry, Secure/HttpOnly/SameSite cookies, same-origin plus per-session CSRF tokens for mutations, logout, identity/membership revision revocation and no-store responses
- `/me`, server-authorized organization profile, membership list/create/update, owner transfer and lifecycle endpoints in the explicitly test-only API assembly
- Six roles, implemented organization/membership/owner/lifecycle capabilities, last-active-owner guard, optimistic revisions, atomic owner transfer and organization transitions
- First Alembic migration, separate non-login owner/authentication/runtime roles, forced tenant RLS, composite membership/audit keys, bounded SECURITY DEFINER identity bootstrap functions, parameterized queries and transaction-local session/organization context
- Runtime starts only under a non-owner, non-superuser, no-BYPASSRLS login. Table access without context is denied; a session from A cannot choose B by changing SQL context. Pooled transactions reset; SQL/API role and lifecycle checks preserve the boundary

The tenant runtime has no permission to create sessions or store/consume pending login flows. Only the separate trusted authentication verifier connection can execute those bootstrap functions, after application OIDC verification. It has no tenant-table privileges or runtime-role membership. Connection startup and defensive catalog tests reject role inheritance/SET ROLE paths, owner/superuser/BYPASSRLS and a mismatched bootstrap grant. A compromise of the trusted verifier process is outside this database-role boundary; real deployment must separately isolate its credentials and execution, and receive security review. The offline test assembly uses separate pools in one process and is not that deployment certification.

## Test-only activation and production gate

`create_app(Settings(environment="test", identity_stub=True), Foundation(database, provider, authentication))` is the integration assembly. Its provider uses an in-memory synthetic code exchange and ephemeral RSA test keys. The normal CLI entry point remains the metadata-only scaffold. It does not silently construct a provider/database from environment values. Production rejects the test provider/stub; no production-enablement switch is added.

A real provider/issuer, customer domain, key refresh strategy, HTTPS database transport, deployment secrets, login rate/flow retention controls and staging authorization remain operator/security decisions before staging. The OIDC interface has no default outbound network client. No credentials are retrieved/generated for an external account, and no authentication grant is created. Disable/redact query-string access logs before enabling a real callback; authorization codes must not enter logs. The synthetic API proof is not a real IdP certification, customer onboarding or production security certification.

User provisioning is deliberately not self-service: only identities already registered by the migration/provisioning operator can establish a session. A member manager may add an existing identity within the configured provider realm to their authorized tenant. No directory/profile lookup across tenants is exposed, and no invite email is sent. Membership changes invalidate the target identity's sessions across organizations, a conservative documented behavior. Deleted tenants are terminal. Lifecycle deletion here changes state only; contact/artifact erasure is EM-014.

## Reproduce the real SQL gate

Use a dedicated disposable PostgreSQL 17.11 database with synthetic state. Never point these test URLs at customer data. Migration/admin, trusted authentication verifier and tenant runtime connections are distinct. From the repository root:

```sh
uv sync --project services/backend --locked
EM_MIGRATION_DATABASE_URL="$DISPOSABLE_ADMIN_URL" uv run --project services/backend alembic -c services/backend/alembic.ini upgrade head
# Create a disposable LOGIN role that inherits emailmonitor_runtime,
# is NOSUPERUSER NOBYPASSRLS and owns no tenant tables; use a test-only credential.
# Create a different LOGIN role in emailmonitor_authenticator for the trusted verifier.
# Neither login may inherit or SET ROLE to the other principal or owner.
EM_TEST_AUTH_DATABASE_URL="$DISPOSABLE_AUTH_URL" EM_TEST_ADMIN_DATABASE_URL="$DISPOSABLE_ADMIN_URL" EM_TEST_DATABASE_URL="$DISPOSABLE_RUNTIME_URL" scripts/check_tenant_foundation.sh
```

The script requires all three explicit test URLs, runs migration upgrade twice (fresh/current revision behavior) and executes the complete scaffold/identity/SQL/frontend checks. Without DB URLs, ordinary `scripts/check.sh` explicitly skips real SQL/API acceptance tests; that is not an EM-002 pass. The EM-002 CI job provides a fresh official PostgreSQL image pinned by digest, migrates it, creates separate synthetic non-owner runtime and authentication logins and runs the required script. It does not receive production secrets. The CI-login helper refuses any target except the exact documented disposable CI service.

Local verification built PostgreSQL 17.11 from its official source with published SHA-256 `dd27f2b3c59e73ed14aa3324901242bf69a032a6347805f274e6260322d42979`. Unix sockets were unavailable in the execution environment; tests ran in a disposable loopback-only process, stopped after each run. A direct runtime login was used, not SET ROLE under a superuser. [Runtime inventory](../reports/runtime-inventory.json) records the source and immutable official CI-image reference. PostgreSQL 17.11 is the current supported 17 minor on the checked [version policy](https://www.postgresql.org/support/versioning/) page.

## Dependency and license choices

SQLAlchemy 2.1.4, Alembic 1.20.0, pg8000 1.31.5, sqlparse 0.6.0 and PyJWT 2.15.1 (cryptography 50.0.2 transitively) are locked. The PostgreSQL driver is pure-Python BSD-3-Clause pg8000; the development Psycopg trial was replaced before the final lock so no default LGPL binary bundle is introduced. Actual migration/role/RLS/API tests were rerun with pg8000. New declared licenses include MIT-0 and Apache-2.0 OR BSD-3-Clause; exact/transitive/optional package metadata is in the [inventory](../reports/dependency-inventory.json). PostgreSQL itself uses the PostgreSQL License. No vendor library was modified or bundled into a release. Full container/base-system SBOM, attribution and vulnerability review remain release gates; the inventory does not claim legal clearance.

References: [PostgreSQL RLS](https://www.postgresql.org/docs/17/ddl-rowsecurity.html), [SQLAlchemy pool reset](https://docs.sqlalchemy.org/en/21/core/pooling.html), [PyJWT verification](https://pyjwt.readthedocs.io/en/latest/api.html), [pg8000](https://pypi.org/project/pg8000/1.31.5/), [PostgreSQL license](https://www.postgresql.org/about/licence/).

## Migration / rollback limits

`0001_tenant_foundation` adds organizations, identities, memberships, sessions, pending flows, minimal audit and guarded functions/policies. Existing EM-001 application data does not exist. Application runtime never creates or owns tables/roles. The migration/operator role owns the controlled bootstrap path; it has deliberate owner policies, not runtime BYPASSRLS.

No automatic destructive downgrade is provided: identity/audit deletion cannot be assumed safely reversible. Downgrade raises an explicit error; use a reviewed forward repair or a tested backup restore with separate authorization. Reverting application code does not erase a migrated database. No production migration or deployment was executed. Next task after acceptance is EM-003, source registry and policy configuration; live network remains gated by EM-004 and source permissions.

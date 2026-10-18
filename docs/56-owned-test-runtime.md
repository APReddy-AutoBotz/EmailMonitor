# 56 — EM-017f owned test runtime composition

## Scope

This bounded [runtime assembly prerequisite](13-deployment-and-operations.md) composes the existing authenticated API through trusted Python inputs and explicit test-only configuration. The default metadata application remains unchanged. It introduces no listener, service account, credential registration, migration, deployment or real identity-provider/source activation.

The composition owns three independent SQL pools: API runtime, authentication, and publisher runtime. Existing database constructors still verify non-owner/non-BYPASSRLS privileges and the authentication/runtime separation. The existing registered Celery worker independently constructs its own runtime pool. The controlled operator acceptance consumes the new composition rather than borrowing the Scenario's API pool; the publisher no longer competes with the API for its single pooled connection.

## Authority and secrets

Settings are revalidated, including instances constructed through validation-bypassing helpers. Explicit test environment, fixture mode and identity-stub mode are required, as is an injected test-only OIDC provider. The two configured PostgreSQL URLs must name the same explicit disposable loopback server/port/database and different login names. Existing SQL privilege checks remain authoritative. No deployment hostname, secret-file loader, environment selector, import path or API/queue JSON can choose executable composition.

Database URLs are in-memory trusted inputs excluded from configuration representation. New configuration/startup/cleanup error messages contain fixed categories rather than credentials. The provider remains caller-owned. Production OIDC, credential rotation and worker service identity still require their separate designs and configuration; test user-session authority is not promoted to production worker identity.

Private exports remain existing database-owned artifacts behind current authenticated policy-rechecked download handlers. No filesystem/object-storage adapter, public object URL or storage permission is added. Private regional storage and secret-manager assembly remain future work.

## Lifecycle

The owner registers each acquired pool immediately and disposes acquired pools in reverse order after partial startup, caller failure or normal exit. Cleanup attempts every acquired pool even when one disposal fails. A retained ASGI application's admission gate returns a fixed 503 after context exit, before routes can reconnect disposed pools.

Callers must stop and join publishers and quiesce API requests before leaving the context. Disposal does not cancel admitted/in-flight SQL or create a global shutdown deadline. The existing controlled worker still owns its gateway pipe and retains its unchanged revoke/join lifecycle. Its Celery application remains the broker publisher interface in this slice; ownership of Kombu global producer pools is not claimed, and no global pool shutdown is added.

## Acceptance and limitations

[Validation](../reports/em017f-validation.md) distinguishes pure lifecycle/refusal tests from actual SQL and controlled operator evidence. Required actual SQL checks cover distinct pools, runtime privilege limits, real signed test OIDC login, CSRF, tenant-A/B denial, current-session revocation, privileged-login refusal and caller-resource survival. Existing normal operator acceptance must still traverse durable outbox, RabbitMQ, protected HTTPS, isolated XML parser, review and CSV/XLSX download with current tenant authority; its browser/worker waits and profiles are unchanged.

Normal and genuinely new-empty Python aggregates, independent exact-tree review and all seven actual own-head workflows remain required. This prerequisite does not meet the full EM-017 staging, hosted/dedicated runtime, storage/secrets, operational recovery or real-source acceptance gates. Rollback removes this optional test composition and restores the prior acceptance caller; no deployed state or database migration exists.

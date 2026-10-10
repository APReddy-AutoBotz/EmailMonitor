# Backend scaffold

From the repository root, install the locked environment with `uv sync --project services/backend --locked`.
Run `uv run --project services/backend uvicorn emailmonitor.api:app --app-dir services/backend/src --host 127.0.0.1 --port 8000`.
The API exposes only `/healthz`, `/api/v1/capabilities` and generated `/openapi.json`. No tenant-data endpoint exists. A healthy response means this process responds, not that a database, broker or extraction system is ready.

Configuration is parsed from `EMAILMONITOR_` variables. Unknown keys and ambiguous booleans fail startup. The default environment is production, with all outbound capabilities unavailable. Fixture/identity-stub switches require the explicit test environment; test transport lives outside the runtime package. This is not production authentication or an enforced network sandbox. EM-002–004 establish those boundaries before any contact-processing feature.

No database migration, worker, queue, fetch client, parser or email/AI integration is introduced by EM-001. The lock includes development tools; `uv sync --project services/backend --locked --no-dev` installs only runtime dependencies.

EM-002 adds an explicitly test-only identity/tenant assembly and a real PostgreSQL migration; see [the foundation runbook](../../docs/26-tenant-foundation-runbook.md). The default CLI does not activate that assembly or run migrations.

EM-003 extends only the explicit test foundation assembly with synthetic source policy governance. See [source-policy runbook](../../docs/27-source-policy-runbook.md); evaluation never performs acquisition.

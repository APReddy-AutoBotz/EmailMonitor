# 35 — Synthetic offline planning and discovery

## Scope and prerequisites

EM-006 builds on the reviewed, CI-verified synthetic/offline EM-004/005 foundation. The test assembly preserves original input, offers the explicit `Myocardial Infraction` spelling suggestion, classifies server-known search/article routes, and refines a homepage instead of crawling its domain. Only the authored `Myocardial Infarction` index is supported. Unknown sources, other topics, filters, PDF and DOI inputs return explicit refinement/unsupported reasons. The default demonstration topic is Myocardial Infarction. No silent query substitution, arbitrary URL execution, API fallback, contact extraction or production enablement exists.

The supported fixture source has no search API: `api_fallback=unavailable_not_attempted` is an explicit capability result, not a claim of equivalent API coverage. The fixture selector/version and SHA-256 byte manifest are server-owned. The test API parses only digest-verified authored repository bytes through the existing current-policy fixture gateway. It cannot receive HTML, selectors, a resolver or a fetcher from a caller. Acquired untrusted publisher bytes require the network-none worker boundary; there is no production assembly. The existing restrictive parser CI executes the same two-page parser inside its actual network-none container, with no new security settings.

## Durable API and worker flow

Use the explicit test assembly with `Settings(environment="test", identity_stub=True, fixture_mode=True)` and a synthetic Foundation. Production configuration rejects those modes. The existing development/tenant runbooks cover locked installation and disposable database setup.

1. Create an original-input draft using POST `/api/v1/organizations/{organization_id}/jobs` and a bounded Idempotency-Key
2. POST `{job_id}/plan` with `expected_revision` equal to the job revision. Supported plans persist immutable tenant/job/generation/deletion/policy/cap context. Refinement/unsupported preflight responses are recomputed from the durable original draft and do not schedule work
3. GET `{job_id}/discovery` reads the durable plan/checkpoint/frontier
4. The synthetic demonstration may POST `{job_id}/discover-fixture-page` with the discovery revision, one bounded page per call. Stopping between calls and constructing a new service preserves the cursor. The API never exposes an arbitrary parsed-page commit
5. The existing test-only Celery application also registers `emailmonitor.fixture.discover`. `publish_discovery` publishes identifier-only durable outbox events with broker confirmation. A periodic test dispatcher selects the current pending revision until its checkpoint advances; confirmation alone never prevents crash recovery. Restarted workers resolve current PostgreSQL authority. Duplicate or uncertain delivery cannot duplicate a page/frontier unit

Page commit, next cursor, fingerprints, article dedup and successor outbox are atomic. Network/fixture byte acquisition and parsing occur outside the database transaction; commit rechecks current authorization, policy version/expiry, generation and deletion fences. A fixed-source tenant/job/current-version-authorized SECURITY DEFINER fence acquires policy/head/catalog share locks during commit. Runtime catalog write grants remain absent; ordinary operator and source-less URL cases are required tests. [PostgreSQL row-lock privileges](https://www.postgresql.org/docs/17/sql-select.html) require this privilege separation. Schema-trigger fences reject writes outside draft extraction jobs/current approved source/caps. No discovery work is sent to the persistence-probe task. Discovery completion leaves extraction jobs draft and creates no extraction result, contact or billing event.

The two search pages contain five raw result entries, including one duplicate; four unique articles are discovered. Source-reported five is a count hint, never a verified unique denominator. `pagination_exhausted` is scoped to the connector fixture. Page/article/source caps (including an exactly exhausted budget before a nonterminal next page), changed or ambiguous selectors, repeated cursor/fingerprint, changed totals and no-new-results stops preserve truthful partial state. The single-article mode discovers one authorized article without claiming it has been extracted. Every candidate link remains inside the explicit registered route set; footer/support/reference/navigation links are excluded.

## Checks and acceptance

Run `scripts/check.sh` for available local gates. `test_discovery.py` contains pure fixture/input/limits/schema tests. `test_discovery_tenant.py` requires actual disposable PostgreSQL for RLS, current-policy, deletion, cancellation, revision/replay, caps, API and outbox tests. `test_discovery_broker.py` requires actual disposable RabbitMQ and worker processes for restart/duplicate recovery. Missing dependencies explicitly skip locally and cannot establish acceptance. Required application CI must run all tests without skips; parser CI must report four unique articles, five raw entries and one duplicate within the unchanged network-none/resource boundary. All existing browser, controlled transport and docs checks remain required.

## Migration and rollback

Migration `0004_discovery` adds forced-RLS discovery and identifier-only discovery_outbox tables with composite tenant/job/source foreign keys, immutable context/revision/current-policy guards and no runtime DELETE or authenticator grants. It changes no existing extraction/probe state transitions or worker credentials. Upgrade through Alembic using the disposable migration role. Migration replay is covered by the existing double-upgrade CI. Destructive downgrade is refused; use a forward repair or restore a disposable test database. Organization offboarding/deletion fences access and writes; physical retention/purge remains the later lifecycle slice.

## Limits

This is synthetic offline discovery, not live-source certification. Fixture reads create no publisher requests; no claim of production source-wide network throttling or quota enforcement follows from them. No acquired untrusted HTML is parsed in the API. Production identity/worker provisioning, live gateway composition, PDF/DOI resolution and source-specific filtering require their documented later gates. The UI continues to state extraction is unavailable. EM-007 can follow only after independent review and actual required CI verify this scoped slice.

# 52 — Controlled provider operator composition

## Scope and preconditions

This partial EM-015 candidate connects the existing normal authenticated operator UI and registered Celery execution task to the controlled synthetic provider journey. It does not activate real ScienceDirect access or certify a live connector. The preceding [journey](51-controlled-provider-journey.md), [protected gateway](50-controlled-provider-gateway.md), source policy, tenant authorization and isolated parser controls are unchanged.

A trusted Python caller may supply an `ExecutorFactory` to `create_worker`. The default dispatcher still uses `Progress.process_fixture`, including its explicit provider refusal. Only a caller-composed `ExecutionDispatcher(progress, dispatch)` can route the exact server-registered provider URLs to `ProviderJourney`. The factory receives the current Progress service after the normal durable event validation and current-generation claim. Queue/API/config JSON cannot specify a factory, import path, credentials or transport. Provider errors cannot fall back to authored fixture bytes. This seam is application composition, not production worker identity or credential registration.

The controlled acceptance proposes and approves a separate synthetic policy through the existing authenticated source-policy API, with explicit search, fetch_xml, extraction, excerpt retention and export operations. It does not edit an existing policy or expand the standard HTML-only Sources screen proposal. UI text explains this precondition. No migration, dependency, entitlement, security setting, real credential or live source permission changes.

## Required connected evidence

The new isolated UI case uses keyboard events to create/plan/start the `Controlled provider journey` keyword. Its publisher reads the durable outbox, confirms real RabbitMQ publication, and the ordinary registered task claims current SQL work. A single real solo Celery worker thread exclusively uses the controlled gateway pipe. The host owns the existing Topology and never passes broker/database credentials to the network-none browser. The normal protected HTTPS gateway obtains one search and two FULL XML documents, and the network-none parser returns observations into current tenant SQL.

The UI reviews two retained citations, requests both CSV and XLSX, and downloads both distinct artifacts through authenticated routes (the browser cancels saving to disk). Host assertions check actual parser profiles, DOI/PII identities, transport provenance, two durable effects, two review receipts, three finished source tickets and zero active HTTP units, both exact-address export contents and tenant-B denial. The browser switches to its read-only second organization and must clear first-tenant content. The existing 41-case controlled journey suite separately retains source-spacing, duplicate/recovery, authority-race and IPv4/IPv6 coverage.

## Bounded lifecycle and existing deadlines

Worker startup has a 20-second readiness deadline, then passive inspection must find consumers on every exact owned queue. The helper avoids Celery's testing helper's unbounded readiness event. It runs `WorkController` with solo/concurrency one and the application's normal queue/ack/prefetch configuration; it does not call the task directly or enable eager mode.

A thread-bound per-I/O gate checks ownership and revocation inside a lock for each send/receive. The lock never spans SQL callbacks or parser work. Shutdown revokes future pipe use, waits at most 25 seconds for an admitted at-most-20-second pipe operation, and poisons an interrupted protocol. The thread then has a 150-second cleanup allowance covering explicit transport/parser-control budgets. This is not a claim that SQL or arbitrary Python scheduling has a global deadline. Failure to join is a failed acceptance, and the revoked capability cannot touch the gateway if a callback returns late. Normal topology inspection follows clean worker shutdown; uncertain protocols fail closed and enter owned cleanup.

The original static operator test retains its eight-second job-completion assertion. The separate provider case waits at most 75 seconds for the actual UI completed state because three genuine acquisitions incur the existing source-wide spacing plus HTTPS and isolated parser startup. The browser RPC remains ten seconds per request, 512 total requests, eight active, sixteen admitted, and the host conversation remains 180 seconds. No success predicate, request cap, guest isolation or existing static deadline is weakened.

## Verification and remaining work

See [candidate evidence](../reports/em015g-validation.md). Local pure/unit passes and explicit service/container skips do not establish real broker, HTTPS, browser or parser acceptance. All seven exact-head CI gates and the new connected operator receipt remain required. Historical intermittent UI exception and inherited Pydantic warning remain unresolved; this composition is not a speculative fix for either. Real-source legal permission, entitlement, credential store, current live admission, approved egress, wrapper compatibility and production identity/registration remain separate activation gates. No merge or deployment is authorized by this candidate.

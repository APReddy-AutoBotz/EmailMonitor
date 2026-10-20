# EM-017 service reference runtime validation

Candidate, 2026-10-20. No commit/tree acceptance is asserted yet. Base is the
completed observation-quality draft (PR45); this candidate is separate and unmerged.
See [runtime contract](../docs/66-durable-service-reference-runtime.md).

## Local evidence so far

- Installed artifact collection, separately retained receipt verification,
  materialized import/CLI/HTML fixture closure; actual local TLS PKCE exchange
  success, proxy-ignore, redirect/oversize and slow-drip refusal; authority models:
  latest combined focused run **41 passed, 3 service-dependent skips**.
- Owned timer reconciliation, cursor/budget behavior, partial construction,
  resource cleanup, fixed CLI diagnostics and API dependency readiness:
  **55 passed**, including an actual installed Celery controller failure/stream
  probe with outbound connections forbidden; most cases use stand-ins. This is
  not SQL/broker acceptance.
- Regression fixes preserve XML import isolation and approved fixture test doubles:
  closure subset **115 passed**. The initial broad candidate run had 42 failures,
  traced to those two compatibility regressions; those failures are not hidden.
- Subsequent broad run: **3001 passed, 336 skipped, 1 failed**. The failure was
  `test_real_trace_failure_has_no_diagnostics_when_disabled[claim_error]`, whose
  spawned subprocess exceeded the existing ten-second join under concurrent local
  test load. Its exact isolated rerun passed in **3.71 seconds**. An earlier
  focused run similarly had 144 passes and a different subprocess timeout whose
  isolated rerun passed. No production deadline or existing assertion was relaxed.
- Serialized broad rerun: **3052 passed, 336 explicit service-dependent skips**
  in **157.39 seconds**. Final frozen-tree normal/fresh aggregates remain pending.
- First full normal gate: **3151 passed, 351 skipped, 2 failed**. Both failures
  were original-workflow preservation assertions. The original operator workflow
  was restored byte-for-byte; new runtime jobs moved to a separate synthetic-only
  workflow, with its explicit filename added to the inventory assertion. All
  **51** private-diagnostic workflow preservation tests then passed. No original
  hash assertion or one-shot trigger/control was relaxed.

- A subsequent full normal gate recorded **3186 passed, 351 skipped, 1 failed**: the
  existing isolated composition test exceeded its combined ten-second interpreter
  startup/action wait. Independent review approved a test-only ready handshake at
  wrapper entry: startup is capped at 30 seconds; unchanged probe actions retain
  ten seconds and kill/reap retains five seconds. Startup and action failures are
  distinct, with no retry. Five existing composition call sites use the helper;
  production execution deadlines are unchanged. Final full gates remain pending.

- The next normal gate recorded **3191 passed, 351 skipped, 1 failed**. An existing
  nine-request channel test assumed only eight identifiers could be emitted, even
  though the ninth request has its own later deadline and can acquire a released
  permit. Independent review confirmed that scheduling assumption was invalid.
  The integration test now accepts eight or nine identifiers while retaining all
  timeout/cleanup checks. Separate held-capacity admission-timeout and controlled-
  clock remaining-budget regressions preserve the exact intended deadline evidence.
  Production channel code and deadlines are unchanged.

## Review and actual-service gates

Independent source review approved the exact two-second server-enforced service
export claim contention wait, unchanged human NOWAIT behavior, and post-wait
revocation/expiry fence. It required exact underlying SQLSTATE assertions and
no persisted admission/artifact on failure; those assertions are included.

Service SQL login validation rejects superuser, BYPASSRLS, CREATEROLE, CREATEDB,
REPLICATION, opposite service roles, human runtime/owner/authenticator membership
and session-minting capability. Review distinguishes the out-of-scope privileges
from an unsupported claim that every flag independently bypasses RLS.

Actual PostgreSQL authority/migration/ACL, RabbitMQ installed-worker crash/replay,
packaged keyboard operator and service container acceptance require their explicit
disposable CI environments. Local skips are not passes. Final exact-tree review,
normal/fresh gates and all exact-head CI receipts are pending. No live identities,
source grants, credentials, acquisition, deployment or merge occurred.

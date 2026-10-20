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

## Initial hosted acceptance receipt (preserved)

Initial draft PR46 head `4af6e75abe9f0cc267ca0fda31acfbf8b576fc52`
used reviewed tree `70b636a34b305c3ae04f7cdf49956ca6bf2724fe`; the GitHub
synthetic merge had the same tree and expected PR45/head parents. Complete normal
and new-empty Python environment gates both passed: **3194 backend tests, 351
explicit local service-dependent skips, 57 React tests**, with documentation,
Ruff/format, mypy (312 files), inventory, typecheck, lint and build passing.

Hosted failures are retained rather than replaced by local passes:

- [Service runtime run 39424496858](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39424496858):
  packaging returned the fixed `SERVICE_PACKAGING_ACCEPTANCE_REFUSED` result;
  that receipt does not establish the failed stage. Installed operator acceptance
  failed its empty worker restart because graceful shutdown required forced kill.
  The failure remains a failure, and no complete installed journey is claimed.
- [Operator UI run 39424496880](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39424496880):
  failed while waiting for jobs after worker processing errors.
- [Controlled transport run 39424496913](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39424496913):
  **36 passed, 5 failed**, with `work_audit` rejecting the existing fixed
  `extraction.observation_committed` action. Both HTML and XML commit call sites
  use this action; the new closed allowlist omitted it. XML owned cleanup was
  verified. Source review is being renewed on a bounded compatibility correction.

Documentation, parser isolation, browser isolation and metadata prerequisite
packaging passed at that head. The [application run 39424496803](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39424496803)
finished **3395 passed, 150 failed**, with no skips, in 854.60 seconds. Of its
150 failure summaries, 140 directly named the omitted `work_audit` action. The
remaining ten include broker-state timeouts, service publication/authority
failures, a human missing-job error-shape regression and an upgrade visibility
assertion; those require separate diagnosis rather than assuming one fix covers
all failures. All eight synthetic workflows are terminal; four passed and four
failed. No failed workflow was cancelled or manually rerun.

Both unchanged opened-only licensed-source jobs were skipped without executed
steps: [sample 39424496840](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39424496840)
and [diagnostic 39424496864](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39424496864).
No source was acquired or diagnosed by this draft.

### Bounded corrections under review

The audit correction restores the four existing call-site actions. Service calls
permit only page/observation commits, exact extraction scope, current permission
and a live execution/admission lease; human delivery receipts retain outbox-event
resource semantics. A fast AST-to-SQL contract now checks the complete literal
call-site action universe even when local SQL is unavailable. Independent review
approved this correction; actual hosted acceptance remains required.

The upgrade visibility assertion now names the exact queued probe in each tenant
and explicitly denies the tombstoned extraction job. Existing restrictive
lifecycle policy was correct; it was not weakened. The other twelve cases in the
initial migration test module passed.

The API shutdown problem was reproduced using pinned Uvicorn and real verified
TLS without SQL: holding the readiness client open required forced kill at
5.008 seconds; closing that owned client first exited in 0.214 seconds. The
harness now closes that client before API teardown on success and failure.
Independent review approved the ownership-order correction. The five-second
cleanup bound and forced-kill failure remain unchanged.

Packaging currently adds only closed stage/build/cleanup diagnostics and a
strictly validated guest stage. It does not claim an identified recipe defect.
Raw errors, paths, configuration and stderr are not forwarded. Independent review
confirmed unchanged Dockerfile, confinement, limits and success receipts. Actual
container acceptance is still required.

The ledger correction maps only the exact database `P0001/JOB_UNAVAILABLE`
refusal to the existing `AuthorizationDenied` contract. Twelve pure cases check
that matching refusals suppress database exception context while nonmatching
errors remain unchanged. Independent review approved the bounded mapping.

Two publisher failures separately showed `55P03` contention on the extraction
job row. Only the pre-send extraction selection now catches that contention in a
nested transaction block and returns no event; no send or receipt occurs. A later
ordinary publication pass may try again. Confirmation contention remains fatal;
authority, privacy and entitlement checks remain outside the handler, and export
semantics are unchanged. Independent review approved the implementation and
regressions for held job/item/outbox rows, later publication, confirmation failure
and revocation between enumeration and scoped execution. Focused local checks
passed 66 tests with 69 explicit SQL/broker skips. Actual service tests remain
required. The five older broker effect-wait failures correlate with the omitted
audit action in retained PostgreSQL logs; that diagnosis still needs hosted
validation rather than a longer timeout.

The worker shutdown investigation used the pinned solo controller with a
synthetic asynchronous transport. Its existing warm-shutdown handler fired
immediately, but the hub waited approximately 4.91 seconds for the unchanged
five-second reconciliation timer. The original five-second cleanup required
forced kill; an independent signal wake exited in 0.079 seconds. This is a causal
local controller probe, not RabbitMQ or installed-journey acceptance.

The correction gives only the owned service worker a separate nonblocking,
close-on-exec wake pipe. Celery handlers, reconciliation timing and cleanup
bounds are unchanged. It requires the main thread, exact solo pool and live hub;
foreign ownership is refused, replacement is detected, and uncertain restoration
retains descriptors while latching a fatal runtime failure. The entrypoint
checks that latch even when Celery swallows bootstep cleanup errors. Python's
wake-FD API cannot expose a foreign owner's previous warning flag; cooperative
main-thread ownership remains an explicit constraint. Focused tests include
real signals, full pipes, partial startup, repeated close and failed restoration.

## First correction hosted receipt (preserved)

Head `7e3ebac8d4b31a9cffbf4c9b1bd72df6bff98e20`, reviewed tree
`808e0a1f36a00e29b409ec979455cbed61b3d98d`, passed both full local gates:
**3289 backend tests / 375 explicit infrastructure skips and 57 React tests**.
The first normal attempt had six deadline failures in unchanged subprocess/TLS
cases; a focused diagnostic had 212 passes and one remaining XML refusal-process
deadline failure. No deadline or affected source was changed. Static review found
no new runtime import in either XML startup closure. The exact source subsequently
passed the genuinely fresh and serial normal aggregate gates. These later passes
do not erase the earlier failures or establish their precise timing cause.

[Service runtime run 39431571356](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39431571356)
failed both new acceptance jobs. Packaging localized to build one, `probe_execute`,
with `guest_stage=unknown` and cleanup verified. This does not prove an OOM.
Installed operator acceptance passed initial worker restart/cleanup and reached
browser `assets_session`, where only HTTP 401 and 303 replies were observed before
failure. The [original operator UI run 39431571498](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39431571498)
passed. Remaining actual-service results are being tracked separately; no manual
rerun or source acquisition occurred.

The first correction's [application run 39431571290](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39431571290)
failed at the existing 900-second aggregate wrapper bound, after reaching 84% of
3664 collected cases. Three service-broker cases had failed; no final pytest
summary or failure stacks were emitted before the wrapper stopped its consumer.
Owned XML cleanup was verified. This remains a failed, incomplete receipt.
Controlled transport passed 41 curated cases, two additional single-case checks
and four operator cases with owned XML cleanup verified. Overall: six synthetic
workflows passed and two failed at that head.

### Second bounded correction

The packaging probe previously retained a full imported application while
starting another full CLI interpreter. Local simultaneous anonymous RSS exceeded
128 MiB, but the hosted receipt does not establish an OOM. The correction runs
seven sequential containers per image: real default CLI help, single-process
integrity/import/kernel/model checks and five actual exec-based production-command
refusals. Each refusal keeps its five-second bound and shares the former probe's
45-second total budget. Exact stopped/non-OOM state, exit and bounded output are
required before counting success. All confinement and cleanup controls remain;
the truthful final receipt counts fourteen containers. Independent source review
approved this correction; focused checks passed 145 cases.

The installed browser preserves real 303 responses and Set-Cookie. A closed
coordinator validates two ordered hops per login, observes the exact redirected
main-frame GET fail in the network-none guest, then consumes one explicit
navigation to that captured approved target. Four hops across two logins are
required. PKCE, cookie/state validation, actual callback UI, TLS and the single
ten-second login budget remain. Unexpected navigation events latch failure;
ordinary old-document aborted fetches do not grant redirect authority. Independent
review approved the six harness files; focused checks passed 117 cases with one
explicit unavailable-service skip. Native Chromium redirect completion is not
claimed by this relay acceptance.

The enlarged application's aggregate-only budget becomes 1200 seconds under a
25-minute job. Controlled transport's wrapper1200/consumer900/job25 bounds stay
unchanged, as do every individual test/runtime deadline and the separate
180-second cleanup plus five-second stop/five-second reap. Observed setup took
45 seconds; future runner overhead still needs to fit the remaining reserve.
The original workflow hash test normalizes only the single reviewed timeout
field before comparing its pinned original bytes. A focused actual service-broker
step also runs in the existing disposable installed-operator job, retaining the
complete aggregate suite and allowing independent browser evidence after
successful prerequisites even if the focused step fails. Either failure remains
fatal to the job; no continue-on-error is introduced.

Two extraction-journey test corrections preserve runtime authority checks. The
positive installed extraction now uses the existing 30-second worker lease
instead of a deliberately short five-second fixture lease. Completion polling
uses a nonlocking admin observation of the exact synthetic org/job state; final
human-authorized progress/state/count checks occur after worker stop. The crash
test retains its 30-second lease, before-expiry redelivery proof and unchanged
15/60-second waits and exact effects/observations. This avoids test polling's
job-share-lock conflict with active worker writes. Export-race failure remains
separately unresolved pending the focused real-service failure stack; that test
was not changed. Focused checks: 36 passed, 12 explicit actual-service skips.

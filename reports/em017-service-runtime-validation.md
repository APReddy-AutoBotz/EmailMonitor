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

## Second correction hosted evidence (in progress)

Head `fe59987a084cc3c66f534c7d1eab6d184c018932` used independently reviewed tree
`8730e22b16fd1fc37b50e0f9b996a800777ecfad`. Both full local normal and genuinely
fresh-environment gates passed **3386 backend tests / 375 explicit infrastructure
skips and 57 React tests**, with all aggregate checks.

[Actual packaging job 118675986076](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39436846819/job/118675986076)
passed: two independent web/image builds had matching artifacts, base inventories
and image contents; fourteen network-none containers passed, five actual CLI
production refusals per image passed, and owned cleanup was verified. OCI archive
bit-reproducibility and production readiness remain explicitly false. This closes
the packaging acceptance failure without proving the earlier hosted OOM hypothesis.

[Focused service and installed browser job 118675985594](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39436846819/job/118675985594)
retains **11 actual service-broker passes and one failure** in 141.32 seconds.
Installed extraction through session expiry/restart, extraction crash/redelivery,
contention and revocation cases passed. The export race failed at its
`wait_for(unpublished)` observation, before its rendering-completion loop. Its
prior empty-queue predicate did not prove claim contention: zero ready/unacked
also describes a pre-delivery gap. The bounded test correction now requires
observing the exact worker's active claim Lock wait blocked by the uniquely owned
publisher, within the same shared twenty-second barrier, before accepting drain
and queued/attempts-zero observations. No production fence or lease changes.

Installed browser acceptance still failed at `assets_session`, with API reply
statuses 401/303/303. That establishes the first routed issuer hop, but callback
static replies are absent from this list and the failure reason remains unknown.
No callback or ancestry cause is inferred. A closed diagnostics-only refinement
will distinguish fixed login phases and rejection causes without recording URLs,
headers, cookies, codes, state, exception messages or DOM content. Actual browser
completion remains unmet.

The diagnostics refinement adds only finite source-authored reasons and an
optional nine-value installed-login phase on failure frames at the two existing
login stages. Old absent-field frames and host text remain compatible. The first
fixed reason/class/phase is immutable; unknown exception classes map to the
existing UnexpectedError value, including terminal stderr. Phase clears after
successful login. No new awaits, retries, deadlines, navigation predicates or
success-receipt changes are introduced. Focused checks passed 227 tests with one
explicit unavailable-service skip. The deterministic export barrier's focused
checks passed 55 tests with twelve actual SQL/broker skips. Hosted evidence for
both remains pending.

### Second correction terminal aggregate

[Application run 39436846952](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39436846952)
finished **3760 passed, 1 failed, no skips**, in 1130.48 seconds. The sole failure
was the same export `wait_for(unpublished)` race observation. The controlled XML
composition and owned cleanup passed. The run was within the reviewed 1200-second
aggregate budget, but remains failed. All eight workflows terminated: six passed,
application and service reference runtime failed. No real-source run occurred.

## Third correction hosted evidence (in progress)

Head `e11e69a4d622ddcfbcfe67e753ea55cdb9b14f1a` used independently reviewed tree
`4eae845d253f05514489060f8a6088fa33c04613`; its test merge had that same tree and
expected PR45/head parents. Both full normal and genuinely fresh local gates passed
**3429 backend tests / 375 explicit infrastructure skips and 57 React tests**,
with all aggregate checks. These skips are not actual-service acceptance.

[Service run 39440797602](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39440797602)
passed packaging again. Focused actual PostgreSQL/RabbitMQ broker acceptance passed
**all 12 tests in 89.89 seconds**, including the corrected export race barrier.
Installed browser acceptance remains failed: its closed diagnostics identify
`assets_session`, exception class `Error`, reason `installed_login_failed`, phase
`callback_document`, with actual API reply statuses 401/303/303. This localizes the
failure to callback-document navigation before callback-session verification;
it does not establish a completed login or operator journey. The aggregate
application and controlled transport gates are still running at this checkpoint.

### Third correction terminal aggregate

[Application run 39440797573](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39440797573)
passed **3804 backend tests, no skips or failures**, in 1136.06 seconds, followed
by **57 React tests** and all aggregate checks. Controlled XML integration and
owned cleanup passed. The independent full aggregate therefore also accepts the
export race regression. All eight workflows are terminal: seven passed; only the
service workflow's installed browser journey failed. No real-source workflow ran.

### Fourth correction design evidence

An authored deterministic lifecycle probe invoked the installed Playwright 1.63.0
`Frame.gotoImpl`: a prior failed document committing during the next navigation
raises a document-ID mismatch; settling that prior commit before the next call
returns the authored successful response. This establishes a possible mechanism,
not the hosted failure's root cause. A supplementary system-Chromium 154 probe
could not launch under the private namespace's existing sandbox constraints and
provided no browser acceptance evidence; no sandbox/network relaxation was made.

Independent design review approved a test-only per-hop lifecycle barrier. It must
retain the exact existing failed Request predicate, correlate the failed document
using read-only CDP main-frame identity, exact pending unreachable target and fresh
loader, observe that loader's DOMContentLoaded, and ensure Playwright's own frame
manager has consumed the error-document commit and DOMContentLoaded. These are
observations within the original ten-second login budget, without extra navigation
or retries. Target and loader identities remain transient and excluded from
receipts. Exact implementation/cleanup review and hosted acceptance remain pending.

The implemented barrier's focused validation passed **302 tests**, with one
explicit unavailable SQL/broker installed-journey skip. Ruff check/format and
strict mypy passed. The durable regression invokes the installed pinned Playwright
navigation implementation with authored events and verifies both the late-commit
failure and settled-commit success. Observer setup is capped at ten seconds and
owned detach at five seconds; teardown precedes browser/context closure and any
cleanup failure prevents acceptance. No public receipt/diagnostic fields changed.
Exact cleanup review and complete normal/fresh gates remain required.

Exact independent implementation review returned source GO at all four changed
source/test hashes. It confirmed unchanged URL/cookie validation, isolation,
receipts and the original twelve login awaits/two navigations/one ten-second
budget. Bounded four-loader state and partial setup/teardown ownership were
reviewed; setup/detach fit within the unchanged 180-second host envelope. No
blocking changes were requested. Complete gates and hosted evidence follow.

Fourth-correction full normal gate passed **3504 backend tests / 375 explicit
infrastructure skips and 57 React tests**, with all documentation, Ruff/format,
mypy, inventory, frontend typecheck/lint and build checks. Backend elapsed time
was 166.82 seconds. A genuinely new-empty Python environment gate is running;
actual hosted browser acceptance is still required.

## Fourth correction hosted evidence (in progress)

Head `470beb8b1badfa4e214777099596478e8ac2e6c4` uses reviewed tree
`2644b2aa0d2134954fec81903bfaca1cdc0e49bc`; its synthetic merge has the same tree
and expected parents. Both normal and genuinely fresh full local gates passed
**3504 backend / 375 explicit infrastructure skips and 57 React tests**, with all
aggregate checks. Fresh backend elapsed time was 197.79 seconds.

[Service run 39447562879](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39447562879)
passed actual packaging again and **12 focused actual PostgreSQL/RabbitMQ broker
tests in 117.60 seconds**. Installed browser progressed through both sign-ins;
its failure moved to `keyword_worker`, fixed reason `installed_route_relay`,
exception class `RuntimeError`, without an active login phase. Numerous successful
authenticated API replies do not establish worker completion. The exact relay
refusal requires further diagnosis; full aggregate acceptance is still running.
The earlier callback-document failure is retained, and this progression does not
retroactively prove the hypothesized late-commit cause.

### Fifth correction scope and evidence

The installed positive-work harness retained a five-second execution lease, while
its restart is explicitly an empty-process restart and natural browser expiry is
independently tested by shortening that session to 500 milliseconds. Independent
review approved using the existing supported thirty-second worker default in this
test only, retaining the publisher's five-second lease, all browser expiry/control
ordering, UI deadlines and exact outcome assertions. An AST regression pins those
boundaries. Focused validation: **129 passed, one actual-installed dependency
skip**; Ruff/format/mypy passed. No SQL or production runtime changed.

The retained PostgreSQL `ASSOCIATION_DENIED` occurred at the parent composite
fence late in association writes, not the affiliation-value guard. Lease expiry
is consistent with this observation but not uniquely established. It is not
conflated with the guest relay failure. An authored ASGI probe confirms ordinary
host relay exceptions propagate through the distinct host-owned error path.
Request-local closed diagnostic reasons for the existing guest request/admission
capacity, envelope-size and outer-status guards are therefore being added without
changing shared Channel behavior, accepted responses or limits. Unknown exception
text must retain the generic reason; no raw exception details may be emitted.

Exact independent source review approved both the isolated worker/publisher lease
split and diagnostics-only patch. Diagnostics focused validation passed **328
tests**, with one explicit unavailable installed SQL/broker dependency skip;
Ruff check/format and strict mypy passed. Request-local classification re-raises
original exceptions; first-cause capture and shared Channel remain unchanged.
The guest retains 108 awaits, identical timeout calls and the approved login
barrier. No actual relay cause or complete browser journey is claimed. Full
normal/fresh gates and actual hosted acceptance remain required.

### Fourth correction terminal aggregate and fifth local gate

[Application run 39447563441](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39447563441)
passed **3879 backend tests, no skips or failures**, in 1114.39 seconds, plus
**57 React tests** and all aggregate checks. XML composition and owned cleanup
passed. All eight workflows terminated: seven passed; only the installed browser
journey failed in the service workflow. No real-source workflow ran.

The fifth correction's complete normal local gate passed **3530 backend tests /
375 explicit infrastructure skips and 57 React tests**, with documentation,
Ruff/format, mypy, inventory, frontend types/lint/build all passing. Backend time
was 190.59 seconds. A genuinely fresh-environment full gate is running; actual
installed browser acceptance remains required.

The fourth installed-journey failure also retained a secondary
`Installed operator cleanup failed: process-forced-kill` receipt. This is an
unresolved cleanup failure, separate from both the relay refusal and the lease
hypothesis; no successful cleanup or complete journey is inferred for that job.
The fifth correction's genuinely new-empty full gate subsequently passed unchanged:
**3530 backend / 375 explicit infrastructure skips and 57 React tests**, all
aggregate checks, backend elapsed 157.76 seconds.

## Fifth correction hosted evidence (in progress)

Head `2ee98379c099f618f9f33e763f397c3d63a9fd6e` uses reviewed tree
`23eeb1295dfa3ca4052daf175f3ff8cb6f484e1e`, with matching synthetic merge tree
and expected parents. [Service run 39451346638](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39451346638)
passed actual packaging and **12 focused actual broker tests in 114.08 seconds**.
Installed browser remains failed at `keyword_worker`, now with the exact closed
reason `installed_relay_admission_capacity`. This identifies the existing guest
RPC admission guard; it does not by itself establish why requests accumulated.
The secondary `process-forced-kill` cleanup failure persists. Its owner is either
the active worker or API; the generic receipt cannot distinguish them. The
publisher, guest browser and completed empty-worker restart are excluded by the
source call paths. No cleanup success or complete journey is claimed. Full
aggregate acceptance remains running.

### Sixth correction design evidence

The admission guard directly establishes that sixteen guest RPCs were already
admitted when the next was refused. Source tracing identifies artificial global
refresh waves every 0.4 seconds in the two job waits; each restarts multiple
workspace/job resources. Browser fetch cancellation does not cancel already
admitted host relay work. Individual SQL read transactions close before SSE
sleep; no shared SQL lock spanning that sleep or production deadlock is proved.

Independent design review approved replacing only those two harness refresh loops
with exact visible terminal-state waits within the original 55/30-second budgets.
The normal app path consumes durable job-finished events, scoped cursor replay
and fresh authorized progress reads, including completion before subscription.
All outcome/count/effect assertions and Channel limits remain; the export loop
is untouched. A final reload failure must still fail acceptance, without a manual
fallback. Separate source-authored API/worker forced-kill labels will distinguish
existing teardown failures without altering the five-second bound or behavior.
Actual complete journey and shutdown acceptance remain required.

Sixth-correction focused validation passed **339 tests**, with one explicit
installed SQL/broker dependency skip. The authored actual-Channel regression
reproduces admission refusal with overlapping held waves, while completed
seven-request waves plus a held SSE request fit the unchanged eight active slots.
Tests compile the actual guest terminal-wait blocks and verify exact visible
states, original 55/30-second envelopes and failure propagation without refresh
or retry. Ruff/mypy checks pass; exact source review and full gates follow.

The complete sixth-correction normal local gate passed **3541 backend tests /
375 explicit infrastructure skips and 57 React tests**, with all documentation,
Ruff/format, mypy, inventory, frontend typecheck/lint and build checks. Backend
elapsed time was 165.94 seconds. A genuinely fresh full gate is running; no
complete hosted installed journey is inferred from local skips.

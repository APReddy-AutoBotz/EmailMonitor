# Installed controlled XML runtime — validation record

Status: local implementation candidate; hosted acceptance outstanding. No merge,
deployment, production source, source entitlement, API credential or service login
activation is authorized by this record. Actual CI uses disposable synthetic roles.

## Baseline and source ownership

Accepted dependent baseline: Draft PR46, head
`713c517750bb98c5330b26292b2582cd4aef5676`, tree
`a361145aa11fb418db6e119d5351a9f8d3c7c787`. The prior worktree was preserved. A separate
checkout was reconstructed from retained content-addressed publication material;
its tree and original commit exactly matched GitHub before edits began.

## Design review

[ADR0007](../docs/adr/0007-installed-controlled-xml.md) records the trust roots.
Independent review rejected an initial same-host subprocess design: passing only
an anonymous descriptor does not prevent opening the host Docker socket. The
implementation now uses a fixed immutable installed service container,
without host mounts/socket, with explicit read-only Docker-exposure prerequisites.
The trusted SQL worker's host networking is not claimed as protected egress.
Gateway and network-none parser retain their separate isolated boundaries.

Independent source-level review approved the confined launcher/channel, bootstrap,
read-only exposure prerequisite, provider proxy and immutable parser lifecycle.
The reviewer independently passed 128 channel/parser/exposure/launcher tests plus
nine pipe/confinement tests. This is source evidence, not actual Docker execution.

The earlier host-subprocess unit tests were useful protocol evidence only. They
are not accepted worker-isolation or installed-container evidence.

## Early local receipts (not complete acceptance)

- Existing lifecycle/CLI regression suite: 83 passed after preserving the default
  constructor call shape. The initial run had ten test failures from the new
  unnecessary `None` keyword argument; no runtime lifecycle assertion was weakened.
- Closed profile/admission tests: 17 passed.
- New immutable parser owner tests: 43 passed; mocked controls only, not Docker.
- New read-only daemon-exposure tests: 37 passed; mocked privileged reads only.
- Frontend: 77 React tests, typecheck, lint and build passed at its first checkpoint.
- XML packaging wrapper tests: 57 passed at first checkpoint.

Final combined normal/fresh gates, actual SQL/broker/container/browser gates,
exact-tree review and exact-head hosted results remain required. Local skipped
infrastructure tests never count as actual execution. Later edits invalidate
unrepeated whole-candidate claims.

## Required actual proof and limits

The installed keyword and direct URL paths must demonstrate genuine service-role
SQL, broker delivery, protected controlled HTTPS acquisition, pinned network-none
XML parsing, normal evidence review and CSV/XLSX. Source policy approval remains
an explicit human step. XML v1 attribution and quality/partial warnings are unchanged.

Post-observation kill/recovery must use an actual owned worker-container kill and
fresh verified gateway session, with no repeated acquisition or parsing and once-
only durable effects. A kill is a recorded failed session, not graceful cleanup.
Inherited tenant, revocation, lease, retention/deletion and provider-race gates
remain required; additional service-specific race gaps must be stated explicitly.

## First published candidate and October 22 reconstruction

Draft [PR47](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/47) first head
`739710487a9b8fae37067cf8518c64602a970260`, tree
`c10117ea513ede1a003c7686500132cf02a1531a`, completed its hosted runs. Application
[39486194699](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39486194699)
passed 4364 backend cases and 77 React cases. The service run
[39486194364](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39486194364)
passed packaging, 12 actual broker checks and the inherited installed HTML journey,
but its four installed XML cases returned three failures and one pass. The held-
response delegation-revocation case passed without parsing or durable observations;
the owned cleanup marker was present. This does not establish the other XML paths.

Two faults were identified: Docker's initial created/non-running state was treated
as worker exit before attach completed; the crash harness's ACCESS EXCLUSIVE lock
blocked authority function planning before the intended observation commit. The
correction waits for strictly verified running state within the existing shared
20-second bootstrap/start budget, and uses a SHARE lock with the exact worker
INSERT and owned blocking backend to identify the post-observation crash point.
The 45-second barrier wait, exit-137 check and fresh no-fetch/no-parse replay checks
are unchanged. No migration, dependency or production permission changes occur.

An earlier unpublished correction and its local receipts were lost when the
workspace snapshot was restored. They are not recovered or reused as this
candidate's evidence. On October 22 a separate checkout was reconstructed from
GitHub's exact published PR47 objects; both commit and tree above matched before
new edits. The two fixes and regression cases were implemented anew. Independent
fresh source review found no blocking issue, pending formatting, execution and
immutable-tree review. New serial normal/fresh local gates and all eight hosted
acceptance workflows on the eventual corrected head remain required.

Historical timing evidence is retained: the lost correction's concurrent local
aggregates each hit the inherited DNS deadline test's expected-two/observed-one
query assertion; its focused rerun and a subsequent serial normal aggregate
passed. Scheduling load was not proven to be the cause. No timeout or assertion
was relaxed, and those receipts do not validate this reconstructed candidate.

Fresh reconstruction focused checks: 34 launcher cases passed; 41 harness cases
passed with four explicitly gated actual-service skips. Both assigned-file Ruff
and strict mypy checks passed. Serial canonical `scripts/check.sh` normal and
new-empty Python environment runs each exited zero: 4004 backend passed, 375
infrastructure skips, 77 React cases, 338-file strict mypy, 340-file Ruff/format,
document/contracts checks, inventory, frontend peers/type/lint/build. Backend
elapsed times were 103.25s and 104.73s. Dependency caches and frontend installation
were reused for the fresh Python run; no prior result is counted. Actual Docker,
PostgreSQL and broker execution remains pending hosted acceptance.

## Reconstructed correction: hosted evidence and diagnostic follow-up

Published head `7dab35328ed2433c7fdfa50142f8c2b007e29559`, tree
`5311cb70b628e15eae1130459ef7192437c6eb17`, passed seven of eight first-attempt
workflows. Application [39711432703](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39711432703)
passed 4379 backend cases without skips in 1086.95s, 77 React cases and owned
cleanup. A separate newly empty archived checkout also passed the full local gate
(4004 passed/375 infrastructure skips in 108.43s, 77 React); Python and frontend
installations were absent before creation, while package caches were reused.

Service [39711432970](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39711432970)
failed two jobs. Packaging job 119603440264 hit the unchanged five-second
start/attach limit for build one's first API production-refusal probe. Its earlier
full installed-image probe succeeded; cleanup verified removal of the exact owned
container, observed running and not OOM-killed. Guest outcome remains unknown.
The packaging path does not call the changed controlled launcher. Docker startup,
import duration or a guest stall remain possible; runner load is not established.
After all protected runs completed, a bounded retry of this job alone was requested
on the unchanged head; its result is recorded separately when available.

Installed-operator job 119603439824 passed 12 actual broker checks (112.82s) and
the inherited HTML journey (112.74s). The four XML cases failed in 385.86s with
owned wrapper cleanup verified. Keyword/direct URL passed initial startup but
later timed out at the UI worker stage. Crash recovery observed worker exit 137
before its observation barrier; revocation observed no held provider request.
Exit 137 can result from the supervisor's failure kill and does not establish OOM.
No root cause is established. The approximately 21-second worker connections and
open-transaction EOFs are consistent with a failed capability exchange; SQL logs
show no XML-phase lock-timeout or authority-denial error. None of these failed
cases establishes the intended XML acceptance assertion.

Independent review approved a narrow diagnostic follow-up: supervisor-owned fixed
phase/failure enums and saturating callback counters, an immutable constant-size
snapshot retaining the first failure before cleanup, and failure-only harness
rendering. No raw frames, identifiers, URLs, configuration, exception text or
stderr may be included. No new SQL reads, protocol messages, retries, deadline
resets, permission changes or cleanup changes are permitted. The snapshot can
identify the last observed hop; it cannot establish why a worker/SQL callback
failed. Corrected XML acceptance remains outstanding.

Packaging-only retry job 119609965260 passed on unchanged head `7dab35328`:
two uncached builds, equal artifacts/base inventories/image contents, 14
network-none containers, five production-refusal checks per image, and verified
cleanup. The first timeout remains unexplained and preserved above; retry success
does not establish its cause. Installed XML acceptance is still failed.

Diagnostic-only candidate local gates: 88 focused runtime/channel/pipe cases and
81 harness cases passed; serial normal and separate empty-checkout canonical gates
each exited zero with 4058 backend passed/375 infrastructure skips, 77 React,
340-file strict mypy, 342-file Ruff/format and all documentation, inventory and
frontend checks. Backend times were 105.70s and 113.23s. Fresh Python/frontend
installations were absent before creation; dependency caches were reused.
Independent source review found no blocker. Counters are worker-session totals;
startup failures before yielding a handle report diagnostics unavailable. Final
immutable-tree review and diagnostic-head hosted execution remain required.

## Diagnostic-head result and fresh authority composition

Diagnostic head `a54bd4502db705a88cd32385efb45c907d403e17`, tree
`477f8d766f3f40ed60cf019d36327fc9dcb88574`, completed seven successful workflows.
Application [39714597160](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39714597160)
passed 4433 actual backend cases without skips in 1095.10s, 77 React cases and
owned cleanup. Service [39714597193](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39714597193)
again failed the first packaging API refusal's five-second start/attach limit,
with exact-owned cleanup verified and no observed OOM. No further blind retry was
performed. The cause remains unestablished.

Its installed job passed 12 actual broker cases (116.86s) and inherited HTML
(115.92s), then failed all four XML cases (387.37s), with wrapper cleanup verified.
The new snapshots showed CURRENT callback waits timing out after 18, 20 and 22
validated replies for keyword, direct URL and crash respectively. Revocation's
assertion observed RESOURCE_ACQUIRE waiting after six validated replies, with no
failure yet recorded. These are session totals; snapshots identify the observed
hop, not a worker-side root cause. Repeated valid exchanges rule out an initial
attach/framing failure for those sessions.

Source tracing identified avoidable repeated SQL work: each fresh provider request
check opens two authorized transactions and reads policy again after authorization
already returned it. The next independently reviewed composition uses one fresh
short transaction per check, retaining preparation, scope and final authorization
calls, then uses the final authorized policy. The existing service end fence and
commit must finish before returning; no connection, row lock or authority snapshot
survives across a callback/network boundary. Transaction and service-audit counts
intentionally decrease from two to one per check. This is not caching or permission
expansion; all callbacks and deadlines remain unchanged. Runtime benefit and
installed acceptance must still be measured.

A separate approved packaging diagnostic classifies only already-bounded output
on failure: stdout presence and stderr empty/exact fixed refusal marker/other.
It must preserve the first failure, original exception, output limits, deadlines,
success assertions and cleanup. No raw output or new I/O is permitted. This can
establish whether a refusal marker was observed, not why startup timed out.

The authority composition and packaging classification received independent source
GO. New pure tests cover both request routes, fresh transaction state, final policy
selection and failures during preparation, authorization, service end and commit.
Two new actual-SQL cases reuse the existing disposable service-role fixtures:
keyword delegation revocation and article policy revocation. They identify the
exact submitted writer and callback backend, require real lock contention, then
require writer commit after authority transaction release and before binding
return. The next fresh callback must deny. These cases complement, rather than
replace, inherited lease/source/tenant denial coverage. Local PostgreSQL absence
means those two cases are explicit skips until hosted execution.

Packaging classifications describe bytes already captured when failure occurred;
"empty" does not prove the guest emitted nothing. Focused packaging consumers
passed 409 tests. A preliminary normal gate passed 4109 backend cases with 377
infrastructure skips and 77 React cases; its SQL observer was then tightened to
match the exact writer PID, so final normal/fresh gates are recorded separately.
No migration, dependency, credential, persistent grant or deadline change is made.

Final serial normal and separate empty-checkout gates both passed: 4109 backend
cases/377 infrastructure skips, 77 React cases, 342-file strict mypy, 344-file
Ruff/format, documentation, inventory and frontend build checks. Backend timings
were 98.82s and 103.71s respectively. The fresh checkout started without Python or
frontend installations; existing dependency caches were reused. These results do
not execute the two SQL regressions or establish runtime performance improvement.
Independent source review approved the exact-writer lock evidence, transaction
composition and closed packaging diagnostics. Hosted exact-head acceptance is
still required; the preceding diagnostic-head service failures remain unresolved.

## Single-transaction head hosted result

Head `fcc8626f39ecc39f2e212eb53e4292be8af4c55c`, tree
`6599585bbe30ac610be3f7dd14e5be8bf8590d75`, completed seven successful workflows.
Application [39718602096](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39718602096)
passed all 4486 backend cases without skips in 787.11s, including both new actual
SQL lock/revocation cases, plus 77 React cases and owned cleanup. Cross-run elapsed
time differences do not establish a causal performance improvement.

Service [39718601847](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39718601847)
passed 12 broker cases (100.67s) and inherited installed HTML (98.23s), but all four
XML cases failed (349.74s), with owned cleanup verified. Keyword and crash snapshots
showed CURRENT waits after 25 and 28 validated replies; direct URL showed
RESOURCE_FINISH after 26 replies. Revocation saw CURRENT after eight validated
replies at its assertion, without a recorded failure. These observations do not
establish the cause of an unanswered callback or satisfy installed XML acceptance.

Packaging again failed the unchanged first API production-refusal attach limit:
captured stdout and stderr were empty, shared budget remained, container was
running/non-OOM and cleanup was verified. Captured-empty is not emitted-empty.
No retry was performed. Read-only source inspection found avoidable application,
server and broker imports before configuration rejection; import latency remains
an unmeasured candidate, not an established cause.

The next independently reviewed slice defers unnecessary imports while preserving
the existing Pydantic models, validators and single bounded configuration read.
It also explicitly extends the strict callback reply schema with closed elapsed
and initial remaining-budget buckets, without additional messages. The supervisor
records its own round-trip bucket; all last-completed fields update atomically
only after full reply validation and freeze on first failure. Worker timings are
untrusted diagnostic observations, never authority/deadline inputs. They describe
completed callbacks, not the unanswered callback, and cannot isolate SQL or wire
latency precisely. No SQL observer, timeout extension or authority reduction is
included. Final implementation review and all exact-head gates remain required.

Timing/import candidate local verification: 230 focused channel/launcher/diagnostic/
harness tests and 434 import/API/delegation/cleanup/packaging tests passed. Fresh
process tests demonstrate exact minimal production refusal without unnecessary
execution imports and valid actual FastAPI route registration. AST comparison
preserved executable logic apart from imports and function annotations; existing
models/validators are unchanged. The reply is explicitly six keys: four existing
correlation/success fields plus two finite timing enums, with no legacy fallback.

Serial normal and empty-checkout gates each passed 4185 backend cases with 377
infrastructure skips, 77 React cases, 344-file strict mypy, 346-file Ruff/format,
documentation, inventory and frontend build. Backend times were 101.09s and 104.81s.
The fresh checkout had no Python/frontend installation before setup; dependency
caches were reused. Independent source review found no blocker. Hosted exact-head
verification is pending and previous service failures remain unresolved.

## Timing/import head hosted result and test-only experiment

Head `dd0e02aa1c4dd7c8e2518d1c3d6953d8d91f7537`, tree
`33939c0fb4a97a865f1f6054270dfd9bd12494fb`, completed seven successful workflows.
Application [39721294305](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39721294305)
passed 4562 backend cases without skips in 1125.15s, plus 77 React cases and owned
cleanup. Service [39721294262](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39721294262)
packaging passed on its first attempt: two uncached builds, equal artifacts/base
inventories/image contents, 14 network-none containers, five production refusals
per image and verified cleanup. Prior timeout causality remains unestablished.

Installed broker (12 cases, 114.13s) and HTML (112.56s) passed, but all four XML
cases failed (361.17s); cleanup was verified. Last-completed CURRENT callbacks
reported worker elapsed and supervisor roundtrip in [100ms,1s); initial acquire
remaining budget was [5s,20s). Keyword/direct/crash timed out after 21/22/24 valid
replies. Revocation was waiting on RESOURCE_ACQUIRE after six valid replies.
These observations do not isolate SQL or network latency.

Pinned pg8000 inspection found three exchanges per parameterized query and no
TCP_NODELAY option enabled by default. Its buffered writes and response reads do
not establish a Nagle/delayed-ACK stall. A bounded local actual-driver/authored-wire
loopback experiment (six alternating modes, 16 parameterized queries per round,
no injected delays) found medians about 0.17-0.20ms in both modes, maximum 0.434ms.
It reproduced no stall or meaningful benefit and omitted actual SQL, TLS and the
container path. No production socket change is justified by that experiment.

The next independently reviewed change is test-only: existing disposable service
fixtures compare OFF/ON/ON/OFF socket settings on fresh physical connections with
the same provider request/fence sequence, route, endpoint and TLS state. It checks
physical identity/readback and identical results/SQL counts, uses fixed small
samples within an unchanged lease and a 20-second whole-experiment cap, and removes
listeners/disposes each engine. Only rounded saturated timing totals and fixed
labels/counts may be reported, never SQL, parameters, endpoints or credentials.
There is no production hook, caching, speedup assertion or deadline extension.
Actual hosted execution and interpretation remain pending.

Implementation detail: the experiment's 20-second budget is cooperative admission/
observation checking, not asynchronous interruption of an in-flight SQL call.
Existing five-second SQL limits remain unchanged. Nested cleanup guarantees engine
disposal even if listener removal raises. Initial focused checks passed 14 pure
cases with two explicit PostgreSQL-dependent skips; independent source review GO.

Test-only experiment candidate final serial normal/empty-checkout gates each passed
4199 backend cases with 379 infrastructure skips, 77 React cases, 346-file strict
mypy, 348-file Ruff/format, documentation, inventory and frontend build. Backend
timings were 97.65s and 102.98s. Fresh Python/frontend installations were absent
before setup; caches were reused. Neither local run executes the PostgreSQL A/B
experiment. Independent source review GO; exact-head hosted measurements pending.

## Initial A/B harness result

Head `fb1a3ce4de0248ae8b609e0d0ebd81301fc314ec`, tree
`a190116cb4e52ac25f2085c1992c86a903a2a3c0`, did not produce A/B measurements.
Application [39724307394](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39724307394)
passed 4576 cases but failed both new experiment cases (917.11s), with cleanup
verified. The harness incorrectly expected exact `pg8000.dbapi.Connection`;
SQLAlchemy's pinned dialect imports top-level `pg8000`, which exports
`pg8000.legacy.Connection`. Both cases stopped at this check before measurement.
This is a test assumption failure, not transport/performance evidence. The next
correction retains exact supported-class validation and adds an offline regression
against the dialect's actual selected class; production behavior is unchanged.

Service [39724307418](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39724307418)
again passed broker/HTML and failed four XML cases with the same timing pattern,
with owned cleanup verified. Packaging failed the second (worker) production
refusal's unchanged five-second attach limit, captured streams empty, container
running/non-OOM and cleanup verified. No packaging/XML retry was performed.

Inherited parser [39724307446](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39724307446)
passed functional fixtures but correctly refused memory-enforcement proof:
11 observations showed stopped/exit137 with OOMKilled=false. Parser inputs were
unchanged. Removal commands completed by control-flow evidence, but this harness
has no post-removal absence/image-cleanup receipt. After all original runs became
terminal, one unchanged parser-job retry was requested; original failure and all
memory/deadline assertions are preserved. Its outcome remains pending.

The single unchanged parser retry passed (job 119650270659): its first memory
state observation was OOMKilled=true/exit137. Original failure remains recorded;
retry success does not identify why its OOM flag differed.

Exact-class correction source review GO. Serial normal and empty-checkout gates
both passed 4201 backend cases with 379 infrastructure skips, 77 React cases,
346-file strict mypy, 348-file Ruff/format and documentation/inventory/frontend
checks. Backend times: 99.56s and 105.73s. Fresh installations were absent before
setup; caches reused. The added regression verifies the actual installed dialect's
selected class and rejects alternate/subclass shapes without opening connections.
Actual SQL A/B measurements remain pending; no production transport change exists.

## Actual A/B result

Head `3047f1ff465670e057398d9dfd9361e8aa1917b7`, tree
`058e1e76d247814d424dcbaea981647569adf373`, completed seven successful workflows.
Application [39726824687](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39726824687)
passed 4580 backend cases without skips in 941.31s, plus 77 React cases and cleanup.
Both real PostgreSQL A/B cases completed with identical outputs and statement
counts, verified connection/peer/TLS identity and cleanup. Keyword requests took
492-636ms, with 489-631ms in 15 cursor executions; article requests took 476-570ms,
with 473-565ms in 14 cursor executions. OFF/ON samples overlap, showing no useful
TCP_NODELAY improvement in this small workload. No production socket hook follows.
Total experiment times were 4301ms and 4105ms, with no saturated measurements.
These aggregates attribute most elapsed time to DBAPI execution, not to a precise
SQL statement, server execution versus protocol cost, or installed timeout cause.

Packaging and parser passed first attempts. Installed broker/HTML passed but four
XML cases still failed (358.75s), with cleanup verified and unchanged completed-
callback timing pattern. The next authorized test-only attribution adds fixed
statement-category totals/counts to the same synthetic authority path, preserving
all checks, transactions, locks and deadlines. Raw SQL/parameters/identifiers and
credentials must not enter receipts. No production optimization is included until
specific cost is established and independently reviewed.

Category attribution implementation uses twelve fixed trusted statement shapes
plus UNKNOWN, bounded exact-string whitespace matching, and no parameter/result
inspection. Per-category counts reconcile with existing totals and vectors match
across arms. Unknown shapes retain ordinary execution and emit only UNKNOWN.
Times include client/driver/network cursor execution, not server-only SQL cost.
Focused checks: 25 passed, two SQL skips; independent source GO.

Normal and final separately empty-checkout gates passed 4210 backend cases with
379 infrastructure skips, 77 React cases, 346-file mypy, 348-file Ruff/format and
all documentation/inventory/frontend checks. Backend times: 104.69s and 111.12s.
An earlier fresh run also passed (111.28s), but its setup briefly overlapped the
normal frontend tail; a second empty checkout was run after completion to preserve
serial final validation. Fresh installations were absent before setup; caches
reused. Actual statement-category measurements remain pending.

## Statement attribution and bounded CI split

Head `fe315a3e9f2f25116ddef64313cddc118d12492e`, tree
`ae62f549b6098b3a7123517b010b450c4a3e772a`, completed six successful workflows.
Application [39730072508](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39730072508)
passed all 4589 backend cases (1146.44s) and 77 React cases, but the unchanged
1200-second wrapper expired during final frontend build. Cleanup was verified;
this is an overall failed gate, not a complete application pass.

Actual category receipts had UNKNOWN=0 and identical output/count vectors. Source
fences (two executions) took 199-269ms; job lock 151-180ms; execution match 90-114ms;
job permission 65-95ms. Binding/settings were about 0-1ms. The nonuniform pattern
supports investigating nested authority functions rather than socket tuning, but
does not distinguish planning, JIT or server execution. These categories preserve
repeated live permission/delegation/write checks; none is removed or cached.

Service [39730072443](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39730072443)
passed broker/HTML and failed four XML cases (473.74s), with cleanup verified.
Packaging worker refusal timed out despite capturing the exact refusal marker;
stdout was empty, container remained running/non-OOM, and cleanup was verified.
This distinguishes observed refusal emission from completed process/attach exit;
it does not establish why completion exceeded the bound.

The next test-only discriminator replaces socket variation with JIT OFF/ON/ON/OFF
on fresh disposable connections, retaining the same measured requests, fixed socket
settings and authority semantics. Six fixed setup statements per arm apply existing
local caps, read baseline, enable JIT to test availability, set/read back the desired
arm and commit before measurement. No thresholds or production settings change.
Only booleans and existing bounded category receipts are emitted. Constructor/setup
can warm connection-local state identically across arms; any benefit establishes
workload sensitivity, not by itself the installed timeout's cause.

Separately reviewed CI orchestration splits static/frontend checks from the complete
unfiltered actual backend suite. Closed script phases retain the full default local
aggregate; an always-evaluated scaffold join requires explicit success from both
workers. No test, integration requirement, image guard or per-test/runtime deadline
is dropped. Existing backend wrapper 1200s + stop/reap up to 10s + cleanup 180s
leaves at most 110s within the 25-minute job for setup/finalization. Approximately
35s observed backend work headroom is distinct and still variance-sensitive. No
additional backend capacity, test sharding or retries are introduced by this split.

JIT/split candidate focused checks: 43 pure experiment tests with two SQL skips;
548 split/integration/packaging checks passed. Independent source review approved
both slices, including fixed setup readbacks, unknown-input sanitization and the
strict success join. The inherited workflow snapshot retains its original hash
through a narrow reviewed normalization with unique boundaries; separate tests
cover the new phases, suffix and failure/cancellation/skipped join outcomes.

Final serial normal and empty-checkout aggregates passed 4298 backend cases with
379 infrastructure skips, 77 React cases, 347-file strict mypy, 349-file Ruff/format,
documentation, inventory and frontend build. Backend timings: 109.19s and 113.33s.
Fresh installations were absent before setup; dependency caches reused. The local
default aggregate still runs every original command. Actual hosted JIT results,
new split orchestration and complete installed acceptance remain pending.

## JIT discriminator and split result

Head `1efcac84129f2d6f542874ffd38c9d2bc3a0bf37`, tree
`c5645a068ab24f9fa9c66c2005bf5087263b9298`, completed seven successful workflows.
Application [39734828698](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39734828698)
passed the complete actual backend suite (4677 cases/no skips, 1100.93s), owned
cleanup, separate static/frontend worker and required scaffold success join.
Packaging and parser passed; four installed XML cases still failed (366.65s), with
broker/HTML passed and owned cleanup verified.

JIT was available and baseline enabled in every experiment arm. OFF/ON request
costs overlapped (roughly 620-779ms), with job-lock/source-fence spans persisting.
Identical outputs/counts/category vectors and cleanup were verified. This does not
justify a production JIT setting change. Neither socket nor JIT experiments have
identified a useful transport/runtime toggle.

PostgreSQL 17 implementation documents SQL-function cache lifetime within the
calling query, while PL/pgSQL can retain prepared SPI statements. Repeated nested
SQL authority-function planning is therefore a concrete candidate, still unmeasured.
Next test-only evidence uses fixed EXPLAIN ANALYZE calls for job-lock/source-fence
under existing service authority, with bounded numeric summaries only. Separately,
the existing disposable fixture administrator may SET LOCAL ROLE to the existing
owner solely to explain a trusted leaf query after exact installed body/security
metadata checks. That transaction is rolled back; no grants or persistent roles
are created. The product worker never assumes this role. The leaf is explicitly a
standalone surrogate: different invocation/plan caching means it cannot directly
measure nested planning or establish migration equivalence. No function rewrite
or production optimization is approved by these measurements alone.

Fixed-plan implementation focused checks passed 59 pure cases with two explicit
SQL skips, including metadata rejection before owner-role use and unconditional
rollback after setup/execution/sanitizer failures. Independent source review GO.
Plan/node bounds apply after driver JSON decoding, not as a wire-byte cap; queries
are fixed trusted synthetic statements. Worker diagnostic locks use a savepoint
rollback before the normal service end/audit commit; owner surrogate always rolls
back its separate transaction.

Final serial normal and empty-checkout aggregates passed 4314 backend cases with
379 infrastructure skips, 77 React cases, 347-file mypy, 349-file Ruff/format and
all documentation/inventory/frontend checks (108.94s/117.69s backend). An earlier
normal pass preceded final cleanup-test extraction; final normal was rerun after
files froze. Fresh installations absent before setup; caches reused. No actual
plan output or production optimization is claimed before hosted execution.

### Hosted fixed-plan evidence (2026-10-22)

Published head `c52be10803816e9183ead50c1279213505e16885`, tree
`272f4bef41edb742fffcb73aec54d30db1f22f8a`, completed seven of eight workflows
successfully. Application run 39739239826 passed all 4693 actual backend tests in
1031.63s, static checks and the mandatory success join; owned cleanup verified.

Both authored routes reported job-lock execution 147-149ms and source-fence
99-102ms, with rounded outer planning 0ms, no outer JIT and no shared reads.
The separately validated owner leaf surrogate reported planning 4-9ms and execution
0-1ms across 25 nodes. This narrows the candidate to nested function overhead, but
does not directly measure nested planning or prove equivalent rewrite behavior.
Every diagnostic reported cleanup true and uncapped numeric metrics.

Service run 39739239787 failed: broker 12 tests and authored HTML journey passed;
all four XML scenarios failed in 378.56s with owned cleanup verified. Keyword
reached 128 validated callbacks and direct URL 93 before UI timeouts; crash recovery
missed the expected durable state and delegation revocation hit a callback timeout.
Packaging job 119692177509 failed the unchanged 5-second worker refusal attach
probe with empty captured output, running/non-OOM container and verified cleanup.
No retry was performed. All runs were terminal before subsequent source edits.

### Bounded planning and refusal-startup candidate

Independent design/source review permits forward migration 0015 wrapping the
byte-identical private delegation SELECT in VOLATILE PL/pgSQL, plus the mechanical
exact-head readiness update. No authority result is cached. Existing function
identity, ownership, ACL, search path, live clocks and caller lock order remain
required invariants. New guarded actual SQL tests warm the same physical session
and transaction before committed delegation/policy/principal/identity/session/
membership/catalog changes, cover both purposes and tenant/null/unknown denials,
and require private EXECUTE denial and natural deadline expiry. Migration upgrade
coverage compares metadata/OID/ACL and uses an already connected pool. PostgreSQL
is absent locally; authored SQL regressions are not executed acceptance yet.

A separate mechanical ServiceRuntimeConfig extraction avoids importing the worker
execution graph for configurations already rejected by the unchanged model.
Independent source review and 808 focused tests passed. Schema/defaults, validation
order, same-class legacy re-export, valid worker/publisher configurations and
execution/cleanup behavior are retained. Local module counts and timing identified
avoidable work but do not establish the cause of hosted Docker attach failures.
Neither candidate changes production deadlines or grants. Installed performance
and the four XML scenarios still require exact-head hosted proof.

Final serial normal and empty-checkout aggregates passed 4389 backend tests with
388 explicit infrastructure skips, 77 React tests, 352-file mypy and complete
lint/format/docs/inventory/frontend gates (120.30s/126.24s backend). The first fresh
attempt lost its executor session at approximately 91% backend progress and has
no terminal result; it is not a pass. Read-only reconciliation found no remaining
test process before a new empty checkout repeated the complete gate successfully.
The expiry regression normally issues a 10-second synthetic grant and uses bounded
server-clock waits; it never changes the immutable issued deadline or production
limits. Independent final source review GO; actual SQL and installed gates pending.

### Hosted plan-cache candidate (2026-10-22)

Head `e0847b5124162352652ac64619557c31da558a11`, tree
`1081096b6f65dbf05cb0c574bc601b3e7648c56f`, completed with six workflows green.
Application backend job 119710932082 passed 4776 tests and failed one in 1078.31s;
cleanup verified. The new membership freshness fixture attempted to suspend the
sole owner and correctly encountered LAST_OWNER_REQUIRED. The other migration/
warm-cache SQL cases passed. Static checks passed and the required join correctly
failed. No protective database guard was relaxed.

Actual fixed plans now report job-lock execution 25-35ms (previously 147-149ms)
and source-fence 18-27ms (previously 99-102ms), with rounded outer planning 0ms,
no outer JIT or shared reads. These are observed separate hosted runs, not a
randomized causal experiment or proof of nested-planning internals.

Packaging passed on its first attempt. Installed service job 119710931880 passed
broker/HTML and the complete direct-URL XML review/export journey. Keyword reached
completed processing but its harness expected input omitted the existing false
query-change-confirmation default. Crash/revocation cases hit their expected
primary failure, but exact regex matching also included diagnostic exception
notes and prevented post-context assertions. Service XML total: one passed, three
failed in 259.46s; cleanup verified. Revocation logs separately showed SQL authority
denial; its timeout reflects bounded fail-closed teardown, not prompt protocol
refusal. Explicit milestones and all post-effect checks remain mandatory. All runs
were terminal before subsequent test-only corrections.

The subsequent test-only corrections use the ordinary authenticated membership
API to establish a second active owner before warming/revoking the original
membership. Keyword expectations include the existing normalized false default.
Expected failures compare exact exception arguments while retaining diagnostics;
post-exception milestones require completed SIGKILL, held GET, committed revocation,
verified release acknowledgement and completed test body as applicable. Every
original tenant/no-effect/lease/ticket/deadline assertion remains required.
Independent source review GO. Serial normal and new empty-checkout full gates
passed 4397 backend tests with 388 explicit infrastructure skips, 77 React tests,
352-file mypy and all lint/format/docs/inventory/frontend gates (118.41s/128.93s).
Actual membership and complete installed acceptance remain pending hosted execution.

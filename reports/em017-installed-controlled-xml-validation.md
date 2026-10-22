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

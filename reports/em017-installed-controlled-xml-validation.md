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

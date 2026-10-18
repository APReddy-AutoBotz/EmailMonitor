# Operator tooltip integration validation

Candidate based on accepted Draft PR38 head
`415a41dda6b39282e4a47af6dc1400ce59de0078`, tree
`cdcf5cf41cf436251181d0b347ec7131ea876cc2`.
Independent design confirmed existing EM-007/010/012 contracts cover the bounded
synthetic tooltip integration. [Runbook](../docs/59-operator-tooltip-browser.md).

## Preserved development outcomes

Initial focused owned-browser and provider-worker run: 28 passed, one failure.
The existing format-selector AST test assumed exactly one selector globally;
the separate new browser journey adds another. Acceptance worker is narrowing
that regression to the original provider branch without weakening its selector
assertions. No runtime/browser predicate change is inferred from this failure.

Frontend focused aggregate: 48 tests across eight files pass, with typecheck,
lint and build. The inherited npm http-proxy configuration warning remains.

Normal/new-empty full aggregates, independent source/exact-tree review and all
seven actual own-head CI workflows remain pending. Local service skips are not
actual SQL/RabbitMQ/browser acceptance. No live-source or production claim.

Independent lifecycle review found a missing ownership check after the second
SQL authorization callback. Added the post-callback check and a specific
revocation regression before acceptance. Shared worker teardown now attempts its
bounded join even if revocation fails. If the worker remains alive, cleanup is
reported failed and its stop flag/capability remain revoked; resources are not
closed underneath a live owner. Behavioral tests cover readiness, revocation,
join and queue cleanup failures. The first five lifecycle-test cases used an
invalid fixture queue name and failed before worker setup; correcting only the
test namespace yields 36 focused lifecycle/provider tests passing.

Full mypy initially identified a newly shared guest tuple variable and explicit
re-export assumptions in tests. These are test/annotation corrections, with no
runtime permission or deadline changes. Initial Ruff line formatting failures
were corrected by the existing formatter.

The first normal aggregate returned exit 1 at the guest tuple annotation before
pytest. Browser-only variable naming correction leaves the provider branch
unchanged; full mypy then passed across 261 files. Initial log is retained.
Independent full source review found no remaining blocker and passed 133 focused
Python and all 48 frontend cases; frozen exact-tree review remains required.

Corrected normal aggregate returns exit 0: 2484 passed/302 explicit service skips
in 99.42 seconds, 48 React tests across eight files and mypy over 261 files, plus
all existing docs/format/lint/inventory/type/build gates. Two new SQL regressions
age authoritative contact/excerpt lifecycle deadlines after committed browser
evidence and verify recovery refuses without new acquisition or effects. They do
not claim to mutate the immutable observation expiry column.

Genuinely new-empty Python aggregate also returns exit 0: 2484 passed/302
explicit service skips in 107.48 seconds, 48 React and all aggregate gates. The
Python environment was confirmed absent before creation; shared package caches
and frontend dependencies were reused. The corrected normal/new-empty receipts
supersede earlier local pending notes. Independent full source and final expiry
test delta review are clear. Actual application target is 2786/no skips, with
controlled 41 plus all three separate operator journeys and all seven exact-head
workflows still required. No actual-service success is inferred from these local
runs.

## First actual head failure and bounded corrections

PR39 first head `3b94fe4ea53f3b85d85fbc972ec0504875d64ff7`, tree
`5472d3802c266e0e8c0a4f64b441dfe7a9528a97`, failed
[controlled run 39101590581](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39101590581).
Its 41 transport cases passed in 207.93s and original keyword operator passed;
operator aggregate was one passed/two failed in 121.57s. Owned topology/XML
cleanup was verified. This failed run is preserved, not rerun or treated as
acceptance.

The new tooltip guest pressed Enter on an unchecked native checkbox. That
implicitly submitted the form instead of toggling it, then the unchanged checked
assertion failed at url_plan before browser execution. The correction focuses
that checkbox and presses Space. A causal regression executes the actual guest
statements against native key semantics and rejects the original Enter mutation;
original provider/static activation and all success/time bounds remain unchanged.

The existing direct-XML case reached exports but a worker refused its envelope
organization before SQL/session lookup (results/broker.py). Independent source
analysis found five configured closure tasks registered with Celery's default
shared=True. Real Celery finalization of two differently configured apps, using
an inert Database constructor and no task/SQL/network execution, deterministically
bound both apps to the same callable for each name, guaranteeing five incorrect
bindings. The CI log does not expose closure identity or the stale organization;
the causal reproduction establishes the mechanism matching its envelope/config
refusal. This was a latent multi-app bug, not evidence of expanded authority.

The bounded correction registers all five tasks app-locally with shared=False.
Isolated simultaneous and sequential lifecycle regressions require each task's
own config/ledger and the execute task's own trusted factory. Envelope matching,
SQL authorization, source permissions and all tenant fences remain unchanged.
Corrected local/review/exact-tree and all seven actual gates are required.

Independent corrected-delta review passes 53 focused cases and confirms both
original mutations (shared registration and Enter checkbox activation) fail their
new regressions. The worker-focused suite passes 168 cases. The first corrected
normal aggregate stopped at Ruff before tests because single-file import
classification differed from the full aggregate target set; the standard full
Ruff invocation corrected that test-only spacing. Its exit-1 receipt is retained.

The first head's application run completed successfully with 2786 actual backend
cases/no skips in 724.09s, 48 React and verified XML cleanup. All 25 new SQL cases
executed. Six workflows passed; the controlled operator failure remains blocking.
All first-head runs reached terminal state before any corrected publication.

Corrected normal/new-empty aggregates both return exit 0: 2487 passed and 302
explicit service skips, 48 React tests and mypy over 262 files, plus all existing
local gates. The fresh Python environment was absent before creation; shared
package caches/frontend dependencies were reused. Independent corrected source
review is clear. Corrected actual application target is 2789/no skips; controlled
41 plus all three operator proofs and all seven own-head workflows remain required.

## Second controlled-head result and review-entry correction

Head `1230acab789d623b60d62ce4673e0851cd705fff`, tree
`2c4850b4be70d75dad09b5cc603981b844f36505`, passed 41 transport cases in
198.17s and both original keyword/direct-XML operator journeys in
[run 39102632181](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39102632181).
The new tooltip job reached completed but its review-list row assertion failed;
operator aggregate was two passed/one failed in 122.01s. Cleanup was verified.
This failed run is also preserved.

The actual pure browser observation and existing association mapper produce one
accepted explicit observed correspondence for Elena Park. Review queue defaults
to needs_review, so the copied XML journey selected a list that correctly excludes
that association. XML intentionally has different conservative mapping rules.
The browser-only correction opens Contacts (accepted default), then performs the
same evidence dialog, reason and Save review action. The host still requires its
durable review receipt. A causal regression binds real observation/mapping to the
actual guest navigation and UI default, rejecting the original Review queue
mutation. Association rules, human review and all timing/safety predicates remain
unchanged. Another corrected own-head acceptance is required.

Second-head application completed 2789 actual backend cases/no skips in 717.83s,
48 React and verified XML cleanup. All seven second-head runs are terminal:
six success and the preserved controlled review-entry failure.

Review-entry correction passes normal/new-empty aggregates with explicit exit 0:
2488 passed/302 service skips in 101.42s/112.09s, 48 React, mypy 262 files and all
local gates. The fresh Python environment was absent before creation; shared
caches/frontend dependencies were reused. Independent review passes 49 focused
cases and rejects the original navigation mutation. Actual own-head target is
2790/no skips, controlled 41/three operator cases and all seven workflows.

## Final actual acceptance

[PR39](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/39) final head
`2e90c6dcc686a8b354440669ea8e4422b586a9c7`, tree
`3fdc20880ebaf8914cce9760497c88a7ff6f1ecd`, completed all seven attempt-one
workflows. The tested GitHub merge commit
`9210f683270eaf243d01e9df367062a56747f545` has that exact tree and parents
accepted PR38 plus the final head.

- [Application](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39103717471): 2790 passed/no skips in 498.15s, 48 React, owned cleanup.
- [Controlled](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39103717443): 41 passed in 213.17s and all three operator cases in 133.27s; all proof markers and owned cleanup verified.
- [Browser](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39103717493), [static UI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39103717473), [parser](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39103717486), [packaging](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39103717506) and [docs](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39103717481): success, actual logs independently reviewed.

Independent exact-tree, final actual-evidence and factual-description review
passed. Public description readback matched. Earlier failed runs remain above;
no successful rerun erases them. This closes the scoped synthetic integration,
not real-source rights or production/deployment acceptance.

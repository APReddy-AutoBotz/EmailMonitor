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

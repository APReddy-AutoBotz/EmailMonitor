# Combined fixture operator validation

Based on accepted Draft PR39 head
`2e90c6dcc686a8b354440669ea8e4422b586a9c7`, tree
`3fdc20880ebaf8914cce9760497c88a7ff6f1ecd`.
[Runbook](../docs/60-combined-fixture-demonstration.md).

Independent design approved the existing-contract acceptance composition with a
separate topology/one fresh browser guest per operator case. All four mapped
associations are already accepted, so human review enters Contacts. Article and
association counts are separate. Accepted-contact crash/replay uses the existing
subprocess harness, never the threaded browser worker's process-exit hooks.

Initial candidate status (historical): implementation, normal/new-empty aggregates,
independent source/exact-tree review and all seven actual gates were pending.
Completed local receipts follow; own-head actual acceptance remains pending. No production or
live-source acceptance is inferred from this candidate.

## Development and local checks

Focused composition/discovery/protocol suites: 170 passed. Full Ruff lint/format,
mypy over 263 source files, shell syntax and diff checks passed. The separate
restart suite collected five cases and skipped them because disposable SQL
service URLs are absent; independent restart-source review passed.

The first aggregate invocation stopped before checks because uv's default cache
path was read-only (exit 2). The rerun uses the established writable shared cache;
no source or security setting was changed. Full results remain pending.

The first running aggregate ended with four failures, 2490 passed and 303 skips
in 106.89s. Three stale pure contract assertions still expected the former
single browser branch/three operator cases; their updates retain refusal of
missing receipts, skips and failing pytest. Independent review also caught all
three before publication. The unchanged DNS shared-deadline test observed one
query rather than two, with no HTTP call, under its existing 60ms total deadline
and 40ms per-question delay. Its isolated unchanged rerun passed in 2.14s. This
is preserved as an intermittent timing observation, not a proven cause or fix;
no DNS deadline or predicate is changed.

## Reviewed local aggregates

Corrected normal and genuinely new-empty Python aggregates both exited 0:
2497 passed / 303 explicit service skips in 124.61s and 131.75s, 48 React tests,
mypy 263 files, documentation/contracts, Ruff, inventory, frontend type/lint and
build. Fresh environment absence was verified before creation; shared uv cache
and existing frontend dependencies were reused. The earlier DNS failure remains
unresolved and preserved; both unchanged full reruns passed it.

Independent corrected source review passed, with 144 focused tests. Three stale
contract tests now include all four receipts and reject missing-combined and
stale-three-pass summaries. Required actual acceptance remains 2800 backend/no
skips, 41 controlled transport plus four operator cases and all seven workflows.

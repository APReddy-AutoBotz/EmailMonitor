# One-sample validation evidence

Scope: [one bounded Elsevier article evaluation](../docs/62-elsevier-one-sample-validation.md).
This is a candidate runner/control change, not a completed real-source result.
No real sample has been acquired or parsed by this implementation worker.

The dedicated runner reuses the accepted private admission harness, immutable
curated-image preparation, exact network-none parser protocol and owned resource
reconciliation. Its one fixed anonymous acquisition uses public DNS validation,
a pinned literal socket and system-CA hostname/SNI verification. The existing
seven synthetic workflows remain unchanged.

Initial synthetic tests passed 48 cases. Development lint/type corrections were
limited to formatting, test imports and explicit exception expectations. Final
focused results and independent review follow after the candidate is frozen.
Actual Docker/sample execution is unavailable locally and is not inferred from
pure tests. The dedicated initial-event attempt remains pending.

## Focused candidate checks

The completed focused suite passed 290 tests in 8.08s, including 51 new
synthetic-only runner tests plus existing private/XML/packaging regressions.
Full-scope mypy passed 268 files. Changed-source Ruff lint/format passed.
Documentation validation passed 80 documents and 374 local links, with existing
contracts/examples/traceability intact. No Docker or real-sample outcome was
inferred. Full normal/new-empty aggregates, independent exact-tree review and
actual own-head synthetic gates remain pending.


## Preliminary aggregates and cleanup-review correction

Before the cleanup correction, normal/new-empty aggregates exited 0 with 2606
passed/303 explicit service skips in 122.58s/125.24s, 48 React tests and mypy 268
files. These are preliminary receipts for the earlier candidate, not validation
of the corrected final tree.

Independent review identified that a temporary-directory context deletion error
or interruption could escape file removal while only Docker cleanup was verified.
The correction retains the owned temporary-directory reference and adds bounded
outer-finally removal retries plus an explicit filesystem-absence check before
Docker reconciliation. Either unresolved cleanup forces `cleanup_refused`.
The environment guard also rejects `SSLKEYLOGFILE` to prevent inherited TLS key
logging. New synthetic tests cover transient/persistent/silent deletion failure,
termination during deletion and cleanup deadline expiry, without real network.
Corrected aggregates and exact-tree review remain required.


Corrected focused receipt: 296 tests passed in 9.13s; the runner's 57 synthetic
cases also passed independently in 1.00s. Full-scope mypy passed all 268 files;
changed-source Ruff lint/format and documentation validation passed. A transient
test-only return-type annotation issue was corrected before this receipt. No real
sample acquisition, parser execution or publication occurred during the correction.

## Final local receipt

After the cleanup correction, normal and genuinely new-empty Python aggregates
both exit 0: 2612 passed/303 explicit service skips in 122.43s/124.31s, 48 React
tests, mypy 268 files and all existing checks. Fresh environment absence was
verified before creation; shared uv cache and frontend dependencies were reused.
Independent revised source review passes, including 57 runner tests in 1.07s.
No real sample execution is inferred. Exact-head actual synthetic target is
2915 backend tests without skips, all seven existing workflows, plus the separate
initial-event sample outcome. The actual outcome may report unsupported or partial
compatibility and does not establish extraction accuracy.

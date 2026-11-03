# One-sample affiliation diagnostic validation

Scope and exact control specification: [runbook64](../docs/64-one-sample-affiliation-diagnostic-plan.md).
This separately scoped partial EM-015 investigation reuses the reviewed PR43
fixed-counter guest without changing its source or parser association behavior.
It introduces an additional PR44 initial-event composer and new diagnostic-purpose
rights decision. PR42 acquisition controls remain unchanged.

## Prerequisite evidence

PR43 [draft](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/43), head
93f72166ea246b47f585bf278d681bff8dc2fe79, tree
dba3014ad4dc5250cdfe60a40a339aa0b876cfd2, passed all eight workflow conclusions.
[Application](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39359708212)
passed 3054 backend tests without skips and 48 React tests.
[Controlled isolation](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39359708322)
passed 41 transport, one original private admission, one new full synthetic
admission-to-container diagnostic and four operator tests with owned cleanup.
[Packaging](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39359708312)
passed two uncached builds and exact 35-module closure/inventory checks. The
[original one-shot job](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39359708321)
was skipped with no steps. These are synthetic diagnostic evidence, not evidence
of the real article's affiliation cause.

## Design review

Independent review found no blocking design finding after clarification that
existing affiliation nodes must be counted before attributing missing selection
to the reference gate. Direct textfn presence does not establish valid text or
intended attribution. The new explicit diagnostic-purpose decision, exact initial
event guards, original inspect validation plus image ownership, closed four-key
output and independently attempted file/Docker cleanup are mandatory.

## Implementation validation

The new workflow contract suite passed 51 tests, with 28 temporary synthetic
workflow mutations rejected. A combined workflow/existing focused run passed 247
in 3.01s. Changed-file Ruff and focused mypy passed after correcting an initial
format failure. Frontend typecheck/lint/build and 48 React tests passed.

Independent review reproduced a narrow signal-transition gap in the first runner
draft: interruption during cleanup alarm transitions could escape before Docker
reconciliation and leave the outer pre-resource refusal record. This was corrected
before publication: ordinary SIGINT/SIGTERM is deferred across both separately
bounded cleanup phases, transition failures cannot skip Docker reconciliation,
and unexpected outer failure conservatively reports cleanup_refused. A preliminary mypy loop-variable
issue was also identified. Initial local uv calls encountered the read-only default
cache; subsequent setup uses the existing writable cache. These preliminary
failures are retained rather than represented as successful final validation.

Final local validation:

- 130 new synthetic runner tests; implementer combined regression: 326 passed.
- Independent combined source-boundary review: 515 passed, including all 181 new
  runner/workflow tests, transition injections and actual synthetic SIGTERM in
  each cleanup phase. No remaining source-review blocker.
- Normal Python aggregate: 2932 passed, 303 explicit service-dependent skips,
  113.28s, exit 0.
- Verified previously absent new-empty Python environment: 2932 passed,
  303 explicit service-dependent skips, 117.72s, exit 0. Locked offline setup reused
  the existing package cache; this is not a fresh-download claim.
- Whole Ruff lint/format: 282 files; whole strict mypy: 280 files; all passed.
- Frontend typecheck/lint/build and all 48 React tests passed.
- Inventory: 64 Python and 159 JavaScript locked packages. Docs/contracts/
  traceability/fixtures and git diff whitespace checks passed.

All local tests use authored synthetic bytes and mocked acquisition. No real
source was acquired locally. Docker is absent locally, so actual isolation and
the real initial-event outcome remain separate exact-head CI evidence. Independent
frozen-tree review and remote tree/base/allocation checks precede publication.
The frozen identity and later CI receipts belong in the draft description without
mutating the reviewed source tree.

## Actual attempt

Not started. A failed or ambiguous attempt will be retained without automatic
retry, reopening, alternate source or another acquisition. Fixed structure counts
cannot establish accuracy, completeness, identity or acceptable association.
There is no migration, deployment, merge, API activation or persistent credential.

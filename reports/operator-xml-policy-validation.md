# Operator synthetic XML policy validation

## Baseline and scope

Accepted Draft [PR36](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/36) head `2ec9db1c012c10e416fab6f21ab81a09e017138d`, tree `2b0e8ebd04c33c85aefe49db2a7b063e242ee776`, passed all seven corrected-head workflows with 2679 actual backend cases/no skips, 31 React cases and actual controlled operator/service acceptance. Independent final source, evidence and published-description review passed. Its original caller-queue fixture failure remains preserved in that PR; the unrelated intermittent channel timing observation remains unexplained.

This EM-003/EM-012 slice closes the existing operator policy setup gap described in [runbook58](../docs/58-operator-synthetic-policy-profiles.md). It changes the UI and acceptance coverage, without new acquisition permissions by default or production activation.

## Candidate gates

Initial frontend checks pass: typecheck, lint, 38 cases across six files and production build. Focused SQL governance cases are explicitly skipped locally because disposable PostgreSQL URLs are absent. Normal and genuinely new-empty Python aggregates, independent source/exact-tree review and all seven actual own-head workflows remain required. Actual application acceptance must include all nine new SQL cases; controlled acceptance must prove the policy was proposed and approved through the keyboard UI before the existing provider pipeline.

No deployment, merge, live-source or license clearance is claimed.

## Preserved initial failure and review correction

The first focused run recorded 26 passed, nine explicit SQL skips and one failure; the first aggregate recorded 2410 passed, 277 explicit service skips and the same one failure in 97.72s (exit 1). The existing provider locator regression assumed New extraction was the second statement; the new preceding source-review step invalidated that positional assumption. The correction locates exactly one New extraction activation and retains the original scoped-locator evaluation, without changing UI behavior or deadlines.

Independent review also required waiting for the tenant-B loaded no-policy/management-denied state before asserting controls absent, avoiding a vacuous loading-state pass. Independent frontend review passed 38 cases/typecheck/lint; corrected aggregate and actual gates remain pending.

Corrected normal/new-empty Python aggregates both return exit 0: 2411 passed and 277 explicit service skips, 38 React cases and mypy over 253 files; all existing docs/lint/format/inventory/type/build gates pass. The new-empty Python environment was absent before creation; shared package caches and frontend dependencies are reused. Independent source review and 14 focused provider-worker cases pass. Actual 2688/no-skip application and all seven own-head workflows remain required.

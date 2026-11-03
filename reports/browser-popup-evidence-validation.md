# Bounded popup failure evidence

## Accepted baseline and observed failure

Accepted Draft PR30 head `27e6ae133ae29c2c6b13dd4dceba4122eee677fc` matches local `bbf85b915ae06f83b6f09cd5fe004aa65cbaa49c` and tree `81998daa269506ec208765a5b8d0df589d7a3447`. All seven latest workflows passed: application2203/no skips/no pytest warning summary in647.26s,31 React; controlled41 in175.13s plus actual provider operator1 in42.94s. The final PR body preserves all receipts and independent acceptance review.

Browser run38923338052 attempt1/job117048527277 failed after boundary_ready and 11 completed mediated exchanges: popup_count0/popup_closedfalse, download_count1/download_cancelledtrue. Because popup_count increments before child.close, slow close cannot explain zero events. Listener registration preceded navigation/click. Two denied document exchanges are consistent with iframe plus popup but existing logs do not identify their paths. The identical guest/fixture passed in controlled transport and one unchanged same-head diagnostic repeat (attempt2/job117051272182). No source, deadline, predicate or isolation change preceded that repeat; it does not prove a cause fix.

## Mechanism hypothesis and local limits

Pinned Playwright1.63 Chromium initialization waits for a first noninitial navigation commit when an initial target URL is empty or `:`. New-page reporting and the opener popup event follow initialization. An aborted navigation updates failed-navigation state without settling that particular initialization promise. A source-level probe of actual bundled methods with mocked CDP confirms that branch, while initial about:blank resolves immediately. This supports an unreported-target hypothesis, not the historical CI cause.

An attempted sandbox-enabled local Chromium154 launch failed before fixture execution because process_singleton socket creation was not permitted; no retry, escalation, bypass flag or security-setting change followed. Local browser version also differs from CI153, so no equivalent actual-browser reproduction is claimed. No local Docker is available.

## Diagnostic-only change

The existing browser guest counts exact synthetic popup-route observation and completed abort, and counts context.page events registered after the initial owned page. On the unchanged three-second popup/download completion failure, it captures existing flags/counts and context.pages count before awaiting any diagnostic. A single one-second budget covers two read-only CDP calls: Target.getTargetInfo verifies the current target is the exact fixed synthetic fixture page; Target.getTargets requests page targets only. At most16 returned entries are processed. Only children whose openerId equals that verified parent contribute fixed URL categories: synthetic_popup, blank, initial, error_document or other. No title, URL, target/frame ID, exception message or arbitrary metadata is emitted.

Malformed/oversize/unverified/timeout/unavailable evidence uses fixed categories. Output counters are capped16 with a saturation flag. The original failure always remains a failure, including if a callback arrives while diagnostics are collected. This does not increase the existing three-second success allowance, host deadline, request budget, network permission or sandbox capability. No CDP discovery subscription or browser mutation is added. Normal successful execution performs no CDP evidence snapshot.

## Validation required

31 pure cases cover parent/child scope, hostile unknown fields and exception strings, malformed/oversize targets, strict observations, bounded counters, a single shared timeout and sticky failure despite late completion. Existing callback-completion tests remain unchanged. Initial focused combined checks passed25 cases in0.44s; an authoring mypy private-module-reference issue was corrected before final aggregate checks.

Independent source review, normal and genuinely new-empty Python aggregates and all seven exact-head CI gates remain required. Expected actual application inventory is2234/no skips, plus31 React, original controlled41 and separate actual provider1. Successful CI would preserve actual isolation/operator acceptance; it would not exercise this failure-only snapshot unless the relevant failure recurs, nor resolve the popup-event cause. No migration, dependency, live-source grant, real credential, merge or deployment change.

Independent source review found that malformed target type/opener fields could otherwise appear as observed zero children. Strict bounded type/opener validation and seven additional malformed/valid-parent regressions correct that diagnostic ambiguity. That review stage passed32 cases in0.50s. A further fail-closed scope guard validates the parent before listing targets, with one regression proving an unverified parent performs no target listing. Final focused combination passes33 cases in0.58s; independent review passes33 in0.55s. This does not change browser acceptance or routing.

## Final local candidate checks

Final scoped normal aggregate exited0:1974 passed/260 explicit service-container skips in75.91s,31 React and all static/docs/contracts/inventory/build gates. A genuinely absent `/tmp/emailmonitor-popup-scoped-empty-tcJdg9/venv` was verified before locked synchronization; the same complete aggregate exited0 with1974/260 in76.03s,31 React and all gates. Logs `/tmp/em-popup-scoped-normal.log` and `/tmp/em-popup-scoped-empty.log`. Download cache and frozen frontend installation were reused; no fresh frontend install claim. Earlier aggregates predate the final pre-query guard and are not the final candidate receipts.

Independent source review cleared the corrected logic and passed33 focused cases in0.55s. Final immutable-tree review and all seven actual own-head gates remain required. Neither local skip nor mocked CDP case proves actual failure-path CDP behavior or resolves the intermittent popup cause.

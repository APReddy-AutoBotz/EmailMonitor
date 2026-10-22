# Retained job outcome investigation — candidate evidence

## Scope and provenance

EM-010/011/012 UI-only investigation builds on accepted unmerged Draft PR48 head
`2ee0450e509bdc5eb99df41dcb275133bbaa4bc3`, tree
`38d6a74a2a4e18611a91aac33ae4fcc03890f2e4`. That draft remains unchanged. A separate
clean dependent checkout was created; the remote parent commit was reconstructed
from verified Git metadata and its exact content-addressed hash was checked.
Prior writer ownership was released, and no active hosted run was present before
work began. [Scope and limits](../docs/68-retained-job-outcome-investigation.md).

## Review and test plan

Independent design review conditionally approved reuse of the existing outcome
and quality GET endpoints. It required fail-closed scoped page rendering, honest
whole-job/page counters, independent quality visibility, no investigation writes,
and dynamic keyboard/stale-response plus actual runtime-role SQL tests.

Local normal/fresh aggregate gates, final source/exact-tree review and hosted
actual SQL/operator/inherited acceptance are pending. No result in this candidate
record should be read as successful execution of those gates.

## Evidence limits

The fixed synthetic SQL profile restricts each job to a small closed set of
article URLs. A browser-authored single-job dataset greater than 100 rows proves
UI pagination, while actual SQL pagination across authored jobs and separate
job-scoped tests prove existing endpoint behavior. Neither implies real publisher
certification or production readiness. Existing SQL retention, tenant, revocation,
privacy and deletion checks remain the authority for returned data.

No migration, persistent access expansion, deployment, real source acquisition,
production credential, or contact publication is included.

## Initial source review correction

Independent source review identified that request-keyed pagination controls would
lose keyboard focus when replaced. Explicit page-navigation heading focus and
pre-removal focused-descendant cleanup were added. Frontend typecheck/lint/build
and 91 tests passed after this correction. Actual dynamic browser acceptance is
still required; static render tests do not execute hook effects or dialog focus.

## First normal aggregate correction

The first complete normal backend gate reported 4,809 passed, 397 explicit
infrastructure skips and one failure. The existing keyboard-only harness guard
correctly rejected a new programmatic button click used to force modal revision
invalidation. The guard is preserved. The acceptance scenario now uses
a one-shot authored SSE GET failure through the actual stream invalidation path.
The keyboard-only configuration/protocol/browser-contract checks passed 147 tests;
normal/fresh gates will be rerun on the correction.
This failure was in test interaction design, not a successful browser receipt.

## First hosted candidate

Remote candidate `d325ea54d11bd1fbbc74cf87d3ba8f4813d6bbcb`, tree
`fbf0ae9ae2fa795dc3e480f8312b1a1152ffdcf5`, passed both corrected normal/fresh
local aggregates (4,810 backend passed, 397 infrastructure skips, 91 React tests).
Independent source review approved that exact tree. Hosted operator run
[39776121345](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39776121345)
failed with an AssertionError at the broad `url_worker` stage; the existing fixed
output did not identify the particular new assertion. This is a failed actual
receipt, not a successful keyboard proof. Remaining protected runs were allowed
to finish; no run was interrupted. Bounded categorical diagnostics are being
added to identify the new investigation substep without exposing page data.

Diagnostic review caught that extra emitted stage frames would exceed the existing
32-frame cap. The correction preserves the emitted stages, cap and host equality
check, and adds only a closed optional `outcome_phase` on failures at `url_worker`.
A local aggregate overlapped the diagnostic revision and failed its new phase
consistency assertion (4,810 passed, 397 skipped, one failed); that non-frozen run
is invalidated and is not acceptance evidence. Fresh serial gates are required
on the corrected frozen tree. Focused corrected protocol checks passed 149 tests.

## Native modal traversal acceptance correction

Independent review identified an overconstraint in the authored modal test:
requiring all six consecutive Tab presses to leave the active element inside the
dialog also requires native focus navigation to wrap inside the document.
The [HTML sequential-focus-navigation standard](https://html.spec.whatwg.org/multipage/interaction.html#sequential-focus-navigation)
allows navigation to browser UI at a document boundary. The test now verifies the
precise Close → Tab → Refresh → Shift+Tab → Close sequence, with read-only `:modal`
checks before and after. Escape, opener restoration, stream-invalidation cleanup,
closed failure phases and keyboard/security guards remain unchanged.

This is a standards-based acceptance correction, not a confirmed explanation of
the original hosted AssertionError. Its exact failing assertion remains unknown.
The prior diagnostic-tree normal aggregate (4,812 passed, 397 infrastructure skips,
91 React tests) is superseded for this patch; fresh had not run. Full normal/fresh
and hosted actual browser checks must run on the corrected frozen tree.

## Actual SQL fixture corrections

The first hosted backend receipt completed with 5,205 passed, two failed and no
skips (909 seconds). Both failures were in the added investigation fixtures:

- The 104-outcome traversal inherited the generic request fixture's one-article,
  one-page budget, so the actual service correctly returned one capped outcome.
  Its request now explicitly budgets four articles and two pages, retaining the
  closed authored source routes and 26-job traversal. A pure request check prevents
  accidental fallback to the smaller generic defaults.
- The blocked fixture tried to report `source_policy_changed` while policy remained
  approved. SQL correctly refused with `POLICY_DENIAL_REQUIRED`. The corrected
  fixture claims actual work, suspends the existing policy through its authorized
  API, verifies runtime read denial, and finishes the same lease as policy-blocked.
  An existing owner test connection reads the durable blocked/no-batch row; runtime
  Results must remain denied. No policy reactivation, new version, grant or SQL
  weakening is introduced. Visible blocked-row rendering remains separately
  browser-authored evidence, not a claim of current access to suspended-source data.

The subsequent native-modal tree's normal aggregate passed 4,813 tests with 397
infrastructure skips and 91 React tests; fresh had not run. This SQL-fixture patch
supersedes that tree for acceptance. Full normal/fresh and hosted actual SQL/browser
receipts remain required; these fixture corrections alone are not execution proof.

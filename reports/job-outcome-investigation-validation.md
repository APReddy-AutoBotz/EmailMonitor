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

## Scoped contact selector correction

The next hosted operator receipt failed with `AssertionError` in the closed
`outcomes_scoped_contacts` phase. Earlier investigation phases had completed on
that run, but the full operator journey did not pass.

Source review established a deterministic harness selector mismatch: pinned
Playwright's exact label matcher reads the full implicit label text, including
nested select option text. `Association state` alone therefore cannot exactly
match the label wrapping the state select and all its options. Both added state
assertions now use the existing harness's anchored label-prefix regex pattern.
They still require one matching control and exact `accepted` / `needs_review`
values; no `.first`/`.nth` ambiguity suppression is added. A pure regression keeps
that selector/value pairing. No production UI defect is established by this
failure, and no production code or diagnostic/security guard changes are made.

The previous frozen tree's normal/fresh results (4,814 passed, 397 infrastructure
skips and 91 React tests per run) do not validate this new selector patch. Full
serial normal/fresh and hosted actual checks must be rerun on its exact tree.

## Late-organization hold readiness correction

Read-only continuation review found a scheduling hazard after returning from the
review screen to Jobs: the test armed its response hold before the remounted first
page was confirmed ready. A pending initial-page response could then be held while
the keyboard helper waited for Next to become enabled. This is a source-identified
race, not an observed hosted failure or an established production defect.

The test now positively verifies Page 1 and an enabled Next control before arming
the late-organization hold. Both late-job and late-organization holds target only
offset 25 and assert that exact held offset before changing scope. Initial-page
loads are not delayed accidentally. The existing hold deadlines, keyboard controls,
current-scope checks and stale-response assertions remain unchanged. A pure order
regression preserves these preconditions. The preceding selector tree's two local
aggregates (4,815 passed, 397 infrastructure skips and 91 React tests each) are
superseded; full normal/fresh and hosted checks are required on this corrected tree.


## Actual operator success and bounded backend capacity failure

The preceding remote candidate `025cbbde23103db44426b6d26d8b5eb6ea47932f`,
source tree `422178b904c0acdc0b4b4447749ab0c97ff7faef`, passed normal/fresh local
aggregates with 4,816 backend passes, 397 explicit infrastructure skips and 91
React passes per run. Actual operator run
[39782944387](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39782944387)
passed its complete keyboard journey (one test, 83.91 seconds).

Installed-service run
[39782944449](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39782944449)
initially passed 12 broker, one HTTPS and three XML cases, but its XML keyword
journey timed out at `export_preview`. One unchanged exact-job retry,
`119844693785`, then passed all 12 broker, one HTTPS and four XML cases. This is a
successful bounded retry, not proof of the original timeout's cause.

Application run
[39782944707](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39782944707)
reached the unchanged 1200-second wrapper limit twice: original job `119838602014`
refused after 1200.412 seconds at 99%; unchanged retry `119850676804` refused after
1200.241 seconds at 92%. Neither produced a final pytest summary. Both verified
owned cleanup. All runs were terminal before this change. These remain failed
backend receipts. The earlier `c2d823` candidate had completed 5,211 tests without
skips in 1065.35 seconds; the new 104-outcome test alone was observed at 163–222
seconds. This establishes bounded headroom pressure, not a reason to raise limits
or weaken test/security requirements.

## Closed hosted SQL-test separation candidate

Only `test_job_outcome_investigation_tenant.py::test_actual_more_than_100_outcomes_have_no_omissions_or_duplicates`
moves into a separate mandatory `outcome_sql` hosted job. Its fixture, 26 jobs,
104 outcomes and assertions are unchanged. The backend job runs every other test;
normal/fresh local `check.sh` and its `backend` phase remain full and unfiltered.
Both hosted jobs retain the same actual SQL roles, broker/restore/XML requirements,
owned cleanup, 1200-second wrapper/consumer limits and 25-minute job ceiling.

Each closed runner verifies a duplicate-free collection multiset, exact disjoint
partition union, unchanged final selected/deselected collections, all assigned
setup/call/teardown passes, zero skips and unchanged source/configuration. Bounded
job outputs bind those manifests and execution counts to the clean source tree
and configuration/lock digest. The mandatory `scaffold` join requires both SQL
jobs and static/frontend success, matching complete receipts and its own matching
checkout. No missing receipt, skipped/cancelled/failed job or cleanup failure can
satisfy that join. New ordinary tests automatically enter the complete complement;
a missing or renamed dedicated node fails closed. Ambient pytest selectors and
plugins are refused; the already-installed locked AnyIO plugin is explicit.

Actual collection comparison uncovered one existing nondeterministic node name:
the uppercase-UUID parameter in `test_progress_envelope.py`. Only its pytest
parameter display ID is stabilized; its random value and refusal assertion remain
unchanged. No production code, migration, grant, dependency or 104-outcome fixture
change is included. Focused tests, normal/fresh and actual hosted acceptance are
separate evidence; a collection-only check cannot establish runtime SQL success.

The first focused partition-contract run found one no-selector contract failure
(368 passed, one failed): an extra synthetic `-k` expression that happened to match
the entire assigned complement did not alter its collection. The runner now also
requires the exact fixed pytest invocation, so even a no-op selector refuses.
The corrected final focused command covering application phases, partition proof,
XML packaging, preserved diagnostic-workflow boundaries and progress envelopes
passed 393 tests without skips in 12.74 seconds. `scripts/check.sh static` passed
documentation/contracts, full Python lint/format and strict type checks.

Two independent real full collections under the exact fixed configuration and
explicit AnyIO plugin collected 5,418 nodes. They matched the normal full
collection after canonicalizing only its root-relative display paths. Both
partition multisets were exact: 5,417 backend nodes and the one unchanged SQL
node, no intersection or duplicates. The canonical full-manifest SHA-256 was
`e3e62de944caae638b95901a457223f1a4fd72735ae00e94ad9a7c9aff2ae556`.
These are collection and focused local proofs only. Full serial normal/fresh,
independent exact-tree review and new actual hosted receipts remain pending.

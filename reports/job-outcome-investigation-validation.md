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

# Contextual suppression of a retained contact

Draft implementation; hosted acceptance remains incomplete. This connects the
existing EM-014 privacy suppression action to the currently readable contact in
EM-012's evidence dialog. It introduces no new suppression matching rule, source
permission, migration, acquisition route or production activation.

Only the existing `source.policy.manage` capability exposes the action (owner or
data steward). Review authority alone is insufficient. An explicit privacy-request
or source-restriction reason is required. Confirmation states that matching-address
suppression applies throughout the organization, across jobs, and is not an
undoable review rejection. Withdrawal does not restore previously fenced records.

The evidence dialog closes before confirmation. On confirmation the UI rereads the
exact contact and requires unchanged organization, batch, association, revision and
retained address before invoking the existing API. The retained address is sent
unchanged; normalization belongs to the server's existing privacy grammar.
Unavailable/stale data, scope changes, read/write refusals and uncertain receipts
must not report success or automatically retry. Server revalidation remains the
authority; the client recheck is not an authorization token.

Acceptance inventory: explicit confirmation/cancel, current-row binding, capability
restrictions, organization/session changes and failure handling in frontend tests;
actual PostgreSQL API checks for owner/data-steward versus admin/operator/reviewer/
viewer, CSRF and cross-tenant refusal, and resulting contact visibility; existing
lifecycle tests for export fencing and non-resurrection; an authored installed
keyboard journey that cancels first, then explicitly confirms suppression after
other retained-data journeys finish. Authored or skipped cases are not executed
acceptance. Full normal/fresh local checks precede Draft publication; genuine
hosted checks remain required before acceptance. No merge, deployment or live-source claim follows from local proof.

## Current integration boundary

The product-only suppression increment is integrated locally on the retained-job
timing baseline. Earlier suppression diagnostic commits remain separate. This
candidate preserves timing presentation, current outcome replay readiness and
existing fixed guest diagnostics. It changes no migration, authority predicate,
source access or matching rule. Prior branch receipts are historical evidence;
current normal/fresh, actual SQL and genuine hosted browser acceptance must be
reported independently for each tested candidate.

## Validation checkpoint

The product candidate passed normal and independent fresh local backend checks
(6,292 passed, 578 explicit infrastructure skips each), 200 frontend tests each,
static checks and a fresh web build. Separate disposable PostgreSQL runs each
passed eight suppression role/refusal and lifecycle cases with zero skips and
verified owned cleanup. Draft #60 preserves Draft #59 as its base.

Its first operator workflow failed before reaching suppression, at the existing
late-organization outcome pagination keyboard attempt. The fixed snapshot showed
an enabled, non-inert target tab stop, focused document and another active button;
it did not establish a cause. Existing passive attempt observations are now
summarized as Tab count, truncation and count/first-Tab position for heading focus,
target detachment and target replacement. No event arrays, values or payloads are
exported. A truncated trace cannot prove absence beyond its capture cap. Original
keyboard sequence, deadline, failure and cleanup remain unchanged. This diagnostic
is not a runtime repair; prior failures remain unresolved.

A later operator run reached the broad read-only stage and timed out; this alone
could not locate its final operation. Locked Playwright selector-engine tests on
authored nodes establish two independent harness defects: exact wrapping-select
label matching includes option text, and exact address-cell text matching includes
the normalized-address annotation. The journey now uses the established anchored
label pattern and an escaped exact-address boundary before that annotation. It
also requires a rendered current table/empty result before checking absence.
The regression rejects prefixed and longer addresses. A separate fixed suppression
stage distinguishes this journey from the preceding read-only checks. No authority,
keyboard action, limit or runtime behavior changes. These local selector proofs
are not browser acceptance or proof of the historical timeout's exact operation.

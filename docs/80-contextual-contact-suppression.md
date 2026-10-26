# Contextual suppression of a retained contact

Local implementation in progress; not published or accepted. This connects the
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
acceptance. Full normal/fresh and genuine installed checks remain required before
publication. No merge, deployment or live-source claim follows from local proof.

## Current integration boundary

The product-only suppression increment is integrated locally on the retained-job
timing baseline. Earlier suppression diagnostic commits remain separate. This
candidate preserves timing presentation, current outcome replay readiness and
existing fixed guest diagnostics. It changes no migration, authority predicate,
source access or matching rule. Prior branch receipts are historical evidence;
current normal/fresh, actual SQL and genuine hosted browser acceptance must be
reported independently before publication or acceptance.

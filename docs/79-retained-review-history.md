# Recorded review history in the evidence dialog

FR-020 / EM-009 and EM-012 / UX03: display the existing versioned review
records beside the selected association's evidence. This is read-only UI over
`GET /organizations/{organization_id}/association-batches/{batch_id}/reviews`.
No backend authorization, response contract, review write, migration, grant,
export or replay behavior changes.

The existing response is the earliest 100 batch records in server order
(`created_at,id`). The panel filters that bounded response to the selected
association. It displays recorded action, expected association revision, actor
identifier, reason and a timestamp using the configured timezone. It does not
infer the resulting revision, actor name, current acceptance or missing decisions.
At 100 batch rows it warns that later decisions, including decisions for the
selected association, may be absent. An empty selected window never means
"never reviewed". No pagination or complete-audit claim is introduced.

History is requested only while the exact selected contact is currently readable.
Loading, failed, stale, mismatched organization/batch/association or closed-session
state hides old decisions. Organization, batch, association and refresh identity
changes remount the panel; the shared request hook aborts and ignores obsolete
responses. History reasons remain escaped text. A keyboard-operable disclosure
shows the loaded decisions. Existing review actions and current source, tenant,
suppression, deletion and retention rules remain authoritative.

Acceptance inventory includes render cases for multiple associations, empty and
capped windows, unavailable/stale responses, explicit zones, unknown timestamps
and escaped reasons; current-contact identity checks; distinct refresh identities;
actual PostgreSQL viewer read, cross-tenant/missing batch refusal, stale review
revision preservation, current policy/session/suppression/deletion/retention
refusal and final visibility refusal; and an authored connected keyboard
save/reopen/history journey. SQL or installed tests skipped locally remain
unexecuted until the unchanged genuine hosted gates pass.

This slice does not implement unmerge, source attachment or observation reuse,
and does not claim complete FR-020 or release acceptance. Rolling back the UI
requires no database change. Final formal review remains a separate release gate.

The nine new history SQL cases are explicitly assigned to the existing outcome-SQL
partition. Aggregate hosted timing showed the prior backend gate used 1,176 of
1,200 seconds and the first history backend attempt ended at 1,199 seconds, while
outcome SQL finished in about 826 seconds. This bounded scheduling correction
preserves all collected tests, exact disjoint inventory, source-tree binding,
zero-skip receipts and unchanged deadlines. It does not identify the assertion
behind the separate installed XML failure or establish a causal runtime repair.

Actual local PostgreSQL reproduction established that reducing excerpt or contact
retention returns an empty history list through current RLS, while the selected
contact changes from readable to HTTP 404. The singular quality/metadata views
raise refusal instead. The history retention tests assert the existing distinct
contracts explicitly: service/API release no decisions and contact access refuses.
No runtime predicate or retention behavior is changed. This corrects a new test's
exception assumption; it does not explain the separate backend budget failure.

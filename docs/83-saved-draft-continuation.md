# Saved draft continuation

FR-006/021/025 and UX03 / EM-012 require explicit plan review and job controls.
Previously, leaving the new-extraction wizard left an existing draft readable but
without a workspace plan/start control. This slice uses the existing plan and
start APIs for that same saved job; it does not recreate or edit its request.

Only current source-acquisition capability and a readable extraction draft permit
planning. Reread its revision/generation/state before planning. Bind the returned
persisted plan to the current organization, job and generation, then reread the
draft. Unsupported/refinement responses never offer launch. Explicit launch
rereads again and requires the same planned revision/generation/state. The server
continues to enforce current policy, quotas, retention and lifecycle at commit.
One plan closure submits launch at most once, including concurrent clicks; uncertain
submission is not automatically retried. Scope-owned UI state cannot carry a plan
or late response into another session, organization or job.

No backend, migration, grant, source permission, credential or network change is
required. Current fixture limitations remain visible; no live acquisition is
enabled. Local tests cover binding, stale/refused/closed state, unsupported plans,
post-plan revision, duplicate submission and unknown outcomes. The authored hosted
keyboard journey leaves and reopens the exact saved draft before explicit plan
review and launch, then retains its existing lifecycle/review/export assertions.
Actual hosted SQL/browser execution is a separate gate, not implied by local tests.

This candidate is based on PR60, independently of the unresolved PR61 installed
XML failure. It does not claim to repair historical XML or assembly-probe failures.

The saved-plan component must remain outside the job-loading child boundary.
Successful actions refresh the job resource; its loading state removes those
children. Keeping the component mounted preserves the reviewed plan while current
resource checks still disable launch until the refreshed draft matches. A
structural regression rejects the original nesting; behavioral tests retain all
scope, authority, revision and single-submission checks. Hosted keyboard execution
remains required to establish the complete interaction.

The corrected hosted journey passed saved-draft continuation, then failed at the
later article-presence Next-page keyboard activation. That exact activation now
uses the existing passive same-attempt trace to distinguish target replacement
and heading-focus events. It retains the target, keyboard sequence, Tab cap,
deadlines and original failure. Fixed categories are diagnostic evidence, not a
claim that the historical failure is repaired.

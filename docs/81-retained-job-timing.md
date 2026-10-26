# Retained queue-to-terminal job timing

NFR-017 / FR-021, EM-010/012: a read-only elapsed interval for the current authorized
extraction job, using existing durable execution events. This is a partial metrics
slice, not worker CPU, review effort, HTTP/browser/PDF usage, billing or a latency
acceptance claim.

`GET /organizations/{org}/jobs/{job}/timing` uses the existing fixture-only route,
READ_ORGANIZATION capability, tenant RLS and execution read fence before and after
projection. It neither creates execution authority nor changes policy, grants,
retention, lifecycle, source access or stored events. No migration is introduced.
The additive response has a separate versioned contract; existing progress and
stream contracts are unchanged. Removing the route/panel rolls back this slice
without data conversion or event changes.

For a terminal job, use the first job.queued event by sequence and the latest
matching terminal event (job.cancelled for cancellation, job.finished otherwise).
Require ordered sequences, aware nondecreasing timestamps and a terminal event
revision matching the current job revision. Recheck revision/generation before
returning. Missing/inconsistent events yield unknown, never a zero estimate.
Nonterminal jobs do not report a completed interval. Waiting and pauses are
included; resume does not reset the start. Retry continuations have separate job
intervals and do not rewrite the original.

The job panel displays both recorded timestamps in the explicit organization
timezone and elapsed seconds. Current progress identity, revision, generation and
state must agree; stale, loading, refused, mismatched or closed-scope reads hide
previous values. No ticking client estimate or date inference is added.

Acceptance: projection/schema and production-refusal tests; actual SQL terminal,
pause/resume/cancel, retry/replay, tenant, revoked policy/membership, offboarding
and retention-expiry checks; UI unknown/stale/identity/revision cases; authored
keyboard lifecycle assertions in the unchanged hosted operator journey. Mocked,
skipped or merely authored cases are not actual SQL/installed acceptance. Normal,
independent fresh and hosted gates must be reported separately.

Test-only bounded import and process-exit diagnostics are carried independently
from the unpublished suppression feature. Prior callback startup and post-assertion
refusal timeouts remain unexplained. A later passing sample is not a causal fix.

Installed acceptance also emits a closed host-stage label into its explicitly
opted-in workflow output. A separate named metadata step exposes that label even
when the original pytest step fails. It carries no exception text, identifiers,
URLs or payloads; preserves the first failed stage through cleanup; and leaves
all existing assertions, guards, deadlines and cleanup actions unchanged. A
fixture/setup failure before the test body reports unavailable rather than an
invented stage. This is future diagnostic evidence, not a repair or a substitute
for installed acceptance. Browser execution and its owned cleanup share one host
label; that label alone does not identify a browser assertion or root cause.

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

The backend wrapper can additionally opt into fixed outcome metadata: normal
completion, test failure, consumer exit/signal/deadline, or wrapper signal/deadline.
Numeric active/completed/first-failed/total test ordinals come from a parent-owned
bounded temporary progress file; no test names or output are exported. The
metadata never supplies a partition receipt or changes its fail-closed join.
The wrapper alarm, consumer wait, exit/refusal behavior, complete test inventory
and owned cleanup remain unchanged. Missing diagnostics are not success evidence.

The hosted wrapper deadline was observed on the diagnostic head after 6,403 of
6,593 backend tests completed; the active case was the XML worker import-closure
check. An earlier workflow snapshot assertion also failed independently. Its
original digest stays pinned, with only the exact diagnostic metadata normalized.
The seven timing/current-authority SQL cases are now assigned to the existing
SQL partition, whose measured hosted step had 435 seconds of wrapper headroom.
Those seven cases previously took 24–70 seconds in actual local PostgreSQL runs;
that local timing is not a hosted guarantee. All seven are explicitly enumerated,
required exactly once, and joined against the same full inventory and tree.
No test, assertion, timeout, migration or authority rule is removed or relaxed.

Future operator and installed guest runs expose fixed build/create/validation,
conversation and exact owned-cleanup stages in workflow metadata. Only validated
guest stage/error/reason enums are included; no assertion text, stderr, API
statuses, payloads or identifiers are copied. The first failure remains visible
if another journey in the same pytest step later succeeds. Original exceptions,
exit status, genuine-CI guards, guest restrictions and cleanup operations remain
unchanged. This provides diagnostic evidence, not a runtime repair; a passing
later run cannot explain earlier failures.

Installed login failures additionally expose only the existing validated login
subphase enum. Missing subphase remains `none`; no session values or navigation
targets are reported. This separates readiness, activation, redirect, callback
and organization-selection waits without changing the shared ten-second login
budget or treating a later passing journey as a repair.

For keyboard exhaustion, metadata also includes the existing validated outcome
subphase and fixed focus categories: active kind, target control kind and active
control kind. Eight flags encode target focused, document focused, modal open,
target disabled, target in dialog, active in target dialog, target inert and
target tab stop, in that order (`1` true, `0` false, `u` unknown). Missing and
unavailable snapshots remain distinct. No DOM text, identities, arbitrary
labels or attempt-event payloads are exported. The original 100-Tab sequence,
visibility/enabled waits and failure remain unchanged.

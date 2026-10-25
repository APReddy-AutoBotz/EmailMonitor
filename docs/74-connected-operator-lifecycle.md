# Connected synthetic operator lifecycle acceptance

FR-021/022/025/026, NFR-006/008/011 and EM-005/010/012: connect existing
pause/resume, confirmed cancellation and eligible continuation to retained
review/export and durable broker recovery. This is acceptance wiring, not a new
source, permission, migration or lifecycle policy.

The keyboard journey uses the existing network-isolated operator browser and
actual API/database. It confirms cancellation with retained partial results,
checks that cancellation alone does not permit retry, reviews retained evidence
and explicitly previews/creates the retained selection export. A separate
exhausted-transient fixture creates an auditable continuation. A held real retry
response is released after organization switch; it must not navigate the new
organization into the old job. Returning and repeating retry must select the
same continuation, not create another.

Actual PostgreSQL cases preserve original terminal state and observation rows,
prove failed-work-only selection, revision conflict, pause/cancel generation
fences and source/session/tenant/viewer refusal. Cancelled retained results still
require current authority at review, preview, snapshot and download. Both CSV and
XLSX membership are checked. Pause/cancel service acknowledgement is measured
against the existing two-second target in the owned fixture environment; this is
not a production latency or reference-load result.

A separate actual RabbitMQ case exits the continuation worker after its commit,
then consumes the original unacknowledged message on restart. The original job,
observation rows and continuation result remain unchanged and settled usage
increases only once. This is separate from the keyboard journey; it is not a
claim of combined browser-crash recovery.

The new hosted keyboard case is mandatory alongside the original operator case,
under the unchanged timeout, isolation profile and CI-only guard. Local normal
and fresh checks retain explicit infrastructure skips. Genuine hosted keyboard,
installed artifact, broker and migration gates must be reported separately.
No guarded CI context is fabricated for local execution.

No live acquisition, new catalog/policy/grant, reference-load certification,
publication-date/reuse semantics or export reconciliation is included. Historical
keyboard/DNS/parser intermittency remains unresolved. Formal final review and
production release acceptance remain separate.

The first hosted lifecycle journey encountered an optimistic revision conflict
while the original journey passed. The broad phase label did not identify the
specific control, so that historical cause remains unproven. The new journey
omitted the original journey's wait for Pause to reappear after Resume. Because
Cancel is available while paused, opening its dialog immediately can capture a
pre-resume revision. A deterministic delayed-completion model reproduces that
conflict, verifies the resumed-render wait, and refuses incomplete transitions.
The journey now observes that same resumed state before opening cancellation;
fixed phase labels distinguish pause, resume, confirmation, retry refusal and
retained review. Runtime behavior, revision checks and deadlines are unchanged.

The next hosted lifecycle run passed cancellation, retry refusal and retained
review, then exposed an exact-label mismatch at the export handoff: the guest
used the Contacts job label on the Export screen. The guest now uses the existing
Export label without changing its exact-match or carried-job assertion. A local
regression reads that guest selector and compares it with the actual rendered
Export field and selected job value; it fails on the old label and passes on the
correct one. This does not change export runtime behavior or reconciliation.

The corrected export journey subsequently completed its UI assertions, but the
host refused its result while requests remained pending. The lifecycle branch
now leaves the live job workspace using ordinary keyboard navigation, verifies
the recent-jobs table, and drains pending and admitted requests within the same
ten-second bound used by existing journeys before emitting its result. The host
still rejects premature completion. Deterministic regressions cover empty,
in-flight, admitted-but-not-yet-pending and non-settling channels; this cleanup
does not cancel or ignore outstanding work or change runtime behavior.

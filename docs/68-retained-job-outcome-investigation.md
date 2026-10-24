# Retained job outcome investigation

This bounded EM-010/011/012 view advances document 03's job investigation workflow
and FR-021/023/025, existing FR-017 presentation, and NFR-001/009/011. It does not
complete every FR-023 filter or certify production extraction.

## Operator workflow

Open a job to see whole-job progress counters separately from **Article outcomes**.
Article outcomes use the existing `GET /article-outcomes` with the selected job,
a server cursor and a page size of 25. Previous/Next traverses retained authorized
article rows; page counts never become job totals. Rows show the existing source
URL, outcome, reason, completion time, observation status and inherited-job
identifier. Missing completion or observation fields are explicitly unavailable.
Source URLs are escaped text, not an acquisition request.

**Inspect article observation** opens the existing retained-batch quality view,
including observations without any contact candidate. A batch identifier permits
an attempt to read current quality; it is not proof that quality remains readable.
Missing batches and denied/expired/deleted observations stay unavailable. No
parser reasons are inferred from a no-contact outcome. Existing XML uncertainty
and HTML reason-availability semantics remain unchanged.

Job-scoped Contacts and Review queue navigation opens the existing association
filters and evidence/review workflow. These are job-level links, not exact-item
contact filters. Opening investigation itself performs reads only. Existing
pause, resume, cancel and continuation buttons keep their separate authority.
The retained execution diagnostics explicitly cover only the first 100 items;
they are not the paginated article dataset and do not provide complete history.

## Current visibility and interaction

The existing outcomes API enforces current tenant/session/membership, source,
policy, job-deletion/privacy and retention fences. The independent batch-quality
read additionally checks retained batch/source binding and current visibility.
No new grant, migration, cursor format, review semantic, source route or backend
contract is introduced.

Organization/job changes reset pagination and details. Request-keyed page content
is hidden during page or revision changes, errors, stale responses and closed
scope. Quality refresh hides the prior response immediately. The modal uses native
keyboard focus containment, Escape/Close behavior and restoration to its opener
(or the section heading when the opener has been replaced). Pagination is keyboard
operable; changing pages moves focus to the persistent section heading. Replacing
a focused row/control on stream refresh uses the same fallback without stealing
unrelated focus. Current authorization remains enforced by the server on every read.

## Acceptance boundaries

The authored browser pagination fixture can exercise more than 100 outcomes for a
single job without changing production constraints. The actual fixed synthetic
SQL profile permits only a small closed list of unique article routes per job;
real SQL pagination over more than 100 rows therefore uses multiple authored jobs,
with separate job-scoped/cursor and current-authority tests. These are distinct
proofs: route-intercepted browser data is not SQL-backed extraction evidence.

The unchanged 104-outcome SQL test remains in the mandatory hosted SQL job,
alongside the 29 exact retained article-filter SQL cases. Its backend complement
must execute every collected test outside that explicit 30-node manifest. A closed collection/execution
proof and matching source/configuration/manifests at the required three-job join
prevent omitted or duplicate coverage; skips and incomplete execution fail. The
[development runbook](25-development-runbook.md) records the fixed profiles and
unchanged wrapper, cleanup and workflow budgets. Full normal/fresh local aggregates
remain unfiltered.

Normal/fresh serial local gates, independent source review and all inherited
hosted actual SQL/operator/service/packaging gates remain required. Local
infrastructure skips are not acceptance proof. See the [validation record](../reports/job-outcome-investigation-validation.md).

Deferred: new server-side outcome filters, attempts on each outcome row, historical
events, cursor-security redesign, new evidence or review semantics. No live
credentials, source activation, contact publication, merge or deployment follows
from this UI slice.

The subsequent [retained article filter increment](69-retained-article-filters.md)
adds exact-item navigation and outcomes-only presence. The descriptions above
record this earlier job-level slice; its unchanged 104-outcome acceptance remains
required for the dependent increment.

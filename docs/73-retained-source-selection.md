# Existing registered source selection

## Scope

FR-003/004/023/024/025 and EM-003/006/011/012: connect readable source
presentation, explicit keyword source choice, retained Contacts/Review and export.
Only `synthetic-publisher` is supported. A URL hostname, DOI, XML/PDF parser or
acquisition route is not another source. No catalog row, source policy, execution
entitlement, credential or runtime grant is added.

Source presentation separates fixture registration, platform availability, tenant
policy approval/expiry and required worker composition. Health remains unknown;
registration does not certify live access. Existing server planning and launch
refusals remain authoritative. An unsupported or unverified source is not an empty
successful search. Publication-date/journal/type filters remain unavailable.

The keyword source participates in request identity and plan invalidation. A
monotonic input generation prevents a late A response after A → empty → A from
restoring a plan. Organization/session remount and existing closed-scope checks
remain in force.

## Retained selection contract

Optional `source_id` is exactly `synthetic-publisher`; omitted/null means all
currently authorized matching records. Unsupported identifiers are rejected, not
normalized, inferred or silently dropped. The selected source binds contact and
outcome cursors, preview, idempotent export requests and immutable snapshot filters.
Default serialization omits the key, preserving legacy request/cursor identities.
All existing job/item/paper/author/status/query/presence semantics remain intact;
candidate presence still applies only to article outcomes.

Contact provenance comes from the retained article observation joined to its
association batch. Outcome provenance comes from the registered discovery record.
The older nullable `jobs.source_id` is not populated for extraction jobs and must
not substitute for those records. Existing visibility, locking and lifecycle
fences are retained before and after selection. No people or acceptance decisions
are merged or transferred.

The UI carries source selection from Review to accepted Contacts to explicit
export preview/create. Changing selectors clears page cursors/evidence and
invalidates previews. Existing request ownership prevents stale responses from
repopulating the new scope. Source is shown in the handoff/preview summary.

## Migration and rollback

Migration 0020 replaces existing filter validation, retained query, export request
normalization/construction and exact schema-readiness functions. It adds no tables,
columns, catalog entries or grants and changes no existing data or migration file.
Old omitted/default requests and snapshots remain readable on the new version.
Fresh migration and an upgrade through 0019 reach the same function definitions;
reapplying Alembic head is a no-op. The service schema guard accepts only the one
expected 0020 revision, retaining fail-closed behavior for old/ambiguous revisions.

Old application code cannot parse new source-selected snapshots. Do not roll back
application code while such snapshots/work remain. Downgrade is refused; use
forward repair, or the separately controlled full restore procedure. Reverting a
frontend alone does not remove the new stored filter contract. Production restore
and deployment are not authorized or claimed here.

## Acceptance inventory and limits

Pure/model/schema/cursor tests cover exact source syntax, legacy omission and
source-bound cursor refusal. Real disposable PostgreSQL cases cover combined
selectors, pages, preview and CSV/XLSX membership, replay/conflict, malformed SQL
and API refusal, tenant isolation and source/session/deletion/retention fences.
Frontend tests exercise the real wizard handlers for invalidation and late plans,
selector serialization, readable unknown availability, summaries and explicit preview.
The authored installed keyboard journey selects the existing source and carries
it from Review into accepted Contacts and export.

Normal/fresh local results are recorded separately after execution. Actual guarded
installed/browser/service/broker and populated migration/restore gates require
genuine hosted execution and remain pending until then. One executable source
cannot establish positive isolation between multiple publishers. Historical
parser/keyboard/PDF callback intermittency remains unresolved; formal final review
is deferred. Export reconciliation, live acquisition, dates and reuse freshness
are outside this increment.

## Keyboard diagnostic follow-up

The hosted late-organization outcome exercise exhausted its existing 100-Tab limit
with an enabled, tabbable target. The cause remains unresolved. A passive observer
now records up to 32 fixed-category target-detachment/replacement and heading-focus
transitions, indexed by the real Tab count, during that same attempt. It records no
text, values, identifiers or URLs. The original keyboard helper, limits and
assertions remain unchanged; diagnostic failure cannot replace its result. Observer
ordering and bounded output have deterministic synthetic tests, which are not a
substitute for hosted browser evidence or a claim that the intermittency is fixed.

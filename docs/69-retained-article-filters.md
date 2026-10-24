# Retained article selection and candidate presence

This bounded FR-023 increment follows retained job investigation (document 68).
It adds exact retained article selection, not general source/date/DOI filtering or
new acquisition. Local pure checks, actual SQL tests and authored browser cases
are different evidence; see the [validation record](../reports/retained-article-filters-validation.md).

## Operator and API contract

`GET /organizations/{org}/contacts` accepts optional `job_id` and `item_id`.
`GET /organizations/{org}/article-outcomes` accepts those identifiers plus
`article_outcome_presence`. A non-null item requires a job. The exact pair identifies
one retained article execution item; a foreign, missing or discovery item is
unavailable. Another job's identical URL, DOI or publisher URL is not equivalent.
Contacts retain the original batch's job provenance even when selected from a
continuation. No contact row is invented for an article without candidates.

The default is accepted-only Contacts and all article outcomes. The new presence
predicate applies **only to the separate article-outcome dataset**, never to
Contacts, Review or their state/author/text filtering. Its closed values are:

- `all`: no candidate-presence restriction (default).
- `observed_candidate`: a current, bound supported observation has actual candidates.
  Syntax validity, unmatched identity, rejection and execution state do not negate
  those observations. XML partial observations with candidates are positive even
  when the execution outcome is `unsupported` / `xml_partial`.
- `completed_without_candidate`: a current, complete supported `no_contact`
  observation has zero candidates in both retained observation and batch.
- `unresolved`: incomplete, unavailable, unsupported, missing or inconsistent
  observation/batch binding, including empty partial XML and uncompleted browser
  work. Empty Contacts and execution status alone never establish a negative.

Jobs exposes a keyboard-native presence selector and per-item Contacts/Review
navigation. Contacts/Review includes an exact item field requiring the job, with
presence controls in the separate outcomes section. Exports exposes both selectors
and explicitly labels the outcomes-only predicate in its current preview. Filter
changes reset page cursors and details, invalidate preview, and hide responses
owned by older requests. Job changes clear item identity. Organization, job,
revision and per-request identity fence late responses, including a return to an
earlier path after another request or a disabled interval; existing modal Escape/focus
restoration and page-heading navigation remain.

Evidence-dialog closure restores focus by the exact batch/association identity to
the currently authorized connected Evidence button, including after refresh replaces
its DOM node. If that row is unavailable, the connected view introduction is the
fallback. Closed scopes never restore focus. Loading and current-page membership
guards still hide stale rows and details; focus restoration does not retain them.

## Current binding and SQL authority

Classification resolves `execution_items.batch_id`, then the batch's **original**
source job and observation. It verifies organization, article URL, source revision,
generation, policy, deletion generation, retained snapshot provenance and current
privacy/retention. XML also binds its retained organization/job/item/generation/
policy/deletion/discovery revision. The inherited-item chain must reach that
original item with the same batch and URL; cycles or more than 1,000 generations
fail closed. The immediate predecessor URL is never used as source identity.
Missing, unsealed, replaced or expired evidence cannot produce a negative.

Filters run before keyset ordering/limit. Cursors bind tenant, dataset and the full
filter object. The legacy five-argument `result_outcomes` and its row document
shape remain unchanged. A distinct bounded `result_outcomes_filtered` entrypoint
has the same runtime read capability. Default requests delegate to the legacy
query. Contacts resolve the selected batch once per page and recheck it; outcome
filtering avoids computing full export fingerprints for every scanned item.
No limits or statement deadlines increase.

Migration `0016_retained_article_filters` updates the current
`exports_create_pre_entitlement` and `exports_preview_pre_entitlement` bodies,
retaining their entitlement and service wrappers. New owner-private helpers are
not executable by PUBLIC, runtime, authenticator, publisher or worker. Only the
filtered outcome read entrypoint receives the existing runtime read grant. Shared
`service_job_visible` and `service_batch_visible`, policies, credentials and role
capabilities do not expand. No new PDF persistence or durable PDF read route is
introduced; PDF complete-scan/partial-positive semantics have pure tests only.

## Immutable export and races

An immutable export request and snapshot retain the exact selector and presence
predicate. Filtered snapshots additionally capture unique exact job/item binding
fingerprints for every exported outcome and the selected item, even for
contacts-only exports. Preview and creation use identical filtering. Contacts
remain original-provenance rows and never gain fake memberships.

An owner-private exact-export validator first requires the existing
`work_export_allowed` fence, verifies the complete captured identity set, then
rechecks current selected-child/source authority, retained source fingerprints
and classification. It grants no batch/job read access. This permits a narrowly
delegated worker to render a no-contact outcome without export members, or an
inherited contacts-only selection without child-job service visibility. It does
not permit another export or delegation. Source/child deletion, policy/privacy/
retention changes and evidence no longer supporting a captured classification
invalidate the artifact. The existing requester, expiry, association revision,
suppression, document-comparison and artifact-integrity checks remain at
create/claim/finish/download; publication's existing bounded checks are retained.

Old requests, snapshots and cursors remain parseable. New default keys are omitted
when serializing legacy filters/requests and old snapshot bindings are omitted.
SQL normalizes explicit new defaults before idempotency comparison; changing a
nondefault selector/predicate with the same key conflicts. Outcome rows gain no
new fields, preserving prior snapshot document comparisons.

## Migration, evidence and boundaries

Apply the forward-only migration with the separate migration identity and deploy
only a reviewed matching runtime. The exact service schema-readiness sentinel and
closed restore compatibility advance to 0016. Existing service authority, roles,
rows, deadlines and revocation history are unchanged. Downgrade is refused;
stop admission and use a compatible forward repair. This candidate authorizes no
merge, deployment, live source access, activation or credential configuration.

Required evidence includes pure/model/schema/cursor compatibility, actual SQL/API
and exact worker scenarios, plus actual keyboard operator acceptance. The unchanged
104-outcome test and 29 exact retained-filter SQL cases share the existing SQL
job. The explicit 30-node manifest, full backend complement and mandatory fail-closed join
remain required at the exact reviewed source. Serial normal and fresh aggregate
checks must run after source freezes. Infrastructure skips are not SQL or browser
proof. General FR-023 source/date filtering, cross-job paper identity and production
certification remain outside this increment.

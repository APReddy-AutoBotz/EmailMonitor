# Retained paper identity across jobs

Local candidate for FR-008, FR-019 and the paper-selection part of FR-023,
within EM-009/011/012. This is a conservative identity grouping slice, not a
complete person registry, acquisition cache or live-source certification.

## Identity and storage

Only an explicitly observed, validated bare DOI establishes a paper key. The
supported grammar is the existing connector's bounded ASCII DOI subset, at most
256 characters, with lowercase normalization and no empty/dot path segments.
Resolver URLs, Unicode identifiers and unsupported forms remain ungrouped rather
than guessed. Every observed DOI fact must agree with the preferred DOI after
normalization and have an evidence locator; missing, malformed or conflicting
facts produce no key. Title, author name, email, article URL, PII and PDF digest
alone never establish cross-job identity. The key describes observed identity,
not a claim that an external DOI registry has certified the observation.

Migration 0019 adds an owner-private immutable derivation, a `paper_doi` column
and an index on `(organization_id, paper_doi)` over retained observations. There
is no global lookup table, new login, grant, source policy or network route. An
owner trigger derives the column after the existing observation guard; callers
cannot supply an authoritative key. The index is maintained in the
same transaction as each guarded observation insert/update/delete; concurrent
jobs keep their separate observations with the same derived identity. No new
shared-row lock or union/merge transaction is needed. Existing observation bytes,
source versions, job provenance, batch IDs, authors, reviews and evidence remain
unchanged. Current batch-to-observation revision and generation must still match.

## Read and export contract

Optional `paper_doi` selects the same observed paper across currently authorized
jobs. It intersects, rather than replaces, existing job/item/state/role/text and
outcomes-only presence selectors. A valid unknown key yields an empty result;
invalid syntax is rejected. A key is never a capability and does not disclose
another tenant's existence. Each returned row retains its original provenance
and review state. Matching a paper cannot transfer acceptance, merge people,
reuse expired evidence or suppress a later acquisition.

Filtering precedes keyset pagination. Cursor identity includes the normalized
selector. Preview and immutable export requests use the same filter; absent
selectors preserve legacy serialization/idempotency. Selected outcome bindings
are captured and rechecked, while every selected contact remains bound to its
original batch and current observation. Worker, finish and download retain all
existing source, requester, revision, suppression, retention and deletion fences.
New observations do not enlarge a previously captured export.

Contacts/Review and Exports expose the optional DOI selector. Changes clear page
cursors and selected evidence; export payload changes invalidate the preview.
Existing request-ownership guards discard stale responses. No publication-date
interpretation or new source selector is introduced.

## Migration and acceptance plan

Forward-only from 0018; matching runtime schema readiness advances to 0019.
No historical payload or policy rewrite is permitted. Downgrade refuses: stop
admission and use a compatible forward repair. Deployment is not authorized by
this local candidate.

Required proof: syntax/model/schema/cursor parity; actual PostgreSQL conflicting
facts, concurrent jobs/replay, independent reviews, tenant and current-authority
fences; pagination before limit; immutable filtered exports and revocation;
keyboard/stale-response cases; normal and independent fresh aggregate checks.
Genuine-CI-only installed browser, service/broker and migration/restore acceptance
must remain explicitly pending until run at the exact published candidate.
No skipped test is a passed acceptance test. Validation results are recorded in
the candidate report, not inferred from earlier PDF acceptance.

Cross-job verified-observation reuse, date/source filtering, live acquisition,
held export reconciliation, formal release review and production readiness remain
outside this bounded increment.

The authored HTML article-a fixture now explicitly supplies
`10.9999/synthetic.article-a`. Its new exact digest is pinned; migration 0019
retains recognition of the previous exact fixture digest for historical records.
That old observation has no DOI and is never retroactively assigned one. XML's
requested identifier is not repurposed as observed metadata. No fixture source
policy, allowed URL or parser limit is widened.

Local implementation validation and unresolved hosted gates are recorded in the
[candidate report](../reports/retained-paper-identity-validation.md).

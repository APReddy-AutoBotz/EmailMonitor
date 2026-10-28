# Publication dates, reuse and association unlink

These decisions resolve the product defaults for FR-004/010/019/020. They do not enable any new source, acquisition authority or live publisher.

## Publication-date requests

Publication bounds are inclusive full ISO calendar dates. The chosen type must be explicit for new UI requests: published, online publication or issue publication. Source-declared raw values and precision must remain visible. A future connector must refuse filtering if it cannot prove the requested type and complete filter semantics; it must not invent a day for a partial date, choose among conflicting dates, or treat an incomplete retained-result postfilter as a complete source search. Missing or ambiguous evidence remains explicit.

The wizard can now record a date type and bounds and invalidates an earlier plan when either changes. The current synthetic connector cannot perform publication-date filtering and returns `fixture_filters_unavailable` without starting discovery. Selecting a date in the wizard does not constitute filtering or a claim that any matching results exist. Existing API requests with date bounds and no type remain valid for compatibility and are still refused by the unsupported connector. Omitting date selection preserves the existing request and idempotency identity. This change adds no migration. Search-filter execution, explicit source declarations and connected filtering acceptance remain future work; generic HTML `time` observations in the current parser are labeled `published` by parser convention and do not independently prove the source explicitly declared the type. Historical retained observations are not rewritten.

The current-authorized retained metadata view can separately annotate each recorded date fact with the precision recognized from its exact text: year, month, full calendar day, or unrecognized. It does not fill missing components, rewrite the fact or citation, certify the parser's date-type label as a source declaration, or select a value when observations conflict. Unsupported or invalid text remains visible and unrecognized. A separate versioned read endpoint wraps the existing authorized metadata with these annotations; the original strict response and schema remain unchanged. The new UI requires the matching endpoint and fails closed when it is unavailable. This annotation is not a discovery filter or evidence of complete search results, and adds no migration or source access.

## Verified observation reuse

Reuse must be a deliberate per-job choice, limited to verified retained observations in the same tenant within a user-selected freshness cutoff. Current source authority, retention and suppression must be checked at use, and reused evidence must carry its own lineage, observation time and age. Requested fresh acquisition cannot be silently replaced; the user retains an acquisition option. Review decisions and audit history are not transferred by matching DOI. This is the selected contract, not implemented reuse. No default freshness period or cross-tenant sharing is implied.

## Evidence correction and unlink

Unmerge means an audited, reversible unlink of the selected author-address association into unresolved review, using revision checks, current reviewer authority and existing export invalidation; it does not split people or delete source evidence. Attaching evidence requires its own valid observation and source/tenant provenance. The bounded unlink implementation and its validation limits are described in `docs/83-review-association-unlink.md`; cross-observation attachment remains unimplemented. Existing role restrictions remain in force.

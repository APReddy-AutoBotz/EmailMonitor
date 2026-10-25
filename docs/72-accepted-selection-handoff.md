# Accepted-results selection handoff

## Scope and lineage

FR-023/024/025, EM-011/012, NFR-011 and UX03: connect retained Review,
accepted Contacts and private export. This is a selector handoff, not a transfer
of a review decision, row membership or authorization.

Review offers **View accepted results for this selection**. It explicitly changes
the association state to accepted while retaining supported job, article item,
observed paper DOI, author-role, literal-query and outcome-presence selectors.
Contacts offers **Export this selection** only with export capability and accepted
state. Rejected, unmatched and review-only selections cannot directly seed an
export. Incomplete selectors are refused rather than dropped.

Exports displays the carried selection and requires a fresh informational preview
and explicit create. Cursors, previews, export identifiers, replay keys and
unresolved inclusion never travel. Outcome presence still applies only to the
separate outcomes table. Empty selectors explicitly select all currently authorized
matching accepted results; they do not imply the current page is the entire set.

Changing options invalidates preview ownership, including A → B → A edits. Late
responses after unmount or scope teardown cannot restore an actionable preview.
Organization/session changes remount workspace selection state. Ordinary Exports
navigation discards the handoff and starts its existing independent form.

## Validation and remaining proof

`selectionHandoff.test.tsx` covers selector whitelisting, incomplete/cleared state,
accepted-only mapping, capabilities, summary/preview controls and response generations.
`test_selection_handoff_tenant.py` exercises actual PostgreSQL preview, immutable
CSV/XLSX membership, duplicate creation, changed-key conflict, tenant and deletion
refusal. Existing retained-paper lifecycle tests cover source, session and retention
changes. The installed operator keyboard journey now traverses Review → accepted
Contacts → Export and asserts the carried DOI, accepted state, explicit preview and
unresolved opt-out. Hosted execution of that authored journey remains pending.

This does not resolve historical parser/keyboard intermittency, complete accessibility
certification or add unavailable source/date filters. Formal final review remains
pending. There are no migrations, runtime grants, source-policy changes, acquisition
changes or changes to export recovery. Rollback is a frontend/test code revert;
existing export snapshots and server revalidation remain unchanged.

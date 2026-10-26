# Retained article metadata in review

Requirement lineage: FR-010 and FR-017; EM-007/008/009/012; article/evidence
presentation in UX03 (`docs/03-user-experience.md`). The parsers already retain
metadata observations; the missing behavior was an inspectable, currently
authorized metadata view in the connected review workflow.

The identifier-only `GET /organizations/{organization_id}/association-batches/
{batch_id}/article-metadata` endpoint projects the exact retained observation
bound to the authorized batch. It shares the existing quality view's runtime-role
RLS joins, batch locks, policy/retention/deletion checks and final visibility
recheck. No migration, grant, source registration, fetch, new parser execution or
stored observation/review mutation occurs. A mismatched source/profile/digest or
preferred-metadata snapshot refuses the whole projection.

The review panel shows preferred title, journal, publication-date text and DOI;
missing values are unobserved. It exposes every retained HTML/PDF metadata fact,
its recorded date type and actual locator/excerpt, including PDF page and coarse
region precision. Multiple distinct values are labelled without discarding the
alternatives or changing parser precedence. XML's current retained profile has no
metadata facts; it remains explicitly unrecorded, with no DOI inferred from a URL
or author/contact evidence. Raw text is escaped and never becomes an executable
link or command.

Publication-date text is not converted into a calendar date, inferred date type,
publication interval or freshness promise. These observations are not sufficient
to enable source search filters or observation reuse. Those separate contracts
remain unchanged. Metadata review is read-only; accepting/correcting an author
association does not rewrite article metadata or resolve conflicting values.

The panel clears on organization/batch/revision changes and hides stale, loading,
failed and mismatched responses. A keyboard-operable details control reveals
citations. Existing review actions, focus checks and deadlines remain intact.

Acceptance inventory: pure HTML/PDF/XML projection and mismatch tests; committed
JSON schema/example parity; actual PostgreSQL read/review/replay, tenant, session,
policy, suppression, deletion, retention and final-visibility refusals; render
cases for unknowns, raw dates, conflicting values, stale identity, escaped content
and PDF citations; connected hosted operator keyboard assertions. Local skipped
SQL cases are not actual database proof, and authored hosted assertions are not
passed evidence until the unchanged hosted gates execute them.

# Retained article quality during association review

This additive EM-010/EM-012 slice makes retained extraction uncertainty visible in the existing evidence/review drawer. It does not decide affiliation attribution. The article-level warning applies even after accepting or correcting an author-email association. Missing affiliations remain unobserved, not confirmed absent.

## Read contract and authority

`GET /api/v1/organizations/{organization_id}/association-batches/{batch_id}/observation-quality` returns the closed [observation-quality-v1 schema](../contracts/observation-quality.schema.json), with an [authored example](../contracts/examples/observation-quality.json). It contains organization/batch identifiers, the original parser version, route/status, fixed reason enums, article scope and author-email review scope. It contains no author/contact values, affiliation text, source URL, excerpts or raw document.

The read uses current tenant/session permission, existing parent locks, runtime-role RLS on both the batch and retained observation, exact source-revision/generation/policy/deletion binding, retained-profile validation and a final current-visibility check. An inaccessible or mismatched source refuses the read. No grants or migrations are added. The UI hides old quality on refresh, failure, stale response, identity mismatch or closed scope. The hook-owning child is remounted for every organization/batch/refresh revision so a pre-effect render cannot show the prior successful quality as current.

XML reasons are the recorded parser result, never recomputed from raw XML. HTML/browser-DOM profiles have no equivalent retained reason list: the response says `not_recorded`, rather than inventing a healthy result. An empty recorded reason list does not prove accuracy or completeness. `unsupported_affiliation` describes the article and cannot identify which author's affiliation is missing. Review acceptance cannot clear or repair this warning.

## Compatibility

The new version is a read-view version only. Existing Bundle JSON, input digests, replay comparison, retained XML/parser versions, author/affiliation/evidence identifiers, review persistence, export contract and database history remain unchanged. Adding a default field to Bundle would change serialized input identity; this implementation deliberately uses a separate response model and endpoint. No parser association rule, implicit inheritance rule or diagnostic counter changes.

## Operator reach and validation

The original drawer is reached through existing contact/review rows. The additive [job investigation view](68-retained-job-outcome-investigation.md) also opens retained quality directly from an article outcome, including zero-candidate observations; it does not add new outcome filters. The projection still represents supported no-contact and unsupported outcomes, and the endpoint can serve a visible retained batch independently of a contact row. Loading/error messaging does not block existing author-email review permissions or replace the server's review checks.

Validation covers authored partial-affiliation facts, unchanged acceptance/replay serialization, closed response values, source mismatch refusal, empty-candidate outcomes, runtime-role SQL/API visibility and current-authority refusal. The actual disposable XML pipeline checks the view before/after review. The required keyboard browser journeys check HTML/XML presentation; the HTML journey holds a response across refresh, aborts a subsequent response, and checks that prior quality stays hidden before recovery. These tests use synthetic sources only. Full service/container proof requires CI, not local skipped tests.

This change does not authorize further licensed sample acquisition, claim corrected affiliation extraction, certify a publisher, or complete production runtime/UAT/release acceptance. The existing single-attempt source workflows remain unchanged and must be skipped for this draft.

Validation boundary and preserved local failure: [receipt](../reports/observation-quality-review-validation.md).

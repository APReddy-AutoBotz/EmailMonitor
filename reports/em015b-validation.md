# EM-015b — ScienceDirect XML observation evidence

## Scope and baseline

October 15, 2026. A bounded inert journal-head XML parser returns actual ordered author, correspondence, published email and affiliation observations from caller-supplied bytes. It reuses existing fact models in a separate XML envelope. Newly authored synthetic fixtures only. No live extraction, credentials, dependency, migration, registration, persistence, deployment or merge.

Local base `d96dd3c` has tree `1b0a4955aa9c68360635a6b7161dd65e1cdf6476`, identical to accepted Draft [PR22](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/22) remote head `34bc32e60d86715299a8610a5936486805ba33b4`. PR22's final body records accepted all-seven own-head gates, including 1,623 application tests/no skips. Its earlier in-tree pending report is historical. Publication must use actual remote ancestry; this local checkout has no remote.

## Source and limits

The [runbook](../docs/47-sciencedirect-xml-observations.md) records the verified official native hierarchy/semantics and unavailable XML/schema samples. Independent documentation research corrected an initially contemplated nonstandard correspondence/e-address path; only direct author/collaboration e-address fields produce candidates. The wrapper namespace remains explicitly a candidate compatibility assumption. Native XOCS input is supported with its own required identity. This is not a claim to have parsed an actual authorized researcher record or licensed paper.

## Local checks

- Initial focused run: 77 passed / 1 failed. It caught an author-context evidence excerpt assembled from names rather than the actual located node text. Corrected to actual normalized node text; a locator-resolving regression verifies all author/candidate evidence against original XML elements and attributes.
- An expanded intermediate run had 94 passes / 1 fixture-construction failure: the test inserted a nested author without removing its old element, correctly triggering the duplicate-ID refusal. Corrected the fixture move. Intermediate type/lint runs also caught a callback return annotation, import ordering and a reused test variable name; all are corrected. These were not accepted checkpoints.
- An early aggregate reached 1503 passes / 219 service skips but its subsequent tool-session polling was cancelled before a complete aggregate result was available. No full-pass claim is based on that run.
- Independent review reproduced two provenance/outcome defects: an implicit-affiliation element excerpt could be taken from an unrelated `refid` attribute, and a direct unsupported correspondence email could be omitted without a partial reason. Both are corrected with regressions. Unknown root profiles also now remain `unknown`.
- Final focused parser suite: 106 passed in 0.63s; independent rerun 106 passed in 0.64s. Two-file Ruff/format and strict mypy passed. Independent scoped source/tests/documentation review reports no remaining blocking finding.
- Pre-review-correction normal and empty-Python-environment aggregates passed 1507 tests / 219 explicit service skips in 22.96s / 23.64s, plus 31 React tests and all static/docs/inventory/build gates. They are superseded for the final source by the next runs.
- Final normal aggregate: `UV_CACHE_DIR=/tmp/emailmonitor-uv-cache scripts/check.sh` exited 0 with 1510 passed / 219 explicit service skips in 22.05s, plus 31 React tests, docs/contracts, Ruff/format, strict mypy (198 files), inventory, frozen-lockfile/peer checks, TypeScript/lint and frontend build.
- Final fresh Python aggregate: verified `/tmp/emailmonitor-em015b-reviewed-fresh` absent, performed locked `uv sync` there, then ran the same aggregate with `UV_PROJECT_ENVIRONMENT` set to that new directory. Exit 0: 1510 passed / 219 explicit service skips in 23.19s, plus 31 React tests and all the same gates. The earlier `/tmp/emailmonitor-em015b-fresh` environment was not reused for this final fresh-install claim. Frontend installation remained frozen-lockfile existing state; no fresh frontend installation claim.
- After recording these results, the documentation validator and staged whitespace checks passed. The final staged tree is reported outside this file to avoid a self-referential tree hash.
- Exact-head application/controlled transport/UI/browser/parser/docs/packaging CI: pending. Existing no-I/O tests do not establish isolated XML runtime acceptance.

## Completion boundary

[Runbook47](../docs/47-sciencedirect-xml-observations.md) lists supported profiles, unsupported cases, source binding and next executable integration. Full EM-015 is incomplete. No migration/rollback data loss, source permissions or security grant changes. Live/production entrypoints remain disabled.

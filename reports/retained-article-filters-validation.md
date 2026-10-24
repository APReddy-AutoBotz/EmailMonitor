# Retained article filter validation candidate

Date: 2026-10-23. Scope: [bounded FR-023 increment](../docs/69-retained-article-filters.md).
Base accepted PR49 source is unchanged; implementation is on a separate feature
branch/check-out. No publication, merge, deployment or external activation is
claimed by this record.

## Evidence recorded at initial freeze 9d6926195e0cefd5648af71863bfc1e729cb0666

- Focused backend suite: **950 passed, 38 skipped** in 12.27 seconds. It includes
  the new pure and actual SQL/service suites, operator protocol checks, existing
  result contracts/cursors/serialization, migration compatibility, service plan-cache/
  restore contracts and mandatory application partition/join controls.
- Frontend unit suite: **97 passed in 14 files**; TypeScript and ESLint pass.
- Focused Ruff check/format pass; mypy reports no issues in 17 source files.
- Documentation validator passes: 89 Markdown documents, 444 local links, 58 JSON
  files, 25 schemas, 28 valid examples, 16 negative cases and complete FR/NFR traceability.
- License inventory passes for 64 Python and 159 JavaScript locked packages.
- The 38 skips include 29 new actual SQL/service cases and nine migration checks.
  This local environment lacks Docker/owned PostgreSQL. Skips do not prove SQL
  syntax, migration, RLS, export-worker or lifecycle behavior. No new dependency or
  hosted execution is claimed.
- Independent early design/source review accepted the bounded private exact-export
  approach after fixing nullable classifier guards and a PL/pgSQL alias ambiguity.
  This is not frozen-source approval or hosted acceptance.

## Request-ownership correction and interrupted validation

Frozen-source review found that field equality in the initial `useResource` could
reuse an older settled success or error after A → B pending → A, or after disabling
a resource (`path=null`) and reopening the same path. The correction gives each
scope/path/revision transition a request identity, makes the effect depend on that
identity, and stores that exact identity with both success and error. Returning to
an earlier path cannot acquire its old response. Memo eviction starts a fresh
request rather than reusing stale ownership; abort/closed-scope fences remain.

The actual Contacts operator matrix for initial success/error crossed with pending
A → B → A and disabled null → A is **AUTHORED UNEXECUTED** locally. Its held replies
assert that old empty results/errors disappear, the current request alone settles,
and a delayed abandoned request cannot overwrite it. The local protocol test only
checks that this matrix is wired into the operator harness; it is not browser proof.

The parent-reported normal aggregate attempt on the initial candidate displayed
**5,055 passed and 427 skipped**, but a registry-validation permission denial stopped
completion before a verified complete exit. That receipt is incomplete, not a
normal aggregate pass. No fresh aggregate or hosted acceptance is established by
it. The original focused evidence above remains historical, not validation of the
corrected source. Fresh explicit approval permits the correction and new bounded
validation; parent-coordinated serial normal/fresh checks remain pending.

Corrected-source focused checks completed serially after edits:
- `pytest -q test_operator_ui_protocol.py test_retained_article_filters.py`: **139 passed** in 2.04 seconds (paths under `services/backend/tests`).
- Frontend Vitest: **97 passed in 14 files**; TypeScript and ESLint pass.
- Focused Ruff check/format passes; mypy reports no issues in three changed Python files.
- Documentation/contract validation and `git diff --check` pass.
- These checks use existing locked dependencies. They do not execute the four new
  browser cases, SQL, migration, service worker, or the full normal/fresh aggregates.
  The browser cases remain **AUTHORED UNEXECUTED** locally.

## Authored acceptance inventory

`test_retained_article_filters.py` covers optional/default serialization, schema
parity, all cursor mismatch dimensions, exact snapshot bindings and independent
candidate semantics. HTML/browser/XML cases distinguish positive, supported complete
negative and unresolved. PDF tests are conceptual offline parser evidence only.

`test_retained_article_filters_tenant.py` requires actual SQL/API execution for
pre-limit paging, exact item denial, legacy entrypoints, unchanged private helper
ACLs, review independence, preview/snapshot/idempotency, two continuation generations,
unrelated same-URL batches, corrupt/missing/unsealed/expired/replaced binding,
bound XML classifications and privacy/retention/suppression races. Corruption probes
alter only owned synthetic test rows and restore them; they do not widen catalog
routes, acquisition or runtime permissions.

`test_retained_article_filters_service_tenant.py` requires actual narrowly delegated
worker completion for zero-contact outcomes without fake export members and
inherited-child contacts-only snapshots retaining original Contact provenance.
It checks private helper denial, unchanged batch/child read visibility, wrong-export
refusal and deletion/source/retention/revocation changes after claim.

The existing operator acceptance program now contains actual no-contact selector
and export-preview assertions. Its separate 127-row authored browser contract tests
keyboard presence changes, page reset, late-filter isolation and exact-item
Contacts/Review navigation, preserving prior organization/job/modal cases.
Route-intercepted rows are not SQL-backed extraction proof.

## Pending gates at this writing

Frozen complete-source review, serial normal/fresh aggregates, and the full inherited
hosted suite remain required. The dedicated 104-outcome SQL test is unchanged;
the backend complement must collect and execute every other test, with the existing
mandatory exact-source fail-closed three-job join. All wrapper/job/statement/cleanup
deadlines remain unchanged. Record exact commit/tree and receipts before claiming
acceptance. No local infrastructure skip substitutes for any hosted gate.

## PR50 first hosted attempt and refusal-expectation correction (2026-10-24)

Draft PR50 first head `376b2c5bcbe2e34bbe2dc7f9333ea6aa9b7b4f7d`, tree
`254ba6d045b29f388c9176d8554a80c2099b9ac7`, was published against unchanged PR49.
All protected first-attempt runs were allowed to reach terminal state before edits.

- [Application run 40052379222](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/40052379222)
  failed. Its dedicated outcome SQL test passed with zero skips and matching tree,
  and static/97 React/build passed. Backend progress records two service test failures
  and one suppression test failure before the unchanged 1,200-second wrapper bound;
  owned cleanup passed, but no final backend summary or partition receipt exists.
  The mandatory join correctly failed. This is not a completed backend pass.
- [Operator run 40052379312](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/40052379312)
  failed during existing keyword-worker completion before the new filter assertions.
  Its retained diagnostic reports `FetchDenied` / `source_entitlement_denied`;
  the responsible authority predicate or lock refusal is not established. No UI
  defect, infrastructure flake, or historical root-cause fix is inferred.
- Documentation, browser, parser, metadata packaging, controlled transport and
  service runtime workflows passed. Both live Elsevier workflows remained skipped.
  Installed service proof does not replace the failed original operator gate.

Independent source/evidence review identified two incorrect test expectations.
The service boundary deliberately converts database errors to `AuthorizationDenied`,
so the private-helper refusal probe must expect that public exception. Contact
suppression permanently fences the selected job, so exact preview and creation
must both refuse rather than return an empty preview. The original suppression
case was reproduced against disposable local PostgreSQL 17.11 and failed with
`AuthorizationDenied` at the empty-preview assertion. These test-only corrections
preserve the denial probes; SQL, runtime authority, deadlines and partition gates
are unchanged. The service-only CI guard is not impersonated locally.

Corrected-source normal/fresh checks, independent final review and new exact-head
hosted acceptance remain required. The original three failures, wrapper-bound
failure and operator diagnostic remain historical evidence, not erased by a later pass.

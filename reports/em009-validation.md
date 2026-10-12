# EM-009 — Offline association and review candidate

## Scope and predecessor

This unreviewed candidate adds actual HTML/PDF evidence mapping, conservative normalization, tenant/batch candidate grouping, relational author/candidate/affiliation/citation records and revisioned evidence-backed review. Persistence consumes existing authorized retained HTML/browser observations; no PDF acquisition/persistence route, live source, SMTP/MX, export, UI or production activation is added. Migration 0006 is forward-only. [Runbook](../docs/38-offline-association-runbook.md).

EM-008 documentation checkpoint head 790e40cd6749f2df75395b47da3fb6fe9a9bf0c4 / merge 67155f04a8e29e695a32bd5f37a45d9f89aa5b70 share independently reviewed tree 78b8af6c9a0a9f16ffc3de02b3c5205d2f0676e8, exact 26622480/790e40cd parents. All five own-checkpoint gates passed: [application](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38308658580) 664/no skips/no pytest warnings in121.06s; [controlled transport](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38308658404) 12/58.75s; [browser](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38308658491), [parser](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38308658610) and [docs](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38308658389). PR13 remains Draft/unmerged. EM-WARN-01 cause remains open; runner/service notices are separate from pytest warnings.

## Implemented acceptance cases

- Actual HTML/PDF ordered first and corresponding roles, multiple correspondents, same-name unresolved instances and original source/page/locator/coarse geometry provenance
- Nonempty observed candidate/author evidence required for accepted mapping; incomplete/unsupported/colliding/locator-only input stays unresolved
- Original Unicode, local-part case/plus/dots retained; explicit locked IDNA domains; malformed and unsupported SMTPUTF8/quoted/literal addresses; not_checked/unverified/not_assessed remain separate
- Tenant-stable identifiers and per-batch comparison-key grouping/raw variants; replay preserves review; no global person merge or calibrated score
- Forced RLS/composite tenant relations, current catalog/policy/purpose/session/retention/deletion gates and private lock fence; runtime has no catalog/association UPDATE or DELETE grant
- Owner/admin/steward/reviewer matrix, operator/viewer denial, CSRF, cross-org, cancellation-read-versus-new-ingestion, source replacement/revocation/expiry and offboarding
- Expected revision/concurrent review, immutable history/audit/identifier-only pending outbox, post-write transaction rollback and actual API response contracts

idna 3.20 is promoted from an already installed/locked package to an explicit runtime dependency. No package/version/license chain is added; inventory retains64 Python/159 JavaScript entries and updates the exact lock digest. No new container, profile, workflow, network or host setting is changed or executed locally.

## Local checks and remaining gates

Focused pure/schema/API tests previously passed63 cases;19 actual PostgreSQL cases were explicitly skipped for unavailable synthetic database URLs. A twentieth real-PG atomic rollback regression was then added. These skips are not SQL acceptance. Full normal/fresh-empty aggregate and final source review remain pending at this report snapshot. Required published-head application must execute all collected tests without skips, alongside actual SQL/broker, controlled12, browser/parser and docs gates. No EM-009 acceptance or EM-010 readiness is claimed yet.

## Frozen candidate local evidence

After adding the atomic rollback case and fixing its typed connection argument, normal scripts/check.sh completed successfully:644 passed/103 explicitly unavailable-service skips in24.83s. A new empty source copy installed both exact lockfiles and completed the same aggregate:644/103 in30.00s. Both passed docs/contracts/examples, Ruff lint/format117 files, strict mypy115 source files, inventory64Python/159JavaScript, frontend frozen installation/peer/type/lint/one React test/build. Fresh source bytes were identical to the worktree before this evidence append. Fresh npm registry latency notices are disclosed; no pytest warning summary occurred. Earlier interrupted validation processes were not counted as completed checks.

The focused association suite contains63 pure/schema/API cases and20 real-PG cases; the latter remain unexecuted locally. Full collection is747 tests. Independent exact-tree source review and new-head actual747/no-skip application, current SQL/broker, controlled12, browser/parser and docs are mandatory before scoped acceptance. The UI/default production entrypoints and all existing isolation/workflow controls are unchanged. No local database, broker, browser, container, privileged initialization or network topology was executed.

## Current-version RLS review correction

Independent source review found that the read-side RLS predicate joined the current approved policy without binding its version to the retained batch/observation. The API's locked fence already denied stale versions, but direct runtime SELECT also needs that same restriction. The corrected predicate requires current policy, batch and source observation versions to match. The actual PostgreSQL replacement case now asserts an empty batch listing and zero visible rows across all13 association tables after a new approved same-purpose policy, in addition to the existing API denial. No privilege, source permission, isolation or acquisition path is widened. Corrected aggregate/re-review and actual published-head gates remain pending.

Corrected normal aggregate completed644/103 explicit service skips in23.00s and all gates. A separate new empty source copy installed exact backend dependencies; its initial frontend install stopped because the writable pnpm-store environment variable was omitted. After restoring that existing local package-store setting, the corrected fresh-copy aggregate completed644/103 in22.90s and all documentation/lint/format/typing/inventory/frontend gates. Source bytes matched the successful copy before this evidence append. This operational install retry changed no lock/version/security configuration. Required actual747/no-skip CI and corrected independent review remain pending.

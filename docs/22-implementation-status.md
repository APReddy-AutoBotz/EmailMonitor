# 22 — Implementation status and evidence ledger

**Baseline date:** 2026-10-08. **Updated:** 2026-10-10. **Product state:** metadata-only API/UI scaffold under review; extraction and deployment unavailable.

## Documentation deliverables

Product charter, BRD, PRD, UX specification, architecture, tenant/RBAC design, connector/extraction specification, data model, proposed contracts, job lifecycle, security/privacy, deployment/operations, test benchmark, commercial/onboarding plan, backlog, traceability, ADRs, synthetic fixtures and Codex handoff are included in this baseline.

The repository documentation validator checks local Markdown targets, JSON syntax, schema/example consistency and requirement traceability as implemented by the script. It does not certify business viability, legal compliance, extraction precision or application security. Final publication verification belongs in the handoff report/commit history.

## Task ledger

| Task | Status | Evidence / next dependency |
|---|---|---|
| EM-001 | VERIFIED IN DRAFT PR — unmerged | [PR #1](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/1), head 88e34a7; independent review + [application CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38025740451) + [docs CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38025740436) passed |
| EM-002 | VERIFIED IN DRAFT PR — unmerged | [PR #2](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/2), head bed184b; corrected privilege-boundary review + [application CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38027802453) + [docs CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38027802418) passed; production provider unavailable |
| EM-003 | IMPLEMENTED OFFLINE — review/remote CI pending | [Validation](../reports/em003-validation.md); [source-policy runbook](27-source-policy-runbook.md); no live approval/execution |
| EM-004 | NOT STARTED | EM-003 |
| EM-005 | NOT STARTED | EM-002/003 |
| EM-006 | NOT STARTED | EM-004/005 |
| EM-007 | NOT STARTED | EM-006 |
| EM-008 | NOT STARTED | EM-004/005/007 |
| EM-009 | NOT STARTED | EM-007/008 |
| EM-010 | NOT STARTED | EM-006/009 |
| EM-011 | NOT STARTED | EM-009/010 |
| EM-012 | NOT STARTED | Required UI/API dependencies |
| EM-013 | NOT STARTED | EM-005/010/012 |
| EM-014 | NOT STARTED | EM-009/011/013 |
| EM-015 | NOT STARTED | Technical gates plus actual source permissions |
| EM-016 | NOT STARTED | EM-012/015 and authorized benchmark |
| EM-017 | NOT STARTED | EM-013/014 plus approved staging infrastructure |
| EM-018 | NOT STARTED | EM-016/017 and commercial/legal owner decisions |
| EM-EXT-01–05 | DEFERRED | Separate post-core gates |

## What has not been done

No real researcher emails collected; no source search executed; no live source connector implemented/certified; no tenant database/API/frontend deployed; no AI/mail API keys configured; no emails sent; no benchmark/latency/accuracy results; no customer license or infrastructure purchased; no repository visibility change or open-source license selection.

## How implementers update this ledger

For each task add: state (Ready/In progress/Blocked/Partial/Done), PR and commit, implementation boundary, exact commands and observed results, relevant requirement/test IDs, migrations, remaining gaps and next ready task. Link to sanitized reports; keep real data and signed source/customer agreements outside this public repository.

Do not compute an arbitrary project completion percentage from number of documents or files. Report accepted task/milestone completion and pending critical gates instead.

## EM-001 implementation boundary

FastAPI metadata endpoints, React/TypeScript/Vite unavailable-extraction screen, strict fail-closed configuration, test-only in-memory fixture transport, Python/pnpm lockfiles, full declared-license inventory and offline inventory parity gate are implemented. Source fixture bytes and expected observations remain unchanged. No accepted contact is generated. No identity, tenant database, persistent job, protected egress, queue, extraction or export implementation is claimed.

Local checks are recorded in [EM-001 validation](../reports/em001-validation.md). Independent review and GitHub CI passed for EM-001 head 88e34a7 and exact tree 09fdfab. PR #1 remains Draft/unmerged; EM-002 is developed as a separate stacked offline task. No migration/deployment impact; rollback is removing the scaffold commit and local dependency/build environments. Existing documentation contracts are unchanged.

## EM-002 implementation boundary

Offline OIDC/session, membership/RBAC/lifecycle and real PostgreSQL RLS foundation are implemented and locally tested with synthetic identities. See the validation report and runbook. No real provider/access grant, production activation, extraction or source network is introduced. Fresh corrected-code defensive review and exact-head CI passed for bed184b/tree cbe453d1. PR #2 is Draft/unmerged; this branch adds EM-003 as a distinct stacked task.

## EM-003 implementation boundary

Synthetic read-only source catalog/support matrix; versioned tenant source policies; owner/data-steward approval/suspension/revocation; time-derived expiry, monotonic current version and platform disable gate; strict fixture-only configuration ceilings, opaque permission reference and null synthetic credentials reference are implemented. No acquisition/extraction or secret retrieval occurs. Real credentials/provider manifests and documentary authorization remain future source-onboarding decisions. See the runbook/evidence; independent review and published-head CI are pending. EM-004 is next after acceptance.

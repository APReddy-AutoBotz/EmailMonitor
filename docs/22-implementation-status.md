# 22 — Implementation status and evidence ledger

**Baseline date:** 2026-10-08. **Updated:** 2026-10-10. **Product state:** metadata-only API/UI scaffold under review; extraction and deployment unavailable.

## Documentation deliverables

Product charter, BRD, PRD, UX specification, architecture, tenant/RBAC design, connector/extraction specification, data model, proposed contracts, job lifecycle, security/privacy, deployment/operations, test benchmark, commercial/onboarding plan, backlog, traceability, ADRs, synthetic fixtures and Codex handoff are included in this baseline.

The repository documentation validator checks local Markdown targets, JSON syntax, schema/example consistency and requirement traceability as implemented by the script. It does not certify business viability, legal compliance, extraction precision or application security. Final publication verification belongs in the handoff report/commit history.

## Task ledger

| Task | Status | Evidence / next dependency |
|---|---|---|
| EM-001 | IMPLEMENTED — review/remote CI pending | [Local validation evidence](../reports/em001-validation.md); [runbook](25-development-runbook.md) |
| EM-002 | NOT STARTED | EM-001 |
| EM-003 | NOT STARTED | EM-002 |
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

Local checks are recorded in [EM-001 validation](../reports/em001-validation.md). Independent review and GitHub CI at the exact published head are pending. EM-001 is not marked Done yet; EM-002 is the next task after acceptance. No migration/deployment impact; rollback is removing the scaffold commit and local dependency/build environments. Existing documentation contracts are unchanged.

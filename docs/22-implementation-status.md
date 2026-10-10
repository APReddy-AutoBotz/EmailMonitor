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
| EM-003 | VERIFIED IN DRAFT PR — unmerged | [PR #3](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/3), head 0800137; corrected exact-tree review + [application CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38028911796) + [docs CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38028911825) passed; no live approval/execution |
| EM-004 | PARTIAL — EM-004a verified in Draft PR, unmerged | [Evidence](../reports/em004a-validation.md); [runbook](28-offline-fetch-runbook.md); [PR #4](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/4), head 0a3fa6b; independent review and [application CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38029731856) / [docs CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38029731868) passed; actual public-egress/browser isolation gates unmet; [EM-004b](../reports/em004b-validation.md) real synthetic TLS/parser diagnostics under review, parser CI pending |
| EM-005 | VERIFIED OFFLINE FOUNDATION IN DRAFT PR — unmerged | [PR #5](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/5), head 1abaa3a/tree 62ff0a17; corrected independent review; [application CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38046354505) passed 196 Python tests, including four real-broker tests, no skips; [docs CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38046354454) passed; full EM-004 still gates acquisition |
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

Synthetic read-only source catalog/support matrix; versioned tenant source policies; owner/data-steward approval/suspension/revocation; time-derived expiry, monotonic current version and platform disable gate; strict fixture-only configuration ceilings, opaque permission reference and null synthetic credentials reference are implemented. No acquisition/extraction or secret retrieval occurs. Real credentials/provider manifests and documentary authorization remain future source-onboarding decisions. Corrected review and exact-head CI passed for 0800137/tree 63efdc10. PR #3 remains Draft/unmerged; EM-004a follows as an explicitly partial offline slice.

## EM-004a partial boundary

Strict fixture URL/public-address/pinning validation primitives, bounded in-memory fixture byte gateway and current tenant policy authorization before each hop/release are implemented. Live and browser entrypoints always reject. A disposable bubblewrap network isolation probe failed with Operation not permitted and that route was stopped without retry/alternate isolation route or host security changes. No actual socket connector, enforced HTTP/browser egress or parser process isolation is claimed; EM-004 full acceptance remains unmet even if this partial slice's checks pass. EM-005 may progress independently on its EM-002/003 dependencies, but network-dependent discovery remains gated.

## EM-005 offline durability boundary

Draft original-input requests, synthetic diagnostic job/item ledger, forced tenant RLS, deterministic effects, transactional outbox, leases/attempt bounds, quota reservations/settlement, recovery, pause/cancel and organization deletion epochs are implemented for testing. Celery and immutable official disposable RabbitMQ CI are pinned. Local and clean-install/from-empty aggregate passed 191 Python tests and all other gates, with four explicitly pending actual-broker tests. Independent review and required real-broker/published-head CI remain pending. No extraction result or production worker identity is claimed; EM-006 remains gated by full EM-004.

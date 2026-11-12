# 22 — Implementation status and evidence ledger

**Baseline date:** 2026-10-08. **Updated:** 2026-11-11.  
**Product state:** Staging integration candidate on branch `codex/checkpoint-recovered-focus-20261111` (PR #70) encompasses 299 commits across 70 pull requests with synthetic/offline verification through EM-013, candidate work on EM-014/EM-017, and isolated XML prototypes for EM-015. `main` currently hosts the normative design, schema contracts, and documentation baseline. See [Open Access strategic roadmap](25-open-access-strategic-roadmap.md) for target-market production plan.

## Documentation deliverables

Product charter, BRD, PRD, UX specification, architecture, tenant/RBAC design, connector/extraction specification, data model, proposed contracts, job lifecycle, security/privacy, deployment/operations, test benchmark, commercial/onboarding plan, backlog, traceability, ADRs, synthetic fixtures, open access strategic roadmap and Codex handoff are included in this baseline.

The repository documentation validator checks local Markdown targets, JSON syntax, schema/example consistency and requirement traceability as implemented by the script. It does not certify business viability, legal compliance, extraction precision or application security. Final publication verification belongs in the handoff report/commit history.

## Task ledger

| Task | Status | Evidence / next dependency |
|---|---|---|
| EM-001 | VERIFIED IN DRAFT PR | Staged in PR #1 / branch `feat/em-001-scaffold`; clean install/build/smoke and offline fixture harness verified. |
| EM-002 | VERIFIED IN DRAFT PR | Staged in PR #2 / branch `feat/em-002-tenant-foundation`; OIDC boundary, PostgreSQL runtime RLS and multi-tenant authorization verified. |
| EM-003 | VERIFIED IN DRAFT PR | Staged in PR #3 / branch `feat/em-003-source-policy`; source registry, fail-closed policy evaluation and synthetic governance verified. |
| EM-004 | VERIFIED IN DRAFT PR | Staged in PRs #4–#10 / branch `feat/em-004f-protected-transport`; SSRF prevention, synthetic DNS pinning, redirect restrictions and transport isolation verified. |
| EM-005 | VERIFIED IN DRAFT PR | Staged in PR #11 / branch `feat/em-005-durable-offline-jobs`; Celery/RabbitMQ transactional outbox, idempotent lease fencing, pause/cancel verified. |
| EM-006 | VERIFIED IN DRAFT PR | Staged in PR #12 / branch `feat/em-006-offline-discovery`; keyword/URL preflight, article URL deduplication and pagination caps verified. |
| EM-007 | VERIFIED IN DRAFT PR | Staged in PR #13 / branch `feat/em-007-offline-html-extraction`; HTML metadata, author role markers, ordinary tooltip and click-to-reveal verified. |
| EM-008 | VERIFIED IN DRAFT PR | Staged in PR #14 / branch `feat/em-008-offline-pdf-observations`; isolated synthetic PDF parser, standard fonts and layout regions verified without GPL/MuPDF. |
| EM-009 | VERIFIED IN DRAFT PR | Staged in PR #15, #64 / branch `feat/em-009-offline-associations`; deterministic candidate mapping, author-email evidence linking and audited unlink verified. |
| EM-010 | VERIFIED IN DRAFT PR | Staged in PR #16 / branch `feat/em-010-offline-progress`; durable counters, authorized SSE streams, resumable checkpoints and partial completeness verified. |
| EM-011 | VERIFIED IN DRAFT PR | Staged in PR #17, #53 / branch `feat/em-011-offline-results`; cursor pagination, cryptographic evidence digests and formula-safe CSV/XLSX exports verified. |
| EM-012 | VERIFIED IN DRAFT PR | Staged in PR #18 / branch `feat/em-012-offline-operator-ui`; full React/Vite operator SPA, keyboard navigation, evidence drawer and review screens verified. |
| EM-013 | VERIFIED IN DRAFT PR | Staged in PR #19 / branch `feat/em-013-offline-admission`; multi-tenant fair admission, shared throttles and quota enforcement verified. |
| EM-014 | CANDIDATE IN DRAFT PR | Staged in PRs #20, #60, #61; staged deletion, generation fences, contact suppression and audit logging implemented; automated vacuum review pending. |
| EM-015 | PARTIAL PROTOTYPE | Staged in PRs #21–#47; ScienceDirect XML parser and isolated Elsevier sample adapter prototyped; live Open Access connectors (Crossref/OpenAlex/Europe PMC) pending. |
| EM-016 | NOT STARTED | Test benchmark protocol defined in document 14; held-out publisher UAT pending live source connector integration. |
| EM-017 | CANDIDATE IN DRAFT PR | Staged in PRs #48, #51; packaging runbooks, synthetic backup restore exercises and disposable DB tests passing; production container deployment pending. |
| EM-018 | NOT STARTED | Commercial readiness, final license decision, and production release packaging pending PR #70 merge and UAT signoff. |
| OA-001 | VERIFIED IN DRAFT PR | Europe PMC JATS XML full-text gateway, cryptographic response digest and error boundaries verified in PR #71. |
| OA-002 | VERIFIED IN DRAFT PR | Deterministic JATS XML author, correspondence, and institutional affiliation parser verified in PR #71. |
| OA-003 | VERIFIED IN DRAFT PR | OpenAlex REST query planner, work parser, and JATS routing bridge verified in PR #71. |
| OA-004 | VERIFIED IN DRAFT PR | Instantly & Smartlead cold outreach presets, author recency scoring, and GDPR provenance verified in PR #71. |
| OA-005 | VERIFIED IN DRAFT PR | UI outreach export presets, configuration helpers, and filter alignment verified in PR #71. |
| OA-006 | VERIFIED IN DRAFT PR | Crossref REST connector, DOI query planner, and full-text resolver verified in PR #71. |
| OA-007 | VERIFIED IN DRAFT PR | Multi-source scholarly discovery orchestrator & enterprise UI/UX elevation (Navy/Amber, 2-column layout, compact disclosures) verified in PR #71. |
| OA-008 | VERIFIED IN DRAFT PR | bioRxiv & medRxiv pre-print REST connector, query planner, and early-stage manuscript discovery verified in PR #71. |
| OA-009 | VERIFIED IN DRAFT PR | ORCID ISO 7064 MOD 11-2 researcher checksum verification and institutional profile disambiguation verified in PR #71. |
| EM-EXT-01–05 | DEFERRED | Post-core extensions (OCR adapter, institutional enrichment, recurring searches, direct outreach). |

## What has been done vs what remains

- **Done in Draft Staging:** Complete modular FastAPI backend and React/Vite frontend implemented across 299 commits and 70 PRs. Core isolation, durability, extraction, and operator workflows pass synthetic/offline CI.
- **Pending Merge:** Resolving isolated Chromium headless CI runner flakiness before merging PR #70 into `main`.
- **Pending for Open Access Production:** Real-world Open Access API connectors (OpenAlex, Europe PMC JATS XML, Crossref), author recency scoring, deliverability checks, and cold outreach export presets.

## How implementers update this ledger

For each task add: state (Ready/In progress/Blocked/Partial/Done), PR and commit, implementation boundary, exact commands and observed results, relevant requirement/test IDs, migrations, remaining gaps and next ready task. Link to sanitized reports; keep real data and signed source/customer agreements outside this public repository.

Do not compute an arbitrary project completion percentage from number of documents or files. Report accepted task/milestone completion and pending critical gates instead.

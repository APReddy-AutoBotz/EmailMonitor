# 22 — Implementation status and evidence ledger

**Baseline date:** 2026-10-08. **Updated:** 2026-10-12. **Product state:** unmerged synthetic/offline backend foundations verified through protected fetch/sandbox and durable jobs; UI extraction and deployment unavailable.

## Documentation deliverables

Product charter, BRD, PRD, UX specification, architecture, tenant/RBAC design, connector/extraction specification, data model, proposed contracts, job lifecycle, security/privacy, deployment/operations, test benchmark, commercial/onboarding plan, backlog, traceability, ADRs, synthetic fixtures and Codex handoff are included in this baseline.

The repository documentation validator checks local Markdown targets, JSON syntax, schema/example consistency and requirement traceability as implemented by the script. It does not certify business viability, legal compliance, extraction precision or application security. Final publication verification belongs in the handoff report/commit history.

## Task ledger

| Task | Status | Evidence / next dependency |
|---|---|---|
| EM-001 | VERIFIED IN DRAFT PR — unmerged | [PR #1](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/1), head 88e34a7; independent review + [application CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38025740451) + [docs CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38025740436) passed |
| EM-002 | VERIFIED IN DRAFT PR — unmerged | [PR #2](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/2), head bed184b; corrected privilege-boundary review + [application CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38027802453) + [docs CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38027802418) passed; production provider unavailable |
| EM-003 | VERIFIED IN DRAFT PR — unmerged | [PR #3](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/3), head 0800137; corrected exact-tree review + [application CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38028911796) + [docs CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38028911825) passed; no live approval/execution |
| EM-004 | VERIFIED SYNTHETIC/OFFLINE FOUNDATION IN DRAFT — unmerged | [PR #4](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/4), head 0a3fa6b, retains its [offline evidence](../reports/em004a-validation.md). [PR #6](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/6), head 3f6c96b/tree 5706432f, passed corrected independent review, [application CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38047608099) with 226 Python tests/no skips (two field-alias warnings disclosed), [docs CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38047608092) and [actual parser network/OOM CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38047608171); [EM-004b evidence](../reports/em004b-validation.md). [PR #7](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/7), head 99d700ea/tree f1a88580, passed independent review, [application264/no-skip CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38199138262), [actual synthetic browser CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38199138241), [parser network/OOM CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38199138261) and [docs CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38199138250); [EM-004c evidence](../reports/em004c-validation.md). [PR #8](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/8), head 046fc6db/tree 4df3ca05, passed independent review, [291-test/no-skip application CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38200690403), [actual DNS-gated browser CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38200690352), [parser CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38200690478) and [docs CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38200690366); [EM-004d synthetic DNS/pinning evidence](../reports/em004d-validation.md); [PR #9](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/9), head 5ee5712d/tree 536ec48e, passed independent review and [333-test/no-skip application CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38202490798), [docs](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38202490797), unchanged [browser](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38202490683) and [parser](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38202490718) CI; [EM-004e shared network-free planner](../reports/em004e-validation.md) is verified as preparation only; EM-004f head2c29a8ad/tree3cd450db passed corrected independent source and exact-head evidence review, [application477/no-skip](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38283756495) with one disclosed organization_id field-alias warning, [controlled12/no-skip/no-warning](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38283756291), [browser](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38283756393), [parser](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38283756483) and [docs](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38283756465). Document16 synthetic/offline criteria are verified; live-source/production acceptance is not claimed; documentation checkpoint requires its own CI before bounded offline EM-006 begins |
| EM-005 | VERIFIED OFFLINE FOUNDATION IN DRAFT PR — unmerged | [PR #5](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/5), head 1abaa3a/tree 62ff0a17; corrected independent review; [application CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38046354505) passed 196 Python tests, including four real-broker tests, no skips; [docs CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38046354454) passed; live acquisition remains disabled; bounded offline discovery can compose the verified EM-004 foundation |
| EM-006 | READY OFFLINE AFTER CHECKPOINT CI | EM-004/005 synthetic/offline foundations verified; bounded documented discovery only |
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

Draft original-input requests, synthetic diagnostic job/item ledger, forced tenant RLS, deterministic effects, transactional outbox, leases/attempt bounds, quota reservations/settlement, recovery, pause/cancel and organization deletion epochs are implemented for testing. Celery and immutable official disposable RabbitMQ CI are pinned. Local and clean-install/from-empty aggregate passed 191 Python tests and all other gates, with four explicitly pending actual-broker tests. That original candidate was subsequently corrected and independently reviewed: PR #5 head1abaa3a/tree62ff0a17 passed196 application tests/no skips, including four actual broker failure/recovery tests, as linked in the table above. No extraction result or production worker identity is claimed; Bounded offline EM-006 can proceed after the verified EM-004 checkpoint CI; live execution remains disabled.

## Historical EM-004f controlled transport candidate (2026-10-12)

IN PROGRESS, full EM-004 PARTIAL: shared planner-backed actual DNS/literal socket/TLS transport and a separately constrained disposable dual-stack CI topology with owned-pipe current SQL tenant/browser mediation. Reviewed head7b4fb2ab/tree d5d1f2f passed475 application tests/no skips (one Pydantic alias-body warning disclosed),12 actual transport cases/no skips or warnings, browser/parser/docs. Exact IPv4/IPv6 peers, redirect-selected peer change,15 bounded guest negative-connect receipts and strict unfiltered cleanup are established within the synthetic boundary. Browser test HTTPS/DNS receipts passed, but its final printed selected-peer list was erased by later denials. A bounded immutable successful-receipt correction and explicit two-peer assertion require new-head application477/no-skip, controlled12/no-skip/no-warning and all existing gates plus independent review before final backlog acceptance assessment. No local network/container execution, production/live activation, dependencies or database migration. [Runbook](34-controlled-transport-acceptance.md) / [evidence](../reports/em004f-validation.md). EM-006 remains gated during that reconciliation; no extraction/deployment/benchmark prerequisites are added to EM-004.


## EM-004 synthetic/offline acceptance checkpoint (2026-10-12)

VERIFIED IN DRAFT, unmerged: independently reviewed source head2c29a8ada7ade0759f5deed6aad4c639e84137ab/tree3cd450dbbf574069c6a122b77ab62b5fb591a3e6 and merge dd99bf85bcab762a14832f2542215bb846e36443 have exact verified base/head parents. Independent evidence reconciliation read all five actual run/job logs and mapped document16 EM-004 criteria with no remaining scoped criterion: URL/DNS/IP/connection/redirect/size/time restrictions, approved-domain HTTP/browser mediation, isolated network-free parser, SSRF/rebinding/IPv6/subresource/credential refusal and no evasive retries. Controlled12 passed with exactly two successful browser-selected peers, current SQL tenant/cross-org/stale/revoked-policy checks,15 bounded negative-connect receipts and strict owned cleanup. Application477 passed without skips and with one disclosed Pydantic alias-organization_id warning; browser/parser/docs passed. [Full evidence](../reports/em004f-validation.md).

This verifies the synthetic/offline protected-fetch and sandbox foundation, not live-source or production enablement. Those entrypoints still fail closed. No extraction accuracy, PDF adapter, source certification, deployment or benchmark claim is implied; those belong to their documented later tasks. The documentation-only checkpoint requires its own exact-head CI. Once it passes, EM-006 is ready for input modes, explicit spelling suggestions, page classification/preflight, bounded two-page fixture discovery, dedup/checkpoints/caps and truthful completeness. API fallback must remain labeled. No whole-domain crawl or live source access is authorized.

Tracked compatibility caveat EM-WARN-01: concurrent last-owner-removal CI has emitted Pydantic field-alias metadata warnings (this accepted head: organization_id; earlier head: body). Relevant tenant regressions pass and no EM-004 boundary failure was demonstrated. Disclose rather than suppress; investigate during normal API compatibility maintenance. This caveat does not substitute for security or production-readiness review.

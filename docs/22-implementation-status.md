# 22 — Implementation status and evidence ledger

Saved draft continuation is an independent local candidate based on PR60. It
exposes existing plan/start controls for the same reopened draft, with current
revision/generation/session binding. [Scope](83-saved-draft-continuation.md).
Normal/fresh and hosted acceptance are separate pending gates; PR61's installed
XML failure and historical intermittency remain unresolved.

**Baseline date:** 2026-10-08. **Updated:** 2026-10-13. **Product state:** unmerged synthetic/offline foundations verified through scoped operator UI and shared admission; live/production deployment unavailable.

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
| EM-006 | VERIFIED SYNTHETIC/OFFLINE FOUNDATION IN DRAFT — unmerged | [PR11](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/11), head3bc8f234/tree80431dfb, independently reconciled against document16/document06; application543/no skips/no pytest warnings, actual SQL/RabbitMQ/parser plus controlled12/browser/docs pass; [evidence](../reports/em006-validation.md). This documentation checkpoint requires its own exact-head CI |
| EM-007 | VERIFIED SYNTHETIC/OFFLINE FOUNDATION IN DRAFT — unmerged | [PR #12](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/12), head 98208a9a / tree 4c58b53a, independently reconciled against document 16/document 07; application 599/no skips/no pytest warnings, eleven new runtime SQL cases, controlled 12 with actual tooltip persistence/replay, browser/parser/docs pass; [evidence](../reports/em007-validation.md). This documentation checkpoint requires its own exact-head CI |
| EM-008 | VERIFIED SYNTHETIC/OFFLINE FOUNDATION IN DRAFT — unmerged | [PR #13](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/13), head 5e6568dc / tree 99f0257f, independently reconciled against document 16/document 07; application 664/no skips/no pytest warnings, actual nine-PDF parser/resource/network/OOM plus controlled 12/browser/docs pass; [evidence](../reports/em008-validation.md). This documentation checkpoint requires its own exact-head CI |
| EM-009 | VERIFIED SYNTHETIC/OFFLINE FOUNDATION IN DRAFT — unmerged | [PR14](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/14), head beae5deb/tree a3ea255d; independent authoritative acceptance reconciliation; application748/no skips/one disclosed alias-body warning,20 actual association SQL cases and controlled12/browser/parser/docs pass; [validation](../reports/em009-validation.md). This documentation checkpoint requires its own exact-head CI before EM-010 |
| EM-010 | VERIFIED SYNTHETIC/OFFLINE FOUNDATION IN DRAFT — unmerged | [PR15](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/15), head16bb590e/tree58a708d8; independent authoritative acceptance reconciliation; application862/no skips/no pytest warning summary,22 actual progress SQL/four real-broker cases, controlled12 with durable browser completion and browser/parser/docs pass; [validation](../reports/em010-validation.md). This checkpoint requires its own exact-head CI before EM-011 |
| EM-011 | VERIFIED SYNTHETIC/OFFLINE FOUNDATION IN DRAFT — unmerged | [PR16](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/16), reviewed treeca84f013 implementation1035/no skips and all-five CI; documentation checkpoint head9fd9fbeb/treeee54a2b3 passed its own1035/no-skip application and controlled12/browser/parser/docs; [evidence](../reports/em012-validation.md) |
| EM-012 | VERIFIED SYNTHETIC/OFFLINE FOUNDATION IN DRAFT — unmerged | [PR17](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/17), head6a3c607c/treea513d96c; independently reconciled1132/no-skip application/one alias-body warning, actual keyboard UI1, controlled12/browser/parser/docs; [evidence](../reports/em012-validation.md). This checkpoint requires its own six exact-head gates before EM-013 |
| EM-013 | VERIFIED SYNTHETIC/OFFLINE FOUNDATION IN DRAFT — unmerged | [PR18](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/18), head216a8c3b/treebb37d8e7; independently reconciled1267/no-skip application, controlled13, actual keyboard UI1/browser/parser/docs; [evidence](../reports/em013-validation.md). Own six checkpoint gates required before EM-014 |
| EM-014 | VERIFIED SYNTHETIC/OFFLINE FOUNDATION IN DRAFT — unmerged | [PR19](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/19), head73a1043f/tree73dea867; independently reconciled1386/no-skip application/one alias-batch_id warning, controlled14, actual keyboardUI1/browser/parser/docs; [evidence](../reports/em014-validation.md). Own six checkpoint gates and genuine source inputs required before EM-015 |
| EM-015 | PARTIAL — disabled provider-binding prerequisite candidate | Synthetic isolated XML pipeline accepted in Draft PR25; canonical request/response binding and generalized parser protocol under review. Live acquisition/source certification remain unmet; see [runbook49](49-disabled-provider-binding.md) |
| EM-016 | NOT STARTED | EM-012/015 and authorized benchmark |
| EM-017 | IN PROGRESS — PARTIAL synthetic restore candidate | Quiesced same-version disposable dump/restore and current privacy replay under review; actual CI pending. No staging/deployment or production RPO/RTO. [Runbook](44-synthetic-restore-exercise.md) / [evidence](../reports/em017a-validation.md) |
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

## Historical EM-006 synthetic discovery candidate (2026-10-12)

Original-input planning, explicit spelling confirmation, fixture page classification, bounded search parsing, durable page/frontier checkpoints and identifier-only successor outbox are implemented in a test-only candidate. The initial PR11 actual application ran540 tests without skips:538 passed and two stale-policy outbox selection cases failed; controlled12/docs passed, parser image build and browser aggregate positive evidence failed. A bounded current-policy dispatch filter, exact two-fixture context allowlist and actual popup/download completion observation are corrected locally. Latest normal/fresh aggregate471 passed/72 explicit service skips/all gates; focused discovery/parser/browser diagnostics48 passed. Required corrected new-head application543/no skips, PostgreSQL, RabbitMQ restart/duplicate and network-none parser evidence remain pending. No extraction/contact result or production source request is claimed. Migration 0004 and test API/worker boundaries are described in the [runbook](35-offline-discovery-runbook.md) and [validation report](../reports/em006-validation.md). EM-007 remains gated on this candidate review/CI.

## EM-006 synthetic/offline acceptance checkpoint (2026-10-12)

VERIFIED IN DRAFT, unmerged: head3bc8f2340dbbd5ac5969438c2e765f7e6c0a4e9c and merge345011364bd172aafe3a01b4edce9e971da870aa share independently reviewed tree80431dfbc414c40b69bae3b350f1c72d64f3b474, with exact c5844ecf/3bc8f234 parents. Independent evidence review fetched all five actual run/job logs and found no unmet document16/document06 criterion for this synthetic/offline slice. Application543 passed without skips or pytest warnings, including17 discovery SQL tests and actual RabbitMQ worker restart/duplicate delivery. Controlled12, browser, network-none discovery parser/OOM and docs passed. [Evidence](../reports/em006-validation.md).

This verifies bounded original-input planning and durable authored-fixture discovery, not contact extraction or live-source/production acceptance. Unsupported PDF/DOI/filter paths and unavailable API fallback remain explicit. Runner Node20 deprecation notices exist; this run does not establish a cause fix for tracked EM-WARN-01. Once this documentation-only checkpoint passes its own exact-head CI, bounded offline EM-007 can implement metadata/author-role/contact observations and ordinary approved tooltip interactions from authored fixtures; live enablement remains unavailable.

## EM-007 synthetic observation candidate (2026-10-12)

In progress: inert article metadata/author/role/contact observations and fixed ordinary tooltip plan, separate from accepted identity/validation/outreach. Tenant observation persistence is restricted to the discovered authored frontier, current source/purpose/collection permission and bounded retention; SQL/browser acceptance remains pending. Migration 0005 adds forced-RLS observations without authentication/runtime privilege expansion. No live source, production or UI extraction activation. [Evidence](../reports/em007-validation.md).

## EM-007 synthetic/offline acceptance checkpoint (2026-10-12)

VERIFIED IN DRAFT, unmerged: head 98208a9a7aa7584c69de55c61debdb92190b8e88 and merge fe43d40c606d467f5a019c86afcae329a0c7b6e0 share independently reviewed tree 4c58b53a5b70d4305d3bc4642304ea32b05b16f0, with exact f4e5db8f/98208a9a parents. Independent evidence review fetched all five actual run/job logs and found no unmet document 16 EM-007/document 07 criterion for this scoped synthetic/offline foundation. Application 599 passed without skips or pytest warnings, including all eleven new runtime SQL cases. Controlled 12 verified actual authored tooltip hover/DOM observation persistence and replay with current tenant/source authority, cross-tenant refusal and post-revocation denial. Actual browser, four-article network-none parser/OOM and docs passed. [Evidence](../reports/em007-validation.md).

This verifies observed metadata, ordered author-role facts and scoped raw-address evidence. It does not establish accepted associations, technical email validation, outreach eligibility, UI integration, universal-source extraction or production/live activation. Historical failed cancellation setup and Pydantic alias warning remain disclosed; the warning-free current pytest run does not close EM-WARN-01. Runner/service warnings remain separate. After this documentation-only checkpoint passes its own exact-head CI, bounded offline EM-008 may implement reviewed text/layout PDF observations and explicit unsupported outcomes without OCR or a default MuPDF dependency.

## EM-008 synthetic/offline acceptance checkpoint (2026-10-12)

VERIFIED IN DRAFT, unmerged: head 5e6568dc807ab094827db7ff195275e214ad82b9 and merge a9d584d01a7b5de03cab50d66077981f0ae8fc3f share independently reviewed tree 99f0257fc513646e51b17a0faaa08a0424791872, with exact 26622480/5e6568dc parents. Independent evidence review fetched all five actual run/job logs and found no unmet document 16 EM-008/document 07 criterion for the declared standard-font/simple-Tj/coarse-region synthetic byte-parser foundation. Application 664 passed without skips or pytest warnings. Parser CI executed all nine authored PDF digests/outcomes, page/region and correspondence assertions, byte/decoded-stream caps, network-none lo/ENETUNREACH for both families and actual stopped/OOMKilled true/137. Controlled 12, existing browser and docs passed. [Immutable evidence and limitations](../reports/em008-validation.md).

This does not establish generalized PDF acquisition, universal layout coverage, exact glyph boxes, OCR, password workflows, accepted associations or live/production activation. The source-review text-state finding and conservative refusal correction remain recorded. Runner/service notices are separate from pytest warnings; EM-WARN-01 remains open. After this documentation-only checkpoint passes its own exact-head CI, bounded offline EM-009 may implement evidence-backed association, normalization and review under existing tenant/source permissions.

## EM-009 offline candidate

Source-backed deterministic HTML/PDF mapping, conservative normalization, per-batch tenant deduplication and atomic relational review are implemented locally. Persisted derivation uses existing authorized HTML/browser observations only. Forced RLS/current permission/retention/deletion fences and optimistic review history/audit/outbox require actual PostgreSQL CI; locally skipped services are not acceptance. No production, mailbox checks, export or UI activation. Migration 0006 is forward-only. Independent exact-tree review and all five actual CI gates remain pending; EM-010 is gated.

## EM-009 synthetic/offline acceptance checkpoint

VERIFIED IN DRAFT, unmerged: independently reviewed head beae5deba01673609534178202dde31b464705a6 and merge0073291d2aa797a11f6250cc41705ea925fc77a0 share treea3ea255ddbda34999f49ccaef21b20da859c0ab9 with exact790e40cd/beae5deb parents. Independent review fetched all five authoritative job logs and mapped document16 EM-009/document07/08/09/05 with no unmet scoped criterion. Application748 passed/no skips, including20 actual association PostgreSQL cases and existing broker tests; one existing alias-body warning remains disclosed. Controlled12, actual browser/parser/docs passed.

This verifies deterministic source-backed association, conservative normalization, relational tenant/batch provenance/dedup and optimistic atomic review foundation. It does not establish a global person registry, generalized PDF persistence/acquisition, delivered review events, mailbox/outreach/export/UI or live/production activation. EM-WARN-01 remains open. After this documentation-only checkpoint passes its own exact-head gates, EM-010 may implement durable truthful progress, authorized replay/SSE and resumability within the synthetic/offline boundary.

## EM-010 offline candidate (2026-10-13)

The independently reviewed EM-009 documentation checkpoint passed its own exact-head five CI gates, including748/no-skip application and controlled12. [Checkpoint identities and runs](../reports/em010-validation.md). Bounded synthetic execution/progress implementation is now a local candidate: real job transitions, current per-item leases, durable metadata/outbox/effects, pause/resume/cancel/continuation, truthful counters and tenant-bound SSE. Source review and actual PostgreSQL/broker/isolated browser acceptance remain pending; no production/UI activation. [Runbook](39-offline-progress-runbook.md). EM-011 is gated.

## EM-010 synthetic/offline acceptance checkpoint (2026-10-13)

VERIFIED IN DRAFT, unmerged: independently reviewed head16bb590e2ba2c61b8e8e48ef60452dfe2e4f6ff7 and merge7a2130b09e0f67b8ed25ffd41e5cb9e58ba24f7c share tree58a708d8ce3c5e8a1a7f10d05e7b38991313b33d with exact7ebee149/16bb590e parents. Independent review fetched all five authoritative job logs and mapped document16 EM-010/document10 to the declared runbook39 scope without an unmet criterion. Application862 passed/no skips/no pytest warning summary in209.85s, including22 actual progress PostgreSQL and four real-broker cases. Controlled12 passed58.38s with actual durable tooltip item/job completion; browser/parser/docs passed. [Exact evidence and correction history](../reports/em010-validation.md).

This verifies bounded fixture lifecycle, current leases/generation/deletion fences, atomic checkpoint/outbox/effect recovery, conserved truthful outcomes, auditable continuation, inherited-review invalidation and current-authorized SSE replay. Static browser-unavailable work remains an explicit partial gap; actual supported controlled browser work has separate durable proof. UI, commercial fairness/quota activation, generalized acquisition, live sources and production remain outside this scope. EM-WARN-01 cause remains open; runner/service notices are not pytest warnings. Bounded offline EM-011 may proceed only after this documentation-only checkpoint passes its own five exact-head gates.

## EM-011 offline candidate (historical snapshot, 2026-10-13)

The EM-010 documentation checkpoint passed its own862/no-skip application and controlled12/browser/parser/docs at exact headfe66f7a7/tree1d16ad49, closing this dependency gate. Filtered results/evidence APIs and private async export snapshots are a local candidate. Contacts/outcomes, accepted associations, technical status and outreach eligibility remain distinct. Export-capable roles/current purpose/source/revisions/expiry are checked at creation, claim, commit and download; conservative CSV refusal and literal XLSX cells prevent formula execution. Actual SQL/broker and all existing isolation gates remain pending. [Evidence](../reports/em011-validation.md). EM-012 is gated on scoped EM-011 acceptance.


### EM-011 first published-head validation (historical snapshot)

Draft PR16 headfc5fe611/tree510b387 passed actual1008/no-skip application (18 results PostgreSQL/four broker cases), browser, parser and docs at exact merge2ea2c24. Controlled transport12 failed before transport because precisely owned IPv6 host-veth addresses were still tentative; full cleanup equality passed. The read-only DAD-readiness repair preserves all isolation/settings/baseline controls and awaits its own application1035/no-skip plus controlled12/browser/parser/docs gates. EM-011 is not yet accepted; EM-012 remains gated. [Current evidence](../reports/em011-validation.md).


## EM-011 synthetic/offline acceptance checkpoint (2026-10-13)

VERIFIED IN DRAFT, unmerged: independent authoritative review verified head660e0dc5 and merge45377b5 share reviewed treeca84f013, exactfe66f7a7/660e0dc5 parents, and all five complete job logs. Application1035 passed/no skips/one disclosed EM-WARN-01 alias warning in214.27s, including18 actual results PostgreSQL/four broker cases; controlled12 passed70.08s with real tenant/pinning/durable browser/cleanup proof. Browser/parser/docs passed. [Exact evidence and history](../reports/em011-validation.md).

This verifies runbook40's bounded current-authorized results, accepted-only default immutable snapshots, conservative CSV/literal XLSX and fresh authenticated expiry/revision/revocation/deletion download fences. UI, field-selection preview, external event delivery, global dedup, lifecycle purge and live/production activation remain later scope. EM-WARN-01 cause remains open. Bounded offline EM-012 may proceed only after this documentation checkpoint passes its own1035/no-skip application and controlled12/browser/parser/docs gates.

## EM-012 operator UI candidate (2026-10-13)

The scoped EM-011 documentation checkpoint passed its own five exact-head gates, closing this dependency. Actual React screens and current-authorized session/profile/usage/audit/export preview support are now a local synthetic candidate. Migration0009 adds bounded export options/preview without role, RLS or authentication grant expansion. The restrictive keyboard harness uses unchanged network-none Chromium settings and actual ASGI/PG/outbox/broker worker; its execution remains pending. [Runbook41](41-offline-operator-ui-runbook.md), [evidence](../reports/em012-validation.md). Independent exact-tree source review and six actual CI gates, including the new keyboard UI job, are required. EM-013 remains gated; live/production/deployment and incomplete product features remain unavailable.


## EM-012 synthetic/offline acceptance checkpoint (2026-10-13)

Independent authoritative reconciliation verified head6a3c607c/merge8d2ad475/reviewed treea513d96c, exact9fd9fbeb+6a3c607c parents, Draft/open/unmerged status and all six full successful job logs. Application1132/no skips/one disclosed alias-body warning284.57s includes ten actual operator PostgreSQL cases. Keyboard UI1/64.12s verifies actual assets/ASGI/PG/broker,5 effects/1 review/4471-byte export, native focus, both inputs, partial/no-contact/empty/stale retry, roles and late-tenant response/replay refusal. Controlled12/56.92s plus browser/parser/docs pass. [Evidence and failure history](../reports/em012-validation.md).

This verifies runbook41's declared synthetic operator scope. Real IdP callback/live sources/production/static browser acquisition, native SSE latency and a disk-saved download remain unproven; EM-WARN-01 cause stays open. Bounded synthetic EM-013 may proceed after this documentation checkpoint's own1132/no-skip application and all six exact-head gates. No merge or deployment acceptance is implied.


## EM-013 synthetic admission candidate (2026-10-13)

The EM-012 reviewed checkpoint passed its own six exact-head gates. Migration0010 and the candidate API/worker/protected-hop/UI integration now cover shared tenant/source admission, separate supported phase queues, root-job/article reservation/settlement, owner limits and bounded branding/support metadata. Actual protected network attempts are distinct from authored file reads and resolution units. Existing security/topology/profile/cleanup controls remain in force. [Runbook42](42-offline-admission-runbook.md), [evidence](../reports/em013-validation.md). Normal/fresh checks, independent exact-tree review and actual application/controlled13/browser/parser/docs/operator-UI gates must complete before scoped acceptance; EM-014 remains gated. This is synthetic/offline work in Draft, not live/production or billing enablement.


## EM-013 independently verified synthetic admission foundation

Head216a8c3b/treebb37d8e7 and merge84673c51 passed all six exact-head gates after independent source/evidence reconciliation: application1267/no skips/no pytest warnings285.99s; controlled13/79.00s; keyboard UI1/63.66s plus browser/parser/docs. Actual source contention/spacing, other-tenant four-unit/private-export progress, fair claims, separate consumers, once-only usage across retries/recovery and current owner/source/entitlement boundaries satisfy scoped document16 acceptance. [Evidence](../reports/em013-validation.md) preserves failures and limits. EM-WARN-01 and prior intermittent UI route-error cause remain open. Live/production/billing/exceptional support grants/lifecycle purge are excluded. Bounded synthetic EM-014 may proceed after this checkpoint's own1267/no-skip application and all six gates; no merge/deployment is implied.


The EM-013 documentation checkpoint head5ff0daad retained failed browser readiness/UI wait_jobs own gates despite controlled/parser/docs success. Bounded readiness cancellation and fixed job-state-count diagnostics are in progress; the next reviewed exact head must pass all six gates before EM-014. Historical implementation acceptance remains scope-qualified and does not waive these refusals; [report](../reports/em013-validation.md).


## EM-013 checkpoint-own closure and EM-014 candidate

Independent authoritative reconciliation closed all six own-head gates at845df581/tree3c3a0fa6/merge239c470c:1285/no-skip application, controlled13, actualUI1 and browser/parser/docs. Exact receipts are recorded in [EM-014 report](../reports/em014-validation.md); bounded offline EM-014 is now dependency-ready. Earlier intermittent causes and EM-WARN-01 remain open/unproven.

EM-014 is IN PROGRESS: private tenant-keyed suppressions, current retention/tombstone RLS, staged synthetic purge/artifact invalidation, bounded scheduled sweeps and audited existing-member metadata support. [Runbook43](43-offline-lifecycle-runbook.md) records scope/rollback/restore limits. Corrected normal/empty-install checks pass1131/218 explicit skips21.29s/24.68s,28 React tests and all static/docs/inventory/build gates. Independent exact-tree review and all six actual own-head gates remain pending, including1349/no-skip application and controlled14; no real purge, external grant, live/production enablement or acceptance is claimed.

Independent EM-014 review corrections address support identity locking, SQL privacy grammar parity, final source/privacy organization serialization and precise residual purge metadata. Held-transaction regressions remain actual-PG CI requirements; the corrected exact tree must be independently cleared before publication.

EM-014 first Draft PR19 actual checkpoint failed: application1246/103 plus disclosed alias warning, controlled11/3 and UI failure; browser/parser/docs succeeded. SQL deadline alias and three fixture/test argument corrections are locally checked1133/21822.10s normal/24.38s empty-install with28React/full gates; independent corrected review and actual1351/no-skip/controlled14/all six gates remain pending. [Report](../reports/em014-validation.md) preserves exact failure evidence; no acceptance is inferred.

EM-014 second actual checkpoint: controlled14/82.44s proves receipt-backed deletion-before-release; browser/parser/docs passed. Application1343/8 failed and UI header callback failed. Refusal-contract tests, canonical JSON UUID decoding and fixed fail-closed header diagnostics are corrected locally1143/21822.01s normal/25.75s empty-install,28React/full gates. Separate exact-tree reviews and actual1361/no-skip/all six gates remain mandatory; [failure evidence](../reports/em014-validation.md).


EM-014 third actual checkpoint: application1360/1 failed489.70s due to a fixture-disabled HTTP test client; controlled14/83.69s and browser/parser/docs passed, UI still failed with fixed unclassified RuntimeError. Correction reuses the existing fixture-enabled test client and adds closed fail-closed driver-boundary classifications without runtime permission/security/cap changes. Final normal1152/21822.37s and genuinely empty1152/21824.08s pass28React/full gates; exact-tree review and actual1370/no-skip/all six gates remain pending; [evidence](../reports/em014-validation.md). UI cause and historical EM-WARN-01 remain unproven/open.


EM-014 fourth checkpoint application1370/no skips/no pytest warning summary344.80s and four other gates passed; UI failed the unchanged8s completion assertion with three published/unattempted articles pending. Timeout-only passive owned parse-queue counts use a fixed500ms child-process deadline/no retry and worker-live status, preserving completion/deadline/security predicates; cause remains unproven. The socket-only candidate is superseded after a diagnostic-bound finding; normal1164/21822.64s and genuinely empty1164/21824.48s pass28React/full gates; exact-tree review and actual1382/no-skip/six gates remain pending; [evidence](../reports/em014-validation.md).


EM-014 current diagnostic run again failed UI aturl_worker before timeout queue evidence. Pinned internal rawRequestHeaders calls produce the exact ': ' error prefix; a bounded classifier correction covers it with installed-source positive and nested/unknown-prefix negative regressions, preserving failure/rethrow and all caps. Normal1166/21822.10s and genuinely empty1166/21825.47s pass28React/full gates; exact-tree review and actual1384/no-skip/six own-head gates remain pending; [report](../reports/em014-validation.md).


EM-014 actual UI now identifies the owned combined rpc_capacity refusal. A diagnostic-only split distinguishes the unchanged512 request cap from16 admitted cap, with actual Channel-body pure regressions and conserved cleanup; no frontend/cap/deadline change is inferred before the branch is known. Normal1168/21822.57s and genuinely empty1168/21825.31s pass28React/full gates; exact-tree review and actual1386/no-skip/six own-head gates remain pending; [evidence](../reports/em014-validation.md).


EM-014 latest UI failure reachesempty_contacts and identifies the unchanged16-admitted guard in owned source frames. A bounded250ms keyboard-search coalescing correction keeps immediate input feedback, hides pending-filter contact data and cancels old-scope timers; pure scheduler checks do not substitute for actual UI evidence. Normal1168/21822.95s and genuinely empty1168/21824.77s pass31React/full gates; exact-tree review and actual1386/no-skip/31frontend/six own-head gates remain pending; [report](../reports/em014-validation.md).


## EM-014 independently verified synthetic lifecycle foundation

Independent raw Git/all-six-job reconciliation supports scoped VERIFIED IN DRAFT at73a1043f/tree73dea867/merge9ac9b930, exact845df581+73a1043f parents. Application1386/no skips/one alias-batch_id warning471.50s includes30 actual lifecycle SQL and one real broker tick; controlled14/96.03s proves receipt-backed deletion before release, UI1/64.85s proves actual PG/broker keyboard workflow and4478-byte private export, browser/parser/docs passed. [Report](../reports/em014-validation.md) preserves source findings, failed checkpoints, corrections and exclusions. EM-WARN-01 and unrelated intermittent causes remain open. This documentation checkpoint requires its own six exact-head gates; EM-015 additionally needs genuine source/permission/access/usage/retention/certification inputs. No merge, real purge, external support grant, actual backup restore or live/production enablement is implied.


EM-014 documentation checkpoint own application gate failed1385/1 after its mutating broker completion observer collided with the worker's intended organization NOWAIT fence; five other gates passed. A test-only read-only committed-tick observer retains exactly-one purge, duplicate delivery and post-worker current-scope assertions. Prior scoped implementation evidence remains verified, but checkpoint closure is pending corrected normal/fresh/review and actual1387/no-skip/six gates; [report](../reports/em014-validation.md). No runtime or security change.


## EM-017a partial synthetic restore candidate

The EM-014 own-gate loop closed atc62efa1a/tree30a9c0ed/mergebf60a1a8 after a reviewed test-only read-only broker observer correction: independently verified1387/no-skip application/one alias-identifier warning473.07s, controlled14/81.68s, actual keyboardUI1/76.70s and browser/parser/docs. PR19 remains Draft/unmerged; no redundant checkpoint is required. Historical EM-WARN-01 remains open.

A dependency-ready partial EM-017 exercise now targets the existing disposable PostgreSQL service only: same-version custom dump/restore, coherent current privacy/tombstone/same-version source revocation before restored reads, sealed closed readiness, two-tenant RLS, physical no-resurrection, artifact hash/refusal, accounting and broker-from-ledger checks. Pure tests are not restore evidence. Corrected normal1213/21923.10s and genuinely empty1213/21924.07s plus31React/full local gates pass; independent source review is clear. Initial published headf7bce557/treeff583df8 passed actual1432/no skips/one disclosed alias warning and all six gates. A recap-visibility correction passes normal1214/21921.35s/fresh1214/21923.88s+31React; new-head1433/no-skip/six gates and numeric exercise evidence remain pending; [report](../reports/em017a-validation.md). No application migration, live source, new dependency/access/network/security setting, paid staging or deployment is introduced; production RPO/RTO and generalized newer-history recovery remain unmet. EM-015/016 input gates are unchanged.

## EM-017b metadata packaging prerequisite candidate

EM-017 remains IN PROGRESS / PARTIAL. PR20's bounded restore exercise closed its own six exact-head gates at9ae41b2e/tree35c5b5c6, with actual1433/no skips and10.475s disposable exercise; final PR body records the receipts and the unresolved UI attempt1 cause. A separate bounded packaging prerequisite now prepares deterministic engineering archives/contexts and two metadata-only image builds using existing pins. The default metadata library and separate migration/static assets are not the working extraction service. Independent source review corrected archive provenance validation;70focused cases pass. Final normal1284/219 explicit service skips21.79s and genuine empty1284/21924.04s pass31React/full local gates; independent source review is clear. Initial PR21 packaging refused before Docker because uv build suffix was rejected; strict numeric-pin parsing is corrected with80focused cases. Corrected normal1294/21922.60s and genuinely empty1294/21924.41s pass31React/full gates; independent corrected source review is clear. The corrected packaging build/profile passed but first smoke exited nonzero with stderr suppressed; a bounded fixed-reason diagnostic is added,85focused cases pass. Diagnostic-head normal1299/21921.65s and genuine empty1299/21924.31s pass31React/full gates; source review/parity are clear. Actual diagnostic identified the pinned-base /usr/local/bin/python3 interpreter link; only that exact digest-link target is added with92focused cases. Unchanged parser strict OOM evidence failed on diagnostic head and remains unproven. Interpreter-head normal1306/21922.86s and genuine empty1306/21925.05s pass31React/full gates; source review/parity are clear. Actual1525/no-skip application and all seven new-head CI gates remain pending; [runbook](45-offline-packaging-prerequisite.md), [report](../reports/em017b-validation.md). No new dependency, migration, live source, credential, security setting, registry release or deployment. EM-015/016 inputs and full EM-017/018 acceptance remain unmet.

## EM-015a ScienceDirect adapter prerequisite candidate (2026-10-15)

ScienceDirect is the selected first publisher. A local disabled-by-default V2 query/request contract, DOI/PII normalization, bounded metadata parser and pure pagination implementation has passed independent scoped review and local normal/fresh Python gates: 1404 passes/219 explicit service skips in21.90s/22.52s plus31React and full static/docs/inventory/build checks. Exact-head service/isolation/packaging CI is still pending. It parses source-shaped bytes rather than authored HTML and preserves row evidence, ordered authors and explicit unavailable-contact status. It is not live extraction or full EM-015 acceptance. Existing live refusals and tenant/source controls are unchanged. Independent review corrections and actual evidence are in [report](../reports/em015a-validation.md); capabilities, missing integration and live gates are in [runbook46](46-sciencedirect-adapter-prerequisite.md). No new dependency, migration, credential, registration, deployment or merge.

## EM-015b bounded XML contact observation candidate (2026-10-15)

The preceding EM-015a checkpoint closed in Draft PR22 at remote head34bc32e60d86715299a8610a5936486805ba33b4/tree1b0a4955aa9c68360635a6b7161dd65e1cdf6476; its final PR body is the accepted all-seven-gate record, including1623 application/no skips. Earlier pending entries are historical.

EM-015 remains PARTIAL. A separate inert journal-head XML parser now produces ordered first/corresponding author, literal published email and affiliation observations with digest/positional evidence, existing separated fact states and explicit unsupported outcomes. The official native XOCS profile is documented; the Article Retrieval wrapper namespace is a compatibility assumption pending actual approved XML verification. Focused106 tests pass; independent source review cleared after two provenance/outcome fixes. Final normal and genuinely new empty-Python aggregates pass1510/219 explicit service skips in22.05s/23.19s plus31React and all static/docs/inventory/build gates. Own exact-head CI remains pending; local service skips are not acceptance. [Runbook47](47-sciencedirect-xml-observations.md) / [evidence](../reports/em015b-validation.md). No new dependency, migration, transport, tenant persistence, source activation, credential, isolated XML runtime acceptance, deployment or merge.

## Bounded acceptance cleanup/diagnostic candidate (2026-10-15)

The preceding EM-015b source tree `62aad84f4992f795b8a70d83696b5aa85afba63a` is remote Draft PR23 head `ce17422700e81749cc6bf806072340c2887e289e`. Its seven current gates are successful, with application 1729/no skips/no pytest warning summary in 433.70s and 31 React tests. UI and controlled transport required same-head retries; their first failures and unproven causes remain explicit in the [correction evidence](../reports/owned-test-cleanup-validation.md) and PR23 record. Historical in-tree pending statements describe earlier checkpoints.

This separate local candidate only guarantees owned held-response release/future collection on failure and adds fixed route-registration diagnostics. It leaves all success predicates, waits, resource/security/source controls and runtime/XML behavior unchanged. Local pure checks and exact-head CI are distinct; detailed normal/new-empty-Python results and remaining gates are recorded in the report. Cleanup robustness is not a root-cause fix or evidence that intermittent gates are fully reliable. No migration, dependency, live permission, deployment or merge.

## EM-015c synthetic isolated XML pipeline candidate (2026-10-15)

EM-015 remains PARTIAL. A separate single-article synthetic XML route now composes current tenant admission, a fixed bounded same-profile network-none parser channel, typed retained provenance, conservative associations, evidence-backed human review and existing Results/CSV/XLSX. Migration0012 preserves latest0011 lifecycle/RLS guards and adds an explicit `fetch_xml` fixture operation; existing policies and four-article searches stay unchanged. Incremental review corrected local-image-only resolution, bounded control output, truthful partial completion and excerpt-retention semantics. Final normal/new-empty checks pass1586/242 explicit skips in22.52s/24.37s plus31React/full gates; independent source review clears the runtime/test tree after corrections.242 skips comprise219 inherited service cases plus23 new XML cases. All seven actual own-head gates, including1828/no-skip application and same-container→database proof, remain pending in the [candidate report](../reports/em015c-validation.md). Local skips do not establish actual-container/database acceptance. [Runbook48](48-synthetic-xml-pipeline.md) records the remaining real-wrapper/source/production limits.

PR25 original head `ce51d002` failed application/parser image builds because the deny-all build context omitted the tracked XML fixture. The narrowly corrected context and strengthened fixture-COPY regression pass95 focused checks; corrected-head full local/actual gates remain pending. Original UI also failed with three pending unclaimed articles despite a living worker/consumer; cause remains unproven. Original attempt1 failures and successful controlled/docs/browser/packaging receipts are preserved in the candidate report.

A separately authorized diagnostic addition observes fixed worker readiness/task/claim/process stages only in the synthetic UI fixture. It retains existing timeouts, readiness and queue/ACK/security behavior; cumulative bounded sanitized snapshots distinguish absent/truncated/invalid evidence from zero. The repeated UI cause remains unproven.

Corrected local source/test tree passes218 focused cases and full normal1625/24224.03s/new-empty1625/24225.41s plus31React/full gates;39new pure diagnostic cases raise the corrected own-head application expectation to1867/no service skips. Actual all-seven-gate execution and source/tree reconciliation remain required, with the original failures retained.

Second PR25 head `86534bde` passes five gates but fails application1865/2/no skips/one inherited alias warning564.95s and actual UI1/60.04s (31React passed). The XML proof marker was not emitted because the final duplicate assertion used a forged event. Corrections preserve the guard, replay the actual durable event, align catalog parity, and repair diagnostic default-exchange filtering using actual pinned-publication/request/trace regressions. UI cause and EM-WARN-01 remain unproven; all seven next-head gates and1878/no-skip application remain required.

Final routing/test correction passes normal1636/24230.34s and genuinely new-empty1636/24230.53s plus31React/full gates. Independent source review confirms unchanged SQL/publication/security and the narrow diagnostic predicate; actual next-head1878/no-skip/all-seven gates remain pending. No same-container acceptance is inferred from earlier assertions or local service skips.

## EM-015d disabled provider-binding prerequisite candidate (2026-10-15)

PR25's final remote head `9a5c8f12054502fbfeaccd12d3c0364847143228` matches local tree `8a9b1c1364893ab5cca911db81471a17b22e3916`; its final PR body is the accepted all-seven-gate record, including1878 application/no skips and actual same-container XML→database→review→CSV/XLSX. Earlier pending PR25 entries above are historical.

The next bounded candidate provides canonical ScienceDirect request/response comparison, capped streaming, opaque credential-reference scope and the existing shared hop planner, plus a versioned identifier/digest/profile frame in the existing network-none XML worker. Full transport-owned response binding prevents same-URL query/tenant/lease swaps. Current-source admission and live transport are unimplemented/default-denied; no policy/schema/settings/API or fixed synthetic persistence guard is broadened. Local and new-empty checks, independent review and pending actual own-head gates are recorded in [evidence](../reports/em015d-validation.md) / [runbook49](49-disabled-provider-binding.md). This is production prerequisite work, not activated provider access or completion of EM-015/016.

Final local candidate checks pass 1733/245 explicit skips in 32.85s normally and 34.21s in a genuinely new Python environment, plus 31 React and all aggregate gates. Independent corrected-source review passes 425 focused checks with 3 actual-container skips and finds no remaining blocking issue. The 100 added cases require 1978/no-skip own-head application CI; all seven gates and final immutable-tree review remain required before acceptance. Live acquisition/admission and production access remain unimplemented.

## Synthetic solo-worker callback wake correction candidate (2026-10-15)

PR26 head `82e0a6df91e27e03f94ab2792f1f61bf685f0308` / tree `51f8c23fe6008f00fb9134df6404b7da34703bea` completed all seven attempt 1 workflows: six passed, actual operator UI failed. Application passed 1978/no skips/one inherited alias-body warning in 487.69s plus 31 React; actual generalized XML and same-container→database→review→CSV/XLSX evidence passed. The UI log records three completed task/process/postrun sequences, a living worker and three remaining ready/unattempted articles. Those counters do not prove broker acknowledgement or the exact failure cause. Full PR26 acceptance remains open; earlier local-pending entries are historical.

A bounded real-worker/no-network probe now reproduces a causally supported scheduling defect: synchronous solo work invoked inside Kombu's ready snapshot queues an original ACK promise, then the hub polls up to 10 seconds before executing it. A fixture-only consumer bootstep coalesces one nonblocking pipe byte to wake that unchanged poll; original callbacks run on the normal next iteration. It adds two descriptors, no thread/socket/timer/dependency, and changes no heartbeat, prefetch, ACK settings, 8-second UI wait, resources, source/tenant controls or security profiles. It is active without diagnostic logging and includes lifecycle/reconnect/error cleanup. This corrects the proven mechanism; it does not by itself prove the historical CI path or all-seven acceptance. Source review, local normal/new-empty gates and pending actual next-head gates are in [validation](../reports/worker-callback-wake-validation.md). Provider runtime/admission, live access, migration, merge and deployment remain outside scope. Historical EM-WARN-01 stays open and unsuppressed.

Independent source review approves the bounded correction and independently passes its 28 new tests. Final normal and genuinely new-empty Python aggregates each pass 1761 with 245 explicit service/container skips in 47.45s/48.98s respectively, plus 31 React and all static/docs/inventory/build gates. Neither local run has a pytest warning summary; this does not close historical EM-WARN-01. The final source requires 2006/no-skip application and all seven own-head gates; actual UI acceptance remains pending. No local skip or pure scheduling reproduction substitutes for those gates.

## EM-015e controlled executable provider gateway candidate (2026-10-15)

The coordinator reconciled local baseline `cadbf9b` / tree `7ed147ee83a0c5b8915c53927a293b371d566095` with corrected Draft PR26 head `13a83fdc732bd0c7ee10945521ee4448e4263fd3`. All seven prior own-head gates passed, including 2006 application cases/no skips, 31 React and actual UI; one inherited Pydantic warning remains open. Earlier pending/failed PR26 entries remain historical.

This candidate extends the existing protected gateway with canonical ScienceDirect PUT search and GET XML, scoped opaque credential resolution, trusted response binding, bounded shared TLS/HTTP streaming and failure/cancellation cleanup. The unchanged controlled network gains synthetic provider fixtures and actual HTTPS→isolated-parser acceptance. Live source grants, real credential resolution/admission, usable public DNS, production registration and real-source certification remain unavailable. No migration, dependency, security/network setting, merge or deployment changes. [Runbook50](50-controlled-provider-gateway.md) / [validation](../reports/em015e-validation.md) record local/actual verification separately; all new own-head gates remain pending.

Final normal/new-empty local aggregates each pass 1812 with 245 explicit inherited service/container skips in 52.16s/53.71s, plus 31 React and all static/docs/inventory/build gates. Independent corrected-source review clears the bounded candidate and independently passes 244 focused/3 actual-container skips. The 51 added pure cases require 2057/no-skip application and 31 actual controlled cases on the new remote head; all seven gates remain pending. Source rights, full-text view/entitlement, real admission/credential resolution, live DNS/egress and production registration remain explicit activation gaps.

## EM-015f connected controlled provider journey candidate (2026-10-15)

PR27 remote head `86c59f30391c4b67227d092e646040067badbf0f` matches local tree `609831a13104bd76ae1aafa3f4a48cec4f7821ad`; the coordinator recorded all seven successful own-head gates, including 2057 application/no skips/one inherited warning, 31 React and 31 controlled cases. Earlier pending PR27 entries are historical.

The next bounded candidate connects actual controlled provider acquisition to durable tenant retention and conservative review/export using the same work leases, source accounting and isolated parser. Native PUT keyword search resolves two server-registered DOI/PII documents with explicit FULL requests and distinct synthetic versus transport provenance. Forward-only migration0013 preserves latest0012 privacy/lifecycle/session/lease guards; no live source grants or production registration are added. Original four-article and fixed XML flows remain. Local verification and required 41-case actual connected journey/all-seven own-head gates are recorded in [runbook51](51-controlled-provider-journey.md) / [validation](../reports/em015f-validation.md). EM-015/016, real-source pilot entitlement/compatibility/admission/credentials/egress remain partial.

Final local normal/new-empty aggregates each pass 1834 with 260 explicit service/container skips in 53.87s/54.86s, plus 31 React and all aggregate gates. Focused coverage passes 298/18 skips; controlled collection finds 41 cases but is not actual execution. Independent source review identified and corrected two owned-resource lifecycle defects, and final immutable review remains required. New own-head application must pass 2094/no skips; actual controlled41/all-seven gates remain pending.

Corrected PR28 head `eacdbd8e` / tree `a0e3d465` completed all seven attempt-one workflows: six pass, actual operator UI fails. Application now passes 2094/no skips/one inherited warning in 616.14s plus 31 React; controlled41 passes in 195.45s with both actual connected journey receipts. UI reports six claimed/processed tasks, five returns, one process error/task failure, six postrun, zero ready messages and one unfinished leased article. Its underlying exception remains unknown; empty log-class matches are not proof that no exception occurred.

A minimal default-off diagnostic candidate retains only fixed phase/class/reason metadata from the exact task/queue failure signal. Strict cumulative parsing, exception/return preservation, snapshot/tail limits and all runtime authority/queue/security behavior remain unchanged. No speculative lock/entitlement fix or new source authority is inferred. [Verification](../reports/em015f-validation.md) records local checks and pending next-head gates; a later passing UI without recurrence cannot close the historical cause.

Diagnostic candidate normal/new-empty Python aggregates both pass1900/260 explicit service-container skips in67.57s/67.13s, plus31React and all static/docs/inventory/build gates. Independent source review clears the candidate and separately passes228 focused cases in40.96s. The66 added pure regressions require2160/no-skip actual application, unchanged controlled41 and all seven next-head gates. Final report-only recording and immutable-tree reconciliation do not substitute for that execution; historical warning and UI cause remain open.

## EM-015g normal controlled operator candidate (2026-10-15)

PR28 accepted remote head a04f9d29/tree3728a959 completed all seven gates,2160 application/no skips,31React and41controlled; its final PR body is the accepted record. Earlier pending entries are historical; inherited Pydantic warning and intermittent UI exception remain open.

This bounded candidate composes the ordinary authenticated UI/outbox/RabbitMQ task with the existing protected controlled provider journey, retaining default refusal and explicit synthetic XML policy review. Separate provider UI acceptance and bounded sole-worker pipe ownership preserve the original static8s deadline and all guest/security limits. Local aggregate, review and exact-head gates are tracked in [validation](../reports/em015g-validation.md); no real-source activation, migration, dependency, merge or deployment. Full EM-015/016 remain partial.

Final local normal/new-empty aggregates pass1934/260 explicit service-container skips in64.44s/65.14s,31React and all gates. Independent16-file source review passes42 focused cases. Application2194/no skips, controlled41 plus the distinct normal-provider UI case, and all seven exact-head workflows remain required; controlled synthetic proof is not live-source acceptance.

First PR29 head `d77bae6e` / tree `5a5feb40` passed controlled41 and the original static UI, browser, parser, packaging and docs, but the new provider UI failed at `keyword_plan`, with no 201 creation response recorded. Application was still running at this checkpoint. A source-proven duplicate Dashboard/navigation button is corrected by scoping only the first provider activation to Workspace navigation, with one pure selector regression; sanitized failure output does not prove the historical exception. Revised application requirement is 2195/no skips plus 31 React, the new actual operator-provider case and all seven own-head gates. [Validation](../reports/em015g-validation.md) preserves the failed checkpoint; acceptance remains pending.

The first head's application subsequently passed 2194/no skips in 623.75s plus 31 React, leaving six passing workflows and the new provider UI failure. Correction normal/new-empty aggregates each pass 1935/260 explicit skips in 66.66s/68.63s, plus 31 React and all aggregate gates. Actual corrected-head acceptance remains pending.

PR29 corrected head `e6df8d6c` / tree `ee722503` passed original controlled41 and static UI, browser, parser, packaging and docs; its provider UI reached completed-job/both-review waits but timed out at export preview, without final proof. A second source-proven selector mismatch is corrected: the wrapped Format label includes option texts, requiring an anchored label match instead of exact short text. One pure regression raises required application count to 2196/no skips. All waits and isolation controls remain unchanged; next-head actual acceptance is pending.

Second-head application subsequently passed 2195/no skips/one inherited Pydantic warning in 467.03s, plus 31 React. Final label-correction normal/new-empty gates pass 1936/260 explicit skips in 65.01s/67.01s, plus 31 React and all aggregate checks; independent review passes 14 focused cases. All seven previous runs are terminal. Corrected-head application2196 and full controlled-provider operator acceptance remain required.

## EM-WARN-01 bounded test-assembly maintenance candidate (2026-10-16)

PR29 head `b9179491` / tree `310a0fdead` completed all seven exact-head gates, application2196/no skips/31 React, controlled41 and separate actual normal-worker/provider operator1. Independent review verified the full final host assertions. This closes the bounded controlled synthetic composition; real-source activation remains unmet.

The tracked alias warning is now deterministically reproduced through actual app/router construction without database access. Pinned FastAPI's temporary process-global warning contexts overlap when the last-owner test constructs apps in two threads. The correction prepares independent apps/pools serially while keeping concurrent authenticated requests, barrier and `[200, 409]` acceptance. Seven isolated pure cases cover the three historical aliases and setup structure. No application behavior, dependency or warning suppression changes. [Evidence](../reports/em-warn01-validation.md) records limits; normal/new-empty review and all seven new-head gates, including2203/no-skip application, remain required.

EM-WARN-01 candidate normal/new-empty aggregates pass1943/260 explicit service skips in71.58s/72.87s, plus31 React and all checks. Independent causal/source review passes7 cases and dynamic cleanup/failure probes. Actual2203/no-skip application, unchanged concurrent SQL test and all seven new-head gates remain pending; local warning-free skips do not close actual acceptance.

## Bounded popup failure evidence candidate (2026-10-16)

PR30 head27e6ae13/tree81998daa completed all seven latest gates:2203 actual application/no skips/no pytest warning summary,31 React,controlled41/provider1 and original static UI. Browser attempt1 lacked a popup event while download completed; unchanged attempt2 passed. Its cause remains open and both attempts are preserved in PR30.

A diagnostic-only candidate retains the exact three-second failure predicate and records fixed synthetic popup-route/page-event counts plus a bounded read-only child-target snapshot only after failure. No raw URL/title/ID/error text leaves the sanitizer; late events cannot convert failure to success. [Evidence](../reports/browser-popup-evidence-validation.md) distinguishes pinned-driver hypothesis from unproven actual cause.31 new pure cases require2234/no-skip application and all seven own-head gates; no isolation/permission/dependency/deployment change.

Final popup diagnostic normal/new-empty aggregates pass1974/260 explicit service skips in75.91s/76.03s,31 React and all checks. Independent review passes33 focused cases and verifies parent validation precedes target listing, strict malformed-input categorization and sticky failure. Actual2234/no-skip application and all seven own-head gates remain required; the missing-popup cause is still unproven.

## EM-017c isolated XML worker package candidate (2026-10-16)

PR31 head 04a3b6e2 / tree 9e14c951 completed all seven first-attempt gates, 2234 actual application/no skips, 31 React, controlled 41/provider 1 and original static UI. Independent review and final PR evidence reconciliation are complete. Missing-popup causality remains unproven; no speculative fix or repeated successful rerun is undertaken.

The next bounded EM-017 prerequisite prepares a separate image for the existing synthetic-only XML worker. It retains the explicit shared-helper source closure without embedded fixture/sample assets, unchanged runtime code/protocol and identical isolation. Additive packaging acceptance requires two uncached builds, exact manifests, actual stdin/refusal/kernel checks and owned cleanup; normal/new-empty review and all seven own-head gates remain pending. [Runbook53](53-isolated-xml-worker-package.md) / [validation](../reports/em017c-validation.md). EM-015/016 real-source inputs and full EM-017 production runtime/deployment remain unmet.

Final local normal and genuinely new-empty Python aggregates return exit 0: 2064 passed/260 inherited explicit service skips in 75.97s/75.50s, 31 React tests and all static/docs/inventory/build gates. Independent source review clears the unchanged-runtime package and separately passes all 90 new focused cases. The interrupted first normal run is retained as incomplete. Actual application 2324/no skips and all seven exact-head gates, including two XML builds and 14 worker executions, remain required.

PR32 first head 833dbc1a / tree 7d997caa passed the original metadata image checks but its added XML step failed before Docker: the standalone runner lacked the source-layout import path. A narrow new-step PYTHONPATH correction and subprocess startup regression leave runtime/protocol/isolation unchanged. Required own-head application count becomes 2325/no skips; all local/review/actual gates remain required and the original failure is preserved in the report.

Corrected local normal/new-empty checks return exit 0 with 2065/260 explicit skips in 77.14s/78.64s, 31 React and all aggregate gates. Independent review clears the narrow startup correction and passes 91 focused cases. Actual corrected-head packaging and all seven workflows remain required.

## EM-017d curated XML consumption candidate (2026-10-16)

PR32 corrected head ba2bc151 / tree f2e87c0a completed all seven first-attempt gates: 2325 actual backend tests/no skips, 31 React, controlled 41/provider 1, original static UI/browser/parser/docs, and both metadata/XML reproducibility acceptance. Independent final source, log and published-body review passed. The original startup failure remains preserved.

The next bounded slice substitutes the verified curated XML artifact only in existing controlled application/operator acceptance. Host-only image/owner expectations bind actual parser metadata to the prepared artifact, while runtime protocol/isolation/source policy remain unchanged. At the initial proposal checkpoint, local/review/actual gates were pending; the following paragraph records completed local validation. [Runbook54](54-curated-xml-integration.md) / [validation](../reports/em017d-validation.md). Production assembly and real-source gates remain unmet.

EM-017d clean normal/new-empty aggregates pass with verified exit 0: 2124/260 explicit service skips in 76.49s/75.56s, 31 React and all aggregate gates. Independent review passes 122 focused cases. Initial nine workflow-location contract failures and the incomplete interrupted aggregate remain preserved. Exact-tree actual 2384/no-skip application and all seven CI gates remain pending.

## EM-017e packaged-base inventory candidate (2026-10-17)

PR33 head f7dd9092 / tree eef3775a completed all seven first-attempt gates: 2384 actual backend tests/no skips, 31 React, controlled 41/provider 1 and original static UI/browser/parser/docs/packaging. Prepared and actually consumed XML identities matched; artifact hashes reconciled across consumer and independent builds, with owned cleanup. Independent final source/log/body review passed.

The next bounded deployment prerequisite records observed Debian/upstream-Python metadata and attribution-file hashes for the existing metadata/XML artifacts, using their current network-none probes. No complete SBOM, legal/security clearance or release claim is made. Local aggregates and independent source review passed; final exact-tree review and actual CI gates remain pending. [Runbook55](55-packaged-base-inventory.md) / [validation](../reports/em017e-validation.md).

## EM-017f owned test runtime composition candidate

Accepted Draft PR34 head `ecf314a09f9ec2c07f02714802a95ad123f14515` / tree `453edbeb8c532c23b618b9a196baf54f95f8cebb` passed all seven first-attempt workflows, including 2473 actual backend/no skips, 31 React, controlled 41/operator 1 and matching installed inventory evidence. Its reviewed description summarizes acceptance bound to that exact head/tree and verified workflow runs; older pending entries are historical.

The next bounded EM-017 slice explicitly owns test-only API/runtime/authentication/publisher SQL composition and consumes it in normal controlled operator acceptance. It does not activate production identity, storage/secrets or real sources. Independent design/source review is clear; normal/new-empty aggregates pass 2336/264 explicit service skips plus 31 React and mypy over 249 files. Final exact-tree review and actual 2600/no-skips/all-seven acceptance remain pending. [Runbook56](56-owned-test-runtime.md) / [validation](../reports/em017f-validation.md).

## EM-017g owned test publisher candidate

Draft PR35 head `a13748ea3496e02caa17a433060ffa0bffb45f3d` / tree `42d742292520102c41f6c4545c52a6ff3cf518d0` completed all seven first-attempt workflows: 2600 actual backend cases/no skips, 31 React, actual runtime SQL cases, controlled 41/operator 1, existing browser/static UI/parser/docs and both package builds. Independent source/evidence/final-description review passed; prior pending text records historical checkpoints.

The next bounded runtime slice owns one finite publisher connection/channel and reuses existing Celery/publication semantics. Independent design is approved; implementation and candidate gates remain pending. No supervisor, provisioning, production identity or real-source gate is introduced. [Runbook57](57-owned-test-publisher.md) / [validation](../reports/em017g-validation.md).

EM-017g corrected normal/new-empty aggregates pass with explicit exit 0: 2411 passed/268 explicit service skips in 100.59s/131.63s, 31 React and mypy over 252 files. Independent corrected source review and 85 focused cases pass. Earlier import formatting and unchanged channel-deadline test failures remain preserved; no channel fix is claimed. Final exact-tree review and actual 2679/no-skips/all-seven own-head gates remain required.

PR36 first head `130124def467baab13141beaf7ef018e0292e9ac` / tree `b639e9e823272257e7fe011e8527832ac4c34318` passed six gates and 2678 actual backend cases, but one new caller-survival fixture failed before publisher execution: RabbitMQ 4.3.6 rejects transient non-exclusive queues. The test-only correction makes the separate caller's uniquely named queue exclusive; durable publisher queues and all controls are unchanged. Original failure is preserved; corrected local/review/all-seven gates remain required.

The exclusive caller-queue correction passes normal/new-empty aggregates with explicit exit 0: 2411/268 explicit skips in 90.89s/101.35s, 31 React and all existing local gates. Independent corrected source/focused review passes. Corrected exact-tree and actual own-head acceptance remain required.

## EM-003 / EM-012 operator synthetic policy integration candidate

Corrected Draft PR36 head `2ec9db1c012c10e416fab6f21ab81a09e017138d` / tree `2b0e8ebd04c33c85aefe49db2a7b063e242ee776` completed all seven workflows: 2679 actual backend/no skips, 31 React, controlled 41/operator 1 and all existing browser/static UI/parser/docs/packaging gates. Independent final evidence and description review passed. Earlier pending paragraphs are historical; original failures remain preserved.

The next existing operator integration exposes closed HTML/XML synthetic policy proposals, preserves HTML defaults and separate review, and moves controlled XML policy creation/approval into the actual keyboard journey. Independent design is clear; candidate aggregate/source/exact-tree and actual gates remain pending. [Runbook58](58-operator-synthetic-policy-profiles.md) / [validation](../reports/operator-xml-policy-validation.md). Real source rights and production runtime remain unmet.

Corrected normal/new-empty Python aggregates both return exit 0: 2411 passed and 277 explicit service skips, 38 React cases and mypy over 253 files; all existing docs/lint/format/inventory/type/build gates pass. The new-empty Python environment was absent before creation; shared package caches and frontend dependencies are reused. Independent source review and 14 focused provider-worker cases pass. Actual 2688/no-skip application and all seven own-head workflows remain required.

## EM-006 / EM-012 direct controlled XML URL candidate

Draft PR37 head `a20d289cdbb57dec2a60482ad0cdef700815e47c` / tree `6f5948bd0f6aa93b17e5898b4b944f56e1848e18` completed all seven first-attempt gates: 2688 actual backend/no skips, 38 React, controlled 41/operator 1, original static/browser/parser/docs/packaging. Independent source/evidence/final-description review passed; its prior pending checkpoints are historical.

The next bounded operator closure exercises an existing direct synthetic XML article URL through the normal UI/registered worker. Original keyword/static cases and controls remain unchanged. Independent design is clear; source review corrected a test identity assertion. Focused 78 and frontend 42 cases pass; normal/new-empty/exact-tree and actual 2706/no-skip/all-seven gates remain pending. [Validation](../reports/operator-direct-url-validation.md).

Normal and genuinely new-empty Python aggregates each return exit 0: 2429 passed/277 explicit service skips, 42 React cases, mypy over 254 files and every existing docs/lint/format/inventory/type/build gate. The fresh Python environment was absent before creation; shared caches/frontend dependencies were reused. Independent corrected source review passes 32 focused Python and four frontend help cases. Final exact-tree review and actual 2706/no-skip/all-seven gates, including two provider operator cases, remain required.

## EM-007 / EM-010 / EM-012 tooltip operator candidate

Draft PR38 head `415a41dda6b39282e4a47af6dc1400ce59de0078` / tree
`cdcf5cf41cf436251181d0b347ec7131ea876cc2` completed all seven first-attempt
workflows: 2706 actual backend/no skips, 42 React, controlled 41 and two operator
journeys, plus original static UI/browser/parser/docs/packaging. Independent final
source/evidence/description readback passed. Earlier pending text is historical.

The next bounded slice joins existing synthetic tooltip browser acquisition to
the normal claimed worker and explicit operator opt-in. Independent design is
clear; source review, normal/new-empty and all seven actual gates remain pending.
[Runbook59](59-operator-tooltip-browser.md) /
[validation](../reports/operator-tooltip-validation.md). Live source rights and
production runtime remain unmet.

Tooltip candidate normal/new-empty aggregates both return exit 0: 2484 passed
and 302 explicit service skips in 99.42s/107.48s, 48 React cases and mypy over
261 files, with all existing local gates. Independent source/delta review is
clear. Initial annotation/test-fixture failures and the corrected late-SQL
revocation finding are preserved in the report. Actual 2786/no-skips and all
seven own-head gates remain required.

PR39 first head `3b94fe4ea53f3b85d85fbc972ec0504875d64ff7` / tree
`5472d3802c266e0e8c0a4f64b441dfe7a9528a97` passed controlled transport 41 and
the original keyword operator, but failed the new checkbox keyboard assertion
before execution and the existing direct-XML export's envelope/config authority
check. Native Space activation and app-local Celery closure registration address
the independently reproduced mechanisms without weakening predicates or fences.
Original failure is preserved; corrected local/review/all-seven gates remain
required.

Corrected tooltip normal/new-empty aggregates pass with explicit exit 0:
2487 passed/302 service skips, 48 React and mypy 262 files, all local gates.
Independent corrected source/mutation review passes. First-head application also
completed 2786 actual cases/no skips, leaving six successful gates and the
preserved controlled failure. Corrected 2789/no-skips/all-seven acceptance remains
required; no first-head run was interrupted.

PR39 second head `1230acab789d623b60d62ce4673e0851cd705fff` / tree
`2c4850b4be70d75dad09b5cc603981b844f36505` passed transport 41 and both XML
operator journeys. Tooltip reached completed but its copied needs-review list
expectation excluded the already accepted explicit browser association. The
browser-only test now opens accepted Contacts before the same genuine evidence
review/save. Rules and deadlines remain unchanged; the second failed controlled
run is preserved and all corrected gates remain required.

The review-entry correction passes normal/new-empty aggregates: 2488 passed/302
explicit skips in 101.42s/112.09s, 48 React, mypy 262 files and all local gates.
Independent source/mutation review is clear. Second-head application completed
2789 actual cases/no skips; all seven runs ended before further publication.
Final corrected 2790/no-skips/all-seven acceptance remains required.

PR39 final head `2e90c6dcc686a8b354440669ea8e4422b586a9c7` / tree
`3fdc20880ebaf8914cce9760497c88a7ff6f1ecd` completed all seven attempt-one
workflows: 2790 actual backend/no skips, 48 React, controlled 41 plus all three
operator journeys and existing static UI/browser/parser/docs/packaging gates.
Independent final source, actual-log and factual-description review passed;
public Draft body readback matched. Both earlier controlled failures remain
preserved in the report. No live-source or production gate is closed.

The next independently design-reviewed acceptance slice covers the original
combined synthetic keyword demonstration and a separate accepted-contact
subprocess crash/replay regression. Existing source, isolation and timing limits
remain unchanged. [Runbook60](60-combined-fixture-demonstration.md) and
[validation](../reports/operator-combined-fixture-validation.md) define the proof
boundaries. At initial scoping, implementation and own-head acceptance were
pending; subsequent local receipts follow.

Combined-demo normal/new-empty aggregates passed with exit 0: 2497 backend / 303
explicit service skips, 48 React and mypy 263 files. Independent corrected source
review and 144 focused cases passed. Preserved initial failures include three
stale contract expectations and an unchanged intermittent DNS timing assertion;
no timing predicate was changed. Actual 2800/no-skips and all seven own-head gates
remain required.

PR40 first head `e407aada6e7f6b97af558466ef86ed82c08b1435` passed 2800 actual
backend/no skips, 48 React and six workflow outcomes (parser on an unchanged
second attempt after absent OOM flag). Controlled 41 and three original operators
passed; combined UI completed but the host expected raw rather than canonical
stored keyword input. The corrected complete-model assertion retains exact raw
payload checks; independent original mutation fails. Corrected normal/new-empty
2498/303 skips and 48 React pass. All prior runs ended; new-head actual gates remain
required. Earlier parser/DNS failures remain unresolved and preserved.

PR40 corrected head `8c7b06ceac5b84eaee36447e2ba70311aef8fcf0` / tree
`00b57e8761ec8ec61832b0a290df40c7b86047aa` completed all seven workflows:
2801 actual backend/no skips, 48 React, 41 transport and four operator journeys.
Browser passed its unchanged second attempt after an unresolved boundary-readiness
timeout; all other final-head runs passed first attempt. Independent exact-tree,
actual-evidence and final factual-body review/readback passed. Draft remains
unmerged; earlier failed receipts remain preserved in its public description.

On 2026-10-20 the owner selected Elsevier/ScienceDirect. The bounded next EM-015
prerequisite is [private offline sample admission](61-private-offline-sample-admission.md).
Actual sample execution remains blocked on a scoped rights decision and reviewed
Docker environment. Current cloud lacks that runtime. No live source grant,
credential, production deployment or real contact publication is authorized by
this candidate. At initial assessment, implementation and acceptance were pending.

Private admission implementation and independent source review are complete.
Normal/new-empty aggregates exit 0 with 2552 passed/303 explicit service skips,
48 React and mypy 266 files. All seven actual own-head gates, including the new
synthetic private-entry isolation case, remain required. Real-sample rights and
local Docker availability remain unresolved.


## 2026-10-20 — One scoped Elsevier sample candidate

Partial EM-015: a dedicated one-initial-event runner is implemented for one exact
immutable article representation. A specific CC BY 3.0 article-level decision,
including attribution and legacy contradictory wording, is documented in
[runbook62](62-elsevier-one-sample-validation.md). This grants no unrelated source,
live API, tenant storage, export or outreach capability.

The runner builds/probes the existing owned curated artifact before its single
anonymous pinned-address HTTPS request, verifies exact length/digest and calls
the unchanged private admission/isolated parser. A mode-0700 temporary directory
outside the checkout is removed before bounded owned-image/container cleanup.
Only closed status/reason/count results can be emitted after cleanup verification.
Existing seven synthetic workflows, application source and protocols are unchanged.

Focused synthetic checks after cleanup-review correction: 296 passed, including
57 new runner cases; full mypy
268 files, changed-source Ruff and documentation checks passed. No real sample
was acquired or parsed locally. Independent exact-tree review, full normal/fresh
aggregates, existing actual gates and the dedicated initial-event outcome remain
pending. See [evidence](../reports/elsevier-one-sample-validation.md). Counts alone
will not establish extraction accuracy or a representative benchmark.

## 2026-10-20 — Private affiliation diagnostic candidate

Partial EM-015 investigation. Authored synthetic counterfactuals reproduce
reference-gated implicit affiliation suppression; this is not confirmation of the
real sample's cause. A separate private fixed-counter diagnostic is implemented and independently reviewed,
with distinct rights scope and unchanged normal parser/one-shot controls.
[Design](63-affiliation-diagnostic-design.md) and
[validation](../reports/affiliation-diagnostic-validation.md) distinguish local
pure/mock evidence from pending actual isolated acceptance. No live activation.

Local normal/new-empty Python aggregates each passed 2751 tests with 303 explicit
service skips; 48 React, full Ruff/mypy and documentation/inventory checks passed.
Actual synthetic Docker diagnostic and exact-head CI remain pending before
acceptance. The candidate is unpublished.

## 2026-10-20 — Separately scoped one-sample diagnostic candidate

PR43 synthetic exact-head gates passed, including the actual fixed-counter Docker
acceptance. A new PR44 initial-event composer is being validated under the
[reviewed scope](64-one-sample-affiliation-diagnostic-plan.md). It preserves the
PR42 and PR43 boundaries and uses a separate diagnostic-purpose decision.
[Evidence](../reports/one-sample-affiliation-diagnostic-validation.md) records
prerequisites and pending local/review/actual gates. Real cause remains unproven.

Local candidate gates passed: normal/new-empty Python each 2932 passed with
303 explicit service-dependent skips; React48, Ruff282, mypy280, inventory and
docs. Independent source-boundary review passed 515 focused tests after correcting
a cleanup signal-transition gap. Exact frozen-tree and actual CI/initial-event
receipts remain separate. No real sample was acquired locally.

### Additive article-quality review view (2026-10-20)

The EM-010/EM-012 evidence drawer now has a separately versioned, current-authorized retained article-quality read view. It displays fixed XML reasons and explicitly leaves missing affiliations unobserved after author-email acceptance. HTML reason availability is reported honestly. Existing stored Bundle identity, parser/diagnostic versions, replay and export contracts are preserved. See [scope, compatibility and validation](65-observation-quality-review.md). This entry records implementation scope; exact-head CI receipts remain required before acceptance. Zero-candidate article-wide UX and production deployment are not claimed.

### EM-017 bounded durable service runtime (2026-10-20, candidate)

The [service reference runtime](66-durable-service-reference-runtime.md) adds
independent API/web, worker and finite publisher entrypoints, explicit exact-resource
service delegations and additive migration 0014. Natural human-session expiry and
explicit revocation have separate, tested contract semantics; no persistent live
access is created. HTML-only reference dispatch is explicit. Actual disposable
SQL/broker, migration equivalence, installed keyboard operator and full exact-head
CI acceptance remain pending. Local fixture/package/TLS checks do not establish
production readiness. Legacy restore refuses service-authority state until its
revocation seal is supported; downgrade is forward repair only.

### Installed controlled XML integration — local candidate

Dependent on accepted Draft PR46 head `713c517750bb98c5330b26292b2582cd4aef5676`.
Work connects the existing controlled keyword/direct XML workflow to the installed
service runtime. Explicit runtime capability and source-policy approval remain
separate. The default authored HTML route is preserved. Independent design review
required container-level worker confinement after rejecting descriptor filtering
alone. Actual SQL/broker/parser/operator and final combined gates are outstanding;
see [candidate validation](../reports/em017-installed-controlled-xml-validation.md).
No live source, credential, deployment or merge is included.

### EM-017 closed service-authority restore — candidate (2026-10-22)

A separate dependent slice after accepted PR47 implements the
[closed synthetic service restore seal](67-closed-service-authority-restore.md).
Independent design review passed before implementation. The legacy populated-state
refusal remains; the new target never grants CONNECT or serves work. Exact
revocation/audit/role/schema/export/privacy reconciliation passed independent source
review. Normal and separate fresh local gates each passed 4,754 backend and 77 React
tests with 389 explicit infrastructure skips. [Validation](../reports/em017-service-restore-validation.md)
tracks the required actual hosted gates; this entry is not a completion claim.

### EM-010/011/012 retained job investigation — candidate (2026-10-22)

A separate dependent slice after accepted PR48 adds job-scoped paginated article
outcomes and retained-batch quality independently of contact candidates. Whole-job
progress and first-100 execution diagnostics remain distinct. Existing Contacts,
evidence/review and lifecycle authorization are preserved. No migrations or
backend contracts change. [Scope](68-retained-job-outcome-investigation.md) and
[validation](../reports/job-outcome-investigation-validation.md) track source,
normal/fresh and actual hosted acceptance, which remain pending in this entry.

The investigation candidate now separates only the unchanged long 104-outcome
SQL traversal into a mandatory hosted job, with a complete backend complement
and exact collection/execution receipts joined against the same source/config.
Full local aggregates and all per-job security/cleanup/deadline controls remain.
The preceding actual operator proof passed, but two full-backend attempts reached
the unchanged wrapper bound without final pytest summaries; both verified owned
cleanup. New exact-tree normal/fresh, independent review and hosted receipts remain
required. The linked validation record preserves those failed receipts.

### FR-023 retained article filters — candidate (2026-10-23)

A separate dependent increment after accepted PR49 adds exact job/item selection
and outcomes-only candidate presence. It retains original Contact provenance,
legacy default request/snapshot/cursor identity and current authority. Forward-only
migration 0016 keeps existing service visibility private and uses exact-export
captured binding validation for no-contact and inherited contacts-only work.
[Scope](69-retained-article-filters.md) and [validation](../reports/retained-article-filters-validation.md)
separate authored pure/browser cases from required actual SQL/service/operator
proof. Frozen source review, serial normal/fresh gates and all hosted checks remain
pending; this entry does not complete general FR-023 source/date/paper-equivalence filters.

PR50 first-head hosted acceptance failed in application and original operator gates;
six other workflows passed. Independent review identified incorrect service-exception
and suppression-refusal expectations in the new tests. A test-only correction retains
the existing runtime refusals, while original receipts and the unresolved operator
entitlement diagnostic are preserved in the validation report. Corrected-source
normal/fresh checks, independent review and all exact-head hosted gates remain required.

The retained-filter candidate schedules its 29 exact SQL cases beside the unchanged
104-outcome traversal in the existing SQL job. A closed 30-node manifest and exact
backend complement preserve full collection and successful execution proofs at the
mandatory three-job join. Job counts, roles, deadlines and unfiltered normal/fresh
aggregates remain unchanged; exact-source hosted acceptance is still required.

The owned browser acceptance also has bounded tenant-only admission-timing
diagnostics. They preserve the HTTP receipt-gap assertion, cleanup and all runtime
authority/deadline controls; exact-source hosted acceptance remains required.

The owned operator fixture also has temporary value-free server-side entitlement
diagnostics, with exact function restoration and unchanged refusal behavior.
These observations distinguish ordinary denial from caught lock refusal in the
actual invocation; complete hosted acceptance remains required.

The owned installed XML harness records fixed export substeps on failure and a
failure-only publisher/export/outbox receipt scoped to its synthetic organization
and owner. The separate read-only SQL connection has bounded connect, statement
and lock waits; unavailable diagnostics preserve the original failure. Closed
vocabulary and ownership tests are in `test_installed_xml_harness.py` and
`test_operator_ui_protocol.py`. These observations do not change runtime behavior
or establish complete hosted acceptance; no migration or grants are required.

The owned browser-isolation host records bounded monotonic receipt-time buckets
for its existing fixed guest checkpoints, including startup and route registration.
Partial lines are bounded; duplicate and unknown stages are ignored. Batched
markers share their host receipt time. Success and deadline-failure evidence
retain these observations without changing mediation, browser behavior or limits.
`test_browser_isolation_configuration.py` covers these diagnostic boundaries;
complete exact-source hosted acceptance remains required.

The owned operator harness now observes the URL job from creation through terminal
SSE replay. Readiness requires current stream acknowledgment, matching job and
progress generation/sequence, successful current response delivery, replacement
of the pre-replay request-owned page, and a connected matching outcome opener.
The synchronization and original visibility check share the existing ten-second
budget; the 180-second journey limit and content/focus assertions remain unchanged.
`test_operator_replay_readiness.py` covers reordered, stale, incomplete and refused
observations. A separate hosted proof holds actual terminal replay, demonstrates
premature-dialog invalidation after release, then verifies synchronized inspection.
Events are forwarded unchanged; production lifecycle and permission rules are not
modified. Exact-head hosted acceptance remains required.

### Isolated receipt concurrency candidate

Forward migration 0017 replaces only `execution_confirmed` with a receipt-specific shared job fence and advances service schema readiness. It preserves existing authority predicates and outbox updates; the generic control fence is unchanged. Publication is pending focused proof review. Export reconciliation remains unchanged. Source-policy and full revocation/deletion interleavings are not declared accepted.


### Durable authored PDF candidate — acceptance incomplete

The explicit opt-in fixture-only implementation and acceptance inventory are in
[design70](70-durable-fixture-pdf-design.md). Pure retained/protocol checks and actual
SQL journeys are distinct from isolated parser acceptance. The parser-only client configuration prevents automatic proxy injection
without changing the environment guard. Standard packaging and complete installed
acceptance remain pending; see the current design for validation limits.
Published PR50 stays unchanged. No live fetching, grants or deployment are enabled.

The controlled PDF candidate now composes the worker's bounded byte-parser capability
with the supervisor-selected immutable image. Nine actual isolated RPC cases and
two actual tenant SQL cases cover fixture-only transport, replay/review/export and
cancellation-before-commit. This is not installed artifact/broker certification.
The controller timeout now has failure-only phase/stack diagnostics with its original
20-second deadline; the historical timeout is not claimed repaired.

The first PDF hosted candidate passed seven ordinary workflows and the actual
PDF post-observation crash/recovery case. Its installed browser case refused launch
because composed service bindings omitted registered PDF routes. A bounded routing
correction adds only those nine authored fixtures to the composed profile; default
HTML and unknown-route refusal remain. Installed browser acceptance remains pending
new exact-head execution.

### Tenant-local retained paper identity — local candidate

FR-008/019 and paper-selection FR-023 are being implemented as a conservative
observed-DOI grouping over distinct retained observations. Existing job/evidence,
author/review and policy relationships remain independent. See
[design and acceptance boundary](71-retained-paper-identity.md). The local normal aggregate and focused actual SQL cases pass; an independent
fresh check and genuine hosted gates are tracked in the candidate report. No
public publication or whole-product completion is claimed. The accepted authored-PDF Draft head remains unchanged.

## Retained article metadata review slice

The review workflow now has a current-authorized metadata projection and panel
for retained title/journal/DOI/date text and HTML/PDF citations. Source/batch
binding and the existing runtime RLS/final visibility checks are preserved.
XML metadata remains unobserved where the retained profile recorded none.
This is a read-only presentation feature, not publication-date filtering or
observation reuse. See `docs/78-retained-article-metadata.md` for acceptance
inventory and limits; authored SQL/browser cases require actual hosted execution
and must not be inferred from local skips. No migration or acquisition change.

## Independent retained job timing candidate

NFR-017 / FR-021: read-only queue-to-terminal interval under existing job authority;
no worker CPU, billing or performance claim. Isolated from review-history and
suppression candidates. Implementation and acceptance scope are documented in
`docs/81-retained-job-timing.md`; actual SQL, normal/fresh and hosted gates remain
pending until executed. No migration, source access, merge or deployment.
## Contextual contact suppression — Draft acceptance pending

The existing EM-014 suppression action is connected to the current contact in the
evidence dialog under the unchanged source-policy management capability. Explicit
reason, organization-wide confirmation and fresh-contact binding are required.
Normal/fresh backend, frontend and eight actual SQL cases passed; genuine hosted
acceptance remains incomplete after a preceding outcome-keyboard failure. See
[scope and acceptance](80-contextual-contact-suppression.md). No runtime authority
or migration change is included.

PR62 bounded pagination harness correction: replace the five-second table-only
precondition with exact authored replay/response/render readiness. No runtime,
authority, migration or deadline change. The historical target replacement at
Tab48 is evidence for the missing precondition, not attribution of the stream
trigger. Candidate normal/fresh and hosted gates must be recorded separately;
installed-login, XML and cumulative backend deadline failures remain distinct.

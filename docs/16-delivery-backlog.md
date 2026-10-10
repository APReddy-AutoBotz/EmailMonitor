# 16 — Dependency-ordered delivery backlog

**Baseline:** 2026-10-08. EM-001 is reviewed/CI-verified in an unmerged draft PR. EM-002 is reviewed/CI-verified in an unmerged draft PR; EM-003 is reviewed/CI-verified in an unmerged draft PR. EM-004a is a reviewed/CI-verified offline partial slice in Draft PR #4; full EM-004 network/browser/parser isolation remains unmet. EM-005 is reviewed/CI-verified as an offline foundation in Draft PR #5 on its EM-002/003 dependencies; EM-004b real synthetic TLS/parser diagnostics are under review; network-dependent tasks remain gated. Complexity labels are relative planning estimates, not calendar commitments. One reviewable PR per task or smaller accepted slice.

## Core tasks

### EM-001 — Reproducible scaffold and offline fixture harness (M)

Dependencies: documentation baseline. Read architecture, AGENTS, contracts, fixture README and test strategy. Deliver backend/frontend workspaces, compatible stable version matrix, lockfiles, license inventory, basic tests and actual setup/CI commands; preserve documents. Provide a visibly nonfunctional extraction scaffold rather than fake live data. Create isolated fixture transport/server and contract validation. No external crawling, mail, AI or deployment. Acceptance: clean install/build/smoke, docs/schema/examples pass, fixture link/expected-data checks pass, test-only modes rejected by production configuration. Update status with exact checks.

### EM-002 — Organization identity, RBAC and RLS foundation (L)

Depends EM-001. Implement OIDC boundary/session, identities/memberships, active-tenant authorization, minimal tenant tables/migrations, role/capability checks and organization lifecycle. Introduce non-owner runtime database role and transaction-local RLS. Acceptance: two-tenant API/SQL/pool tests; owner-transfer guard; stale/revoked session and unauthorized tenant selection blocked. No crawler bypass as a demo shortcut.

### EM-003 — Source registry, policy and configuration (M)

Depends EM-002. Implement source catalog, per-tenant policy versions, approval/expiry/revocation, permission references, source credentials references, safe config validation and source support matrix. Only synthetic source is available for tests; no blanket live approval. Acceptance: unknown/expired/revoked route fails closed, owner/steward capability enforcement, no secret disclosure, policy overrides cannot weaken platform rules.

### EM-004 — Protected fetch gateway and sandbox boundary (L)

Depends EM-003. Implement URL classification safety, DNS/IP and connection-time restrictions, redirect handling, size/time limits, approved-domain egress and test-only fixture isolation. Cover HTTP and browser network paths; parser receives no network access. Acceptance: SSRF/redirect/rebinding/IPv6/subresource/credential-forwarding tests pass; 403/challenges do not trigger evasive retries. This task gates live network access, regardless of later UI readiness.

### EM-005 — Durable jobs, outbox, leases and quotas (L)

Depends EM-002/003. Implement job/item ledger, state machine, RabbitMQ/Celery transport, transactional outbox, idempotent effects, lease fencing, reservations and recovery. Network execution waits for EM-004. Acceptance: worker/broker failure and duplicate delivery recover without lost committed results or duplicate usage effects; pause/cancel and deletion-generation primitives work on fixtures.

### EM-006 — Keyword/URL planning and search discovery (L)

Depends EM-004/005. Implement input modes, explicit spelling suggestions, page type detection, preflight, pagination/checkpoints, article URL dedup, scope/caps and completeness reporting. Acceptance: two fixture search pages discover each article once; homepage refines instead of whole-domain crawl; loops/caps/changed selectors produce truthful partial state. API fallback is explicitly labeled.

### EM-007 — HTML and browser-contact extraction (L)

Depends EM-006. Implement structured metadata, ordered authors, role markers, mailto/public attributes, ordinary tooltip/click-to-reveal, scoped follow-up links and hostile-content controls. Acceptance: article-a and article-b role/address evidence correct; tooltip fixture works; support/footer/reference email excluded; no email or contact-form submission occurs; browser network tests remain green.

### EM-008 — Bounded PDF text/layout extraction (L)

Depends EM-004/005/007. Finalize reviewed parser dependencies, build isolated byte-to-observation parser, generate synthetic PDF fixtures, handle layouts/footnotes/line breaks and explicit unsupported outcomes. Acceptance: page/region evidence and correct correspondence mapping; corrupt/encrypted/large/scanned inputs fail safely; no OCR dependency silently introduced; license inventory updated.

### EM-009 — Author/email associations, provenance and review (L)

Depends EM-007/008. Implement candidate/address/author/affiliation/evidence relations, deterministic mapping, conservative normalization, technical-check status, tenant-local dedup, review/revision and correction. Acceptance: first versus corresponding remains separate, multiple correspondents retained, ambiguous names never auto-merge, accepted records require evidence, heuristic scores never displayed as probabilities.

### EM-010 — Progress, exception handling and resumability (M)

Depends EM-006/009. Finish durable counters, authorized SSE, review/no-contact/blocked/failed outcomes, pause/resume/cancel/retry UX API and reconciliation. Acceptance: unknown total shows truthful progress; interrupted job resumes at checkpoint; all-no-contact can complete; source cap is partial; revoked tenant cannot read a stale stream.

### EM-011 — Results API and safe CSV/XLSX exports (L)

Depends EM-009/010. Implement server-side filters/cursors, result/detail/evidence endpoints, asynchronous export snapshots, role/purpose/source checks, formula-safe serialization, expiry and authenticated downloads. Acceptance: contacts and article outcomes remain distinct; accepted associations only in default contact export; formula payloads safe; cross-tenant/stale/revoked artifact downloads blocked.

### EM-012 — Complete operator and organization UI (L)

Depends EM-002/003/006/009/010/011. Implement document-03 screens, both input modes, job view, evidence drawer, review, exports, sources, usage and organization settings. Acceptance: keyboard-accessible end-to-end flow, all error/empty/partial states, organization-switch cache isolation, no fake data claims, no client-only permissions.

### EM-013 — Usage, fairness and administration hardening (M)

Depends EM-005/010/012. Implement tenant/source shared throttles, fair admission, usage reconciliation, entitlements, branding and operational support metadata. Acceptance: one tenant/source cannot starve all others; retries do not double charge; plan changes cannot relax source/security controls; no payment processor needed.

### EM-014 — Retention, suppression, deletion and audit (L)

Depends EM-009/011/013. Implement staged deletion, generation fences, artifact invalidation, source/privacy suppressions, retention schedules and audited exceptional support grants. Acceptance: deletion during fetch/parse/export never resurrects data; denied downloads remain denied; no PII in routine logs; backup-tombstone replay specified and tested in later restore task.

### EM-015 — Real-source onboarding and connector pilot (L)

Depends EM-004/008/011/014 and documented source permissions. Certify a small set of structurally different sources through document 23. Use real credentials only through secret storage. Acceptance: supported keyword/URL routes, declared query semantics, page caps, field coverage, rate compliance, egress host list, canary and permission references. A missing source license blocks that connector only; continue fixture/other authorized work.

### EM-016 — Held-out benchmark and customer UAT (M)

Depends EM-012/015. Execute document-14 protocol with authorized samples, blinded author-email audit and truthful statistics. Acceptance: measured precision/evidence/source-stratified coverage, operator-time/cost report, security and core UAT gates, explicit limitations. Failed source families remain uncertified; no inflated portfolio-wide score.

### EM-017 — Hosted and dedicated deployment / restore (L)

Depends EM-013/014 and sufficient tested build. Implement reproducible images/config, regional storage/secrets, OIDC, constrained worker networks, upgrade/migration and backup/restore runbooks for both modes. Acceptance: staging deployments, actual restore RPO/RTO, runtime RLS, deletion-tombstone replay, smoke and two-tenant checks; no unapproved production/cloud purchases.

### EM-018 — Release, licensing and commercial readiness (M)

Depends EM-016/017 plus owner/customer decisions. Finalize SBOM/license/security review, support ownership, contractual/source permissions, privacy materials, onboarding/offboarding, release artifacts and signed acceptance. Acceptance: no unresolved release-blocking security defects; no unlicensed dependency/source use; documented supported features/limits; final commercial/visibility/license decisions. Do not auto-publish a public release without owner instruction.

## Post-core extension tasks

EM-EXT-01: bounded OCR adapter and evaluation, after EM-008/016 and dependency review.
EM-EXT-02: approved wider-web/institutional identity enrichment, after EM-015/016 and source-purpose review.
EM-EXT-03: recurring saved searches and freshness workflow, after EM-013/014.
EM-EXT-04: governed outreach, provider authentication and suppression, after a separate product/legal gate.
EM-EXT-05: replaceable AI reply triage and manuscript intake, after EM-EXT-04 and processor/security review.

No extension is part of the first Codex prompt. Exact task dates are intentionally not promised; use measured velocity and source-approval lead times after EM-001.

## Task completion discipline

Update docs/22-implementation-status.md with status, commit/PR, commands/results and gaps. Map delivered requirements to test evidence in document 17. A task is Done only when its acceptance boundary is met; skipped tests, missing external approval and mock-only demonstrations remain explicit. Architectural deviations require an ADR, not silent stack expansion.

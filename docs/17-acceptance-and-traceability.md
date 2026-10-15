# 17 — Acceptance scenarios and requirements traceability

**Baseline:** 2026-10-08. Test IDs below are planned test families. They are not tests that have already passed. Actual evidence is recorded in document 22 and implementation reports.

## Functional traceability

| Requirement | Delivery task(s) | Acceptance family |
|---|---|---|
| FR-001 | EM-002 | AT-01 identity and tenant authorization |
| FR-002 | EM-002 | AT-02 membership and owner lifecycle |
| FR-003 | EM-003, EM-015 | AT-03 source support and approval |
| FR-004 | EM-006 | AT-04 keyword input |
| FR-005 | EM-004, EM-006 | AT-05 URL classification and refinement |
| FR-006 | EM-003, EM-006 | AT-06 preflight and launch |
| FR-007 | EM-006 | AT-07 complete pagination |
| FR-008 | EM-006, EM-009 | AT-08 deduplication and lineage |
| FR-009 | EM-004, EM-006 | AT-09 scope and crawl limits |
| FR-010 | EM-007, EM-008 | AT-10 metadata and roles |
| FR-011 | EM-007 | AT-11 HTML contacts and negative examples |
| FR-012 | EM-004, EM-007 | AT-12 browser reveal |
| FR-013 | EM-008 | AT-13 PDF boundaries and evidence |
| FR-014 | EM-EXT-01 | AT-14 OCR extension |
| FR-015 | EM-009 | AT-15 multiple correspondence roles |
| FR-016 | EM-009 | AT-16 association ambiguity |
| FR-017 | EM-008, EM-009 | AT-17 evidence completeness |
| FR-018 | EM-009 | AT-18 normalization and technical checks |
| FR-019 | EM-009 | AT-19 tenant-local identity dedup |
| FR-020 | EM-009 | AT-20 concurrent evidence-backed review |
| FR-021 | EM-010 | AT-21 lifecycle and progress |
| FR-022 | EM-005, EM-010 | AT-22 pause/resume/cancel/recovery |
| FR-023 | EM-011 | AT-23 filtered tenant result API |
| FR-024 | EM-011, EM-014 | AT-24 export safety and revocation |
| FR-025 | EM-005, EM-011 | AT-25 API idempotency/cursors |
| FR-026 | EM-005, EM-013 | AT-26 usage reconciliation |
| FR-027 | EM-004, EM-013 | AT-27 shared source throttles |
| FR-028 | EM-002, EM-014 | AT-28 audit and support grants |
| FR-029 | EM-014, EM-017 | AT-29 deletion and restore fences |
| FR-030 | EM-017 | AT-30 deployment modes |
| FR-031 | EM-003, EM-013 | AT-31 tenant configuration/entitlements |
| FR-032 | EM-015 | AT-32 connector certification |
| FR-033 | EM-EXT-02 | AT-33 bounded enrichment |
| FR-034 | EM-EXT-03 | AT-34 recurring search |
| FR-035 | EM-EXT-04 | AT-35 separate sending gate |
| FR-036 | EM-EXT-05 | AT-36 replaceable approved AI |

## Non-functional traceability

| Requirement | Task(s) | Evidence |
|---|---|---|
| NFR-001 | EM-002, EM-011, EM-017 | SEC-TENANT full boundary matrix |
| NFR-002 | EM-004 | SEC-EGRESS forbidden destination suite |
| NFR-003 | EM-002, EM-004, EM-017 | SEC-SECRETS/TLS/at-rest configuration tests |
| NFR-004 | EM-009, EM-016 | DATA-EVIDENCE completeness audit |
| NFR-005 | EM-016 | BENCH-PRECISION blinded sample and interval |
| NFR-006 | EM-005, EM-010 | REL-REPLAY worker/broker failure report |
| NFR-007 | EM-011, EM-016 | PERF-API reference-environment load report |
| NFR-008 | EM-010 | REL-CANCEL acknowledged and in-flight deadlines |
| NFR-009 | EM-004, EM-006, EM-011 | LIMITS URL/page/byte/query/export resource tests |
| NFR-010 | EM-013, EM-016 | PERF-FAIR multi-tenant blocked-source scenario |
| NFR-011 | EM-012 | UX-A11Y keyboard and automated/manual accessibility report |
| NFR-012 | EM-009, EM-012 | DATA-UNICODE/TIME round-trip tests |
| NFR-013 | EM-017 | OPS-RESTORE timed recovery report |
| NFR-014 | EM-018 | SEC-RELEASE findings and dispositions |
| NFR-015 | EM-001, EM-017, EM-018 | REL-ARTIFACT dependency/license/migration evidence |
| NFR-016 | EM-001, EM-016 | OFFLINE-E2E no external keys/network/mail/AI |
| NFR-017 | EM-010, EM-013 | OPS-METRICS reconciled, non-PII telemetry |
| NFR-018 | EM-003, EM-013 | CONFIG-PARITY server/UI/worker tests |

Business mapping: BR-01 → FR-004/005; BR-02 → FR-007/009/021; BR-03 → FR-016/017; BR-04 → FR-015; BR-05 → FR-001/030; BR-06 → FR-032; BR-07 → FR-024/025; BR-08 → FR-022/026; BR-09 → FR-021/026; BR-10 → FR-030; BR-11 → FR-028/029; BR-12 → FR-035/036 and NFR-016.

## Core UAT scenarios

**UAT-01 — Keyword to contacts.** Given tenant A and approved synthetic publisher, when an operator searches the topic, the system visits both fixture result pages, follows each eligible article once, excludes the footer support address, and shows correct author/contact evidence. Query and cap remain visible.

**UAT-02 — Search URL only.** Paste the fixture results URL without a separate keyword. It is classified as search results and paginated. Article/PDF URLs use their own route; a homepage returns refinement rather than a whole-site crawl.

**UAT-03 — First versus corresponding.** Article A lists Mira Rao first and Alex Chen as corresponding. Output must not assign Alex's email to Mira. Article B keeps two corresponding authors with their own addresses.

**UAT-04 — Dynamic contact.** Static parsing reports the tooltip contact unresolved; the approved browser route reveals it and retains locator/evidence. No mail client/contact form is submitted.

**UAT-05 — No email.** A successfully inspected no-contact article remains in Article outcomes, never receives a fabricated address, and does not fail the whole job.

**UAT-06 — Incomplete search.** A repeated next page, provider cap or configured page/article limit sets discovery_complete=false and a visible stop reason. No inaccurate 'all results processed' claim.

**UAT-07 — Mid-run interruption.** Terminate a worker after commit but before acknowledgement. Resume/replay yields the same stored associations and one usage effect, with no lost checkpoint.

**UAT-08 — Multiple organizations.** Log in to B and attempt to read A's job, item, evidence, review, export, object and event cursor; all fail without confirming contact existence. Switch organizations in one browser and verify cache/stream isolation.

**UAT-09 — Revocation and deletion.** Revoke a source policy or suppress a contact while export generation is active. Work is fenced; stale artifacts cannot be downloaded; deletion cannot be undone by a late worker.

**UAT-10 — Malicious inputs.** Private-network/metadata/redirect URLs, HTML instructions, executable download, giant PDF and CSV formula payloads all fail safely or remain inert data.

**UAT-11 — Human review.** Two reviewers edit the same association; one receives revision conflict. An address without evidence cannot be accepted. Corrected result preserves history and invalidates obsolete exports.

**UAT-12 — Dedicated deployment.** Same application images operate under customer configuration with tenant protections, approved egress and restore procedure. No external AI or hidden vendor support session is required for extraction.

## Acceptance evidence rule

A feature's UAT screenshot is not its security/contract test. Each completed requirement needs actual test artifact or human acceptance reference, code/connector version and date. Real customer contact evidence stays in private approved storage; repository reports use synthetic/redacted examples. Release cannot be marked complete while its required task is only scaffolded or mocked.

## EM-001 delivered test boundary (2026-10-10)

REL-ARTIFACT: `scripts/check_inventory.py` verifies both lock digests, exact inventory membership and reviewed declared-license set. Local frozen clean installs and frontend build are in [EM-001 evidence](../reports/em001-validation.md). This is dependency/scaffold evidence, not signed release or vulnerability certification.

OFFLINE-E2E: `tests/test_fixture_transport.py` checks all six committed fixture byte payloads through an in-memory allowlisted transport while socket/DNS functions are denied; hostile host, scheme, port, credentials, query and path cases have no network fallback. `tests/test_contracts.py` validates five examples; the documentation validator independently checks fixture links/counts and twelve negative cases. These tests do not run extraction or the core UAT workflow.

Configuration/metadata: `services/backend/tests/test_scaffold.py` verifies real FastAPI handlers/OpenAPI, unavailable tenant endpoints for two forged tenant headers, strict configuration and production-entrypoint rejection of fixture/identity-stub modes. This is not an RLS or authentication test. `apps/web/src/App.test.tsx` renders the actual component and checks disabled inputs plus honest empty/unavailable status; browser accessibility/UAT remains EM-012.

## EM-002 offline evidence boundary (2026-10-10)

FR-001/NFR-001/AT-01/SEC-TENANT: `test_tenant_foundation.py` uses a direct non-owner PostgreSQL login for two-tenant API/SQL/pool tests, forged context/body rejection, missing context and restricted identity/session tables. `test_oidc_boundary.py` and browser-flow integration tests verify the protocol/session boundary using a synthetic provider. This is not certification of a real provider or production infrastructure.

FR-002/AT-02: six roles, membership changes, CSRF/revision guards, session revocation, last-owner/atomic transfer/concurrent removal and lifecycle tests are implemented. NFR-003 evidence here is secure cookie/session/no-secret bootstrap behavior, not production TLS/at-rest encryption. REL-ARTIFACT extends the inventory and real first migration; destructive rollback limits are explicit. Actual aggregate and remaining gates are in [EM-002 validation](../reports/em002-validation.md).

## EM-003 offline source-policy evidence boundary (2026-10-10)

FR-003/AT-03 and FR-026/SEC-TENANT: `test_source_foundation.py` covers actual PostgreSQL/API source policy creation, owner/steward capability and denial for other roles, tenant isolation/RLS/pool reset, immutable current versions, permission review, stale revisions, suspension/revocation/expiry, platform disable and a concurrent proposal race through separate pools. Catalog fixture paths match committed files. Actual policy responses validate against the source-policy contract. `test_source_policy.py` rejects live mode, host/region/operation expansions, secret-like URL permission references, any synthetic credential, unknown fields and weaker rates/retention. Approved policy returns `execution_available=false`: these tests do not claim legal permission, protected network enforcement, extraction or export implementation.

EM-003 review correction: source-policy schema explicitly requires null credentials for synthetic-publisher; the committed negative credential fixture is rejected by pytest and documentation validation. No secret resolver or credentialed real source is enabled.

## EM-004a partial evidence boundary (2026-10-10)

SEC-NET/AT-04/NFR-002 remain partial. `test_fetch_safety.py` tests strict fixture URL classification, all-record public IP validation, scripted connection-peer pinning/certificate-required contracts, per-hop fixture redirect/scope checks, bounded bytes/observed absolute deadline, socket/DNS-free synthetic transport, refusal/no retry for source status and unsupported compression/media, and unconditional live/browser entrypoint denial. `test_fixture_gateway_tenant.py` tests actual PostgreSQL tenant/capability/current-version authorization and policy revocation before bytes are released. These are not actual DNS/socket/OS egress/browser isolation tests. The denied disposable sandbox probe and unmet full gates are documented in [EM-004a evidence](../reports/em004a-validation.md). No EM-004 production/security completion is claimed.

## EM-005 offline durability evidence boundary (2026-10-10)

AT-05/UAT-07/SEC-TENANT/FR-025: `test_durable_jobs.py` uses actual non-owner PostgreSQL for unique effects/usage and transactional completion outbox, lease expiry/recovery, pause/cancel fencing, actor/tenant denial, quota rollback/release, bounded retries, revocation/lifecycle barriers and defensive catalog permissions. `test_job_contracts.py` checks original-request/event parity and test-only loopback worker configuration. `test_real_broker_jobs.py` requires actual RabbitMQ/Celery subprocesses for duplicates, termination before commit, exit after commit before acknowledgement and broker application outage/recovery. Broker absence is an explicit skip/failure in required CI, not acceptance. These diagnostic markers are not extraction associations or full UAT-07 evidence; actual extraction and full deletion/artifact workflows remain dependent tasks. [Evidence](../reports/em005-validation.md).

## EM-004b partial diagnostic boundary (2026-10-10)

SEC-EGRESS/LIMITS: test_tls_fixture.py exercises actual pinned loopback TLS, verified CA/hostname, redirect/release authorization, credential-free requests and bounded deadline/header/body framing. This explicit test-only endpoint is not production DNS/public-egress certification. test_fixture_parser.py covers inert bounded UTF-8 HTML observations only; no contact/PDF extraction. test_isolation_configuration.py statically checks the restrictive container/CI definition. Actual parser network/OOM acceptance requires the separate exact-head parser job, currently pending; browser isolation is absent and full EM-004 remains partial. [Runbook](30-isolated-fixture-runbook.md) and [evidence](../reports/em004b-validation.md).

## EM-004c approved browser diagnostic boundary (2026-10-11)

SEC-EGRESS/LIMITS: bounded test-only browser IPC and profile semantic-delta tests pass without browser execution. Eighteen new protocol/configuration cases include one actual TLS mediation case; actual Chromium namespace/seccomp sandbox, network-path/subresource/WebSocket/service-worker/popup/download and credential-forwarding acceptance requires the separately reviewed browser workflow. Production/live entrypoints remain unavailable, full EM004 PARTIAL and EM006 gated. [Runbook](31-synthetic-browser-boundary.md) / [evidence](../reports/em004c-validation.md).

## EM-004d synthetic DNS/pinning boundary (2026-10-12)

SEC-NET/AT-04/NFR-002: `test_dns_fixture.py` adds actual loopback UDP/TLS validation, immutable route/peer behavior, changed DNS across requests/redirects, mixed/IPv6/duplicate/missing answers, bounded malformed/compressed/authority records, wrong owned UDP source, shared deadline, permission recheck and production refusal. `test_fixture_gateway_tenant.py` adds actual SQL/API current-policy browser mediation with synthetic DNS/TLS and no extra receipts for another tenant or revoked policy. Browser CI uses the same DNS-gated host TLS transport; the guest remains network-none with unchanged sandbox/profile/IPC gates. These establish only the declared synthetic diagnostic after actual CI, not public-DNS/firewall/production egress. Full EM-004 remains PARTIAL/EM-006 gated; see [EM-004d validation](../reports/em004d-validation.md).


## EM-004e planning-only boundary (2026-10-12)

SEC-NET/AT-04/NFR-002: `test_fetch_plan.py` covers immutable tenant/source/version/operation binding, complete public A/AAAA snapshot and exact selected-peer matching, absolute deadline, fresh authorization callback stages and bounded redirect re-planning. These are pure invariants with network denied, not actual DNS/socket/TLS/current-tenant or non-bypassable egress evidence. No existing transport is enabled or changed. Actual generalized transport and a reviewed controlled synthetic acceptance network remain required for full EM-004; EM-006 stays gated. See [validation](../reports/em004e-validation.md).

## EM-004f controlled protected transport boundary (2026-10-12)

SEC-NET/AT-04/NFR-002: `test_protected_transport.py`, `test_transport_topology_contract.py` and `test_transport_rpc_contract.py` cover bounded A/AAAA framing, full public snapshot selection, current authorization/redirect stages, production refusal, fixed isolated IPAM/route/resource checks and exact tenant scope/owned byte protocol. These are pure contracts, not actual isolation evidence. The distinct controlled transport job requires 12 actual synthetic DNS-selected IPv4/IPv6/TLS/redirect/rebinding/failure and current SQL tenant/browser cases; existing application/browser/parser/docs CI remains required. Full EM-004 is PARTIAL and EM-006 gated until exact-tree review and actual CI acceptance. See [runbook](34-controlled-transport-acceptance.md) and [validation](../reports/em004f-validation.md).

## EM-006 candidate traceability (2026-10-12)

Document16 EM-006 is mapped to `test_discovery.py` (input/suggestion/URL/caps/selectors/loops/dedup/schema), `test_discovery_tenant.py` (real SQL/RLS/current source/generation/deletion/replay/API/outbox) and `test_discovery_broker.py` (actual worker restart and duplicate delivery). Parser CI executes the same two search pages inside network-none and requires four unique articles/five entries/one duplicate; existing sandbox/OOM/transport checks remain required. This candidate is not accepted until independent exact-tree review and actual published-head no-skip CI pass. See [runbook](35-offline-discovery-runbook.md).

## EM-006 verified synthetic/offline checkpoint (2026-10-12)

Independent evidence review mapped document16/document06 criteria to exact head3bc8f234/tree80431dfb and merge34501136: application543/no skips/no pytest warnings includes real SQL policy/replay/cap/outbox and broker restart/duplicate tests; actual parser emits4 unique articles/5 entries/1 duplicate inside network-none with observed OOM enforcement; controlled12/browser/docs also pass. Original/effective query, explicit spelling confirmation, homepage refinement, explicit unsupported modes/API fallback, loops/selectors/exact caps and atomic checkpoint dedup have verified scoped coverage. This is VERIFIED IN DRAFT, unmerged; bounded offline EM-007 follows after this documentation checkpoint passes its own CI. See [full immutable evidence](../reports/em006-validation.md).

## EM-007 candidate traceability (2026-10-12)

FR-010/011/012 and document 16 EM-007 map to `test_html_extraction.py` (actual authored static facts/roles/negatives/budgets), `test_html_extraction_contracts.py` (observed-not-accepted/schema parity) and `test_html_extraction_tenant.py` (actual runtime SQL/RLS/current source/purpose/retention/replay/API). Existing controlled browser test additionally requires actual authored hover/DOM evidence and current-tenant persistence/replay; parser CI uses the same four article bytes under network-none. Existing network/sandbox/cleanup gates remain mandatory. Candidate review and actual new-head CI are pending; [runbook](36-offline-html-observation-runbook.md) / [validation](../reports/em007-validation.md).

## EM-007 verified synthetic/offline traceability (2026-10-12)

Independent authoritative evidence review mapped document 16 EM-007/document 07 and FR-010/011/012 to exact head 98208a9a / tree 4c58b53a and merge fe43d40c. Application 599/no skips/no pytest warnings includes eleven actual runtime SQL cases covering permission/purpose/retention, replay, forced RLS, viewer/operator, cross-tenant and current job/source/deletion barriers. Controlled 12 demonstrates actual authored tooltip reveal plus current-tenant persistence/replay and refusal after revocation; standalone browser preserves sandbox/subresource/credential controls. Parser observes all four pinned articles under network-none with actual OOM enforcement. Article A/B author roles and address evidence, unresolved static tooltip and explicit no-contact outcomes are verified; support/footer/reference/form/script content remains excluded, and ambiguous identities remain unresolved. This is VERIFIED IN DRAFT, unmerged. Accepted author-email associations and conservative normalization remain EM-009; bounded PDF evidence remains EM-008. The documentation checkpoint requires its own CI. See [immutable evidence and limitations](../reports/em007-validation.md).

## EM-008 candidate traceability (2026-10-12)

Document 16 EM-008, FR-013 and PDF portions of FR-010/017 map to `test_pdf_extraction.py` (actual authored byte/layout/page/role/evidence and refusal cases), `test_pdf_contracts.py` (unavailable claims and stronger runtime semantic checks), `test_pdf_dependency_boundary.py` (exact artifact/effective license/notices/unchanged isolation) and mandatory parser CI (actual pinned PDF outcomes within network-none/memory enforcement). First/corresponding observations, same-name uncertainty, line-wrap evidence and page-cap completeness remain distinct from accepted EM-009 associations. No new acquisition/persistence grant or migration is introduced. Full validation/review/actual new-head CI remain pending; [runbook](37-offline-pdf-observation-runbook.md) / [evidence](../reports/em008-validation.md).

## EM-008 verified synthetic/offline checkpoint (2026-10-12)

Independent evidence review mapped document 16 EM-008/document 07 and FR-013 to head 5e6568dc / tree 99f0257f and merge a9d584d: application 664/no skips/no pytest warnings; actual network-none nine-PDF parser outcomes and page/region/correspondence assertions; bounded stream/byte refusal and actual OOM enforcement; controlled 12/browser/docs success. The nine PDFs demonstrate two-page footnotes, raised markers, two columns, line wraps, unresolved same-name ambiguity, no-contact, encrypted/corrupt/image-only refusal and partial page cap. Nondefault or adjusted text state refuses instead of fabricating visible adjacency. Exact dependency/effective BSD-3-Clause AND Unicode-3.0 inventory and notices pass. This is VERIFIED IN DRAFT for the declared simple-Tj/standard-font/coarse-CropBox profile, with no OCR/acquisition/universal-layout or accepted-identity claim. Bounded EM-009 remains conditional on this documentation checkpoint's own CI. See [evidence](../reports/em008-validation.md).

## EM-009 candidate traceability

FR-015/016/017: test_associations.py covers separate first/corresponding roles, multiple correspondence, ambiguous same names, actual HTML/PDF provenance and conservative accepted evidence. FR-018/019 and DATA-UNICODE: normalization retains raw Unicode/local-part case/plus/dots, uses explicit IDNA domains, refuses unsupported SMTPUTF8, groups repeated tenant/batch candidates and flags normalization collisions. FR-020: test_association_review.py and test_association_tenant.py cover source-backed corrections, expected revisions, immutable history/outbox, role matrix, cross-tenant RLS, current source/session/deletion barriers and concurrent review. test_association_contracts.py checks actual API/schema shape and stronger runtime semantics. These are implemented test cases, not a claim that locally skipped PostgreSQL cases passed. [Runbook](38-offline-association-runbook.md).

## EM-009 independently verified scoped foundation

Independent authoritative reconciliation confirmed reviewed treea3ea255d, exact headbeae5deb/merge0073291d and all five actual CI job logs. Application748/no skips includes20 association SQL cases: role/CSRF, forced tenant RLS and current policy replacement, source/session/deletion barriers, replay preserving review, concurrent expected revision, atomic rollback/history/outbox and original observation/citation relationships. Pure actual HTML/PDF mapping and IDNA/Unicode/collision/probability negatives cover FR-015 through FR-020 and DATA-EVIDENCE/UNICODE. Controlled12/browser/parser/docs passed; one existing Pydantic alias-body warning remains disclosed. No scoped document16 EM-009 criterion is missing. [Evidence](../reports/em009-validation.md) preserves initial review/SQL failures and corrections. Scope is tenant/batch dedup, actual PDF pure mapping and retained HTML/browser persistence, with pending atomic review outbox. Documentation checkpoint-own CI remains required before EM-010.

## EM-010 candidate mapping

Document16 EM-010 and document10 lifecycle/progress/recovery requirements map to migration0007, progress state/binding/service/broker/models/stream/API, test_progress modules and the actual controlled tooltip composition. Current-policy/RLS/deletion and identity boundaries map to document05; IDs-only events and revision controls map to document09. Pure invariants do not certify real SQL/broker/SSE or browser integration; [runbook](39-offline-progress-runbook.md) and [candidate validation](../reports/em010-validation.md) retain exact-head acceptance gates.

## EM-010 verified synthetic/offline checkpoint (2026-10-13)

Independent authoritative reconciliation maps document16 EM-010/document10 to reviewed head16bb590e/tree58a708d8 and merge7a2130b: application862/no skips/no pytest warning summary;22 actual SQL cases and four actual broker cases; controlled12 with current leased tooltip persistence and durable item/job completion; browser/parser/docs success. Actual regressions establish unknown/capped totals remain truthful, all-no-contact completion, source-cap partial outcomes, interrupted checkpoint recovery, original-message redelivery and confirmed-message loss reconstruction, immutable effects, cancellation frontier conservation, auditable continuation/inherited quality invalidation and revoked-tenant replay refusal. Source review findings and actual-CI corrections remain in the [validation report](../reports/em010-validation.md). This is the declared synthetic foundation in Draft, unmerged; UI/live/production and commercial controls remain later tasks. The checkpoint's own exact-head gates precede bounded offline EM-011.

## EM-011 candidate traceability (2026-10-13)

Document16 EM-011 and documents03/05/08/09/12 map to migration0008, results models/cursor/service/API/broker/render and test_result/test_results modules. Composite tenant references/current owner-definer fences and revision members protect private snapshots/downloads. Pure adversarial format/cursor/envelope/role/schema tests are separate from18 required actual PostgreSQL/four real-broker cases. No independent source-review or actual acceptance claim is made yet; [runbook](40-offline-results-export-runbook.md) and [validation](../reports/em011-validation.md) preserve all exact-head gates.


## EM-011 independently verified scoped foundation

Independent authoritative reconciliation maps document16 EM-011 to reviewed head660e0dc5/treeca84f013 and merge45377b5: actual1035/no-skip application includes18 results SQL/four broker cases, covering role/CSRF/current tenant and source, immutable atomic snapshots/idempotency, private artifact permissions/integrity, revision/expiry/revoke/deletion and original-message recovery. Pure CSV control/formula refusal, literal XLSX/OPC and canonical cursor scope/parity cases complement actual server tests. Controlled12/browser/parser/docs passed at the same merge. One existing alias warning remains disclosed. Contacts/outcomes, accepted association, technical checks and outreach eligibility remain independent facts. No scoped document16 criterion was missing; UI/export previews and external event delivery are not claimed. [Evidence](../reports/em011-validation.md) preserves failures/corrections, limits and checkpoint-own CI before EM-012.

## EM-012 UI candidate traceability (historical pre-publication snapshot)

Document03 screens and EM-012 keyboard/error/empty/partial/tenant-cache acceptance map to actual React views, client/session pure regressions, operator models/tenant tests and the dedicated actual keyboard CI. All mutation permissions remain server-side. Migration0009 preview/field selection has current-runtime SQL regressions; client filters never authorize records. [Runbook41](41-offline-operator-ui-runbook.md) records unsupported screens/features and the diagnostic buffered-SSE/cancelled-download boundaries; [report](../reports/em012-validation.md) tracks six pending exact-head gates. Neither fixture expectations nor service skips prove working end-to-end UI.


## EM-012 independently verified synthetic operator foundation

Document16/document03 criteria reconcile to reviewed head6a3c607c/treea513d96c and merge8d2ad475. Application1132/no skips includes ten actual operator SQL/session/profile/role/cross-tenant/preview cases;25 React client/session tests include interrupted-frame cursor checkpoint and closed-scope refusal. Actual keyboard UI1/64.12s executes both input modes, partial/no-contact/empty/stale retry, source approval, evidence/native focus/review, async preview/download and actual usage/audit/settings with PostgreSQL/broker effects; delayed old-tenant contact/replay bodies and viewer-only scope cannot repopulate results or authorize writes. Controlled12/browser/parser/docs pass at the same merge. No scoped document16 EM-012 criterion is missing. [Evidence](../reports/em012-validation.md) retains failures and fixes, one alias-body warning and real-IdP/live/production/static-browser-acquisition/native-SSE-latency/disk-save exclusions. This checkpoint requires its own six exact-head gates before EM-013.


## EM-013 candidate traceability

Shared admission and usage (documents10/15/21; document16 EM-013) map to `test_admission_tenant.py`, `test_administration_tenant.py`, `test_admission_broker.py` and the required controlled transport source-contention case. Configuration/branding/support metadata map to strict model/schema/API tests, `branding.test.ts` and the existing keyboard CI. Pure tests do not establish actual source throttling, SQL atomicity/fairness or real broker separation. [Runbook42](42-offline-admission-runbook.md) and [validation report](../reports/em013-validation.md) preserve those pending acceptance gates and synthetic limits.


## EM-013 independently verified synthetic admission foundation

Document16 fairness, documents10/21 shared source controls and document15 usage reconcile to reviewed216a8c3b/treebb37d8e7 and exact merge84673c51. Actual application1267/no skips includes five administration SQL,19 admission-tenant and two broker cases; controlled13 proves real source spacing/admission and four other-tenant settled resolutions/private export during held source I/O. Current owner/revision/CSRF/policy/expiry/private-accounting guards, captured/current limits, duplicate/crash/cancellation settlement and discovery-only phase permission are exercised. Actual keyboard UI1 verifies configuration/usage/audit/settings and tenant-cleared branding. Browser/parser/docs remain affirmative. [Report](../reports/em013-validation.md) records no missing scoped criterion, unresolved warning/route-error causes and excluded live/production/commercial/support-grant/lifecycle features. This checkpoint requires its own six gates before EM-014.


## EM-014 candidate traceability

Document16 EM-014 and document12/document21 lifecycle criteria map to `test_lifecycle_contracts.py`, actual `test_lifecycle_tenant.py`, real `test_lifecycle_broker.py` and the receipt-backed deletion-before-release case in controlled transport. Current role/CSRF/cross-tenant, keyed privacy/withdrawal/no-resurrection, generation/parse/export fences, bounded purge/retention/replay and support expiry/revocation are separate assertions. [Report](../reports/em014-validation.md) and [runbook43](43-offline-lifecycle-runbook.md) preserve pending actual proof and scoped limits. No pure fixture or skipped test establishes lifecycle acceptance.


## EM-014 independently verified synthetic lifecycle foundation

Document16/document12/document21 acceptance reconciles to reviewed73a1043f/tree73dea867 and exact merge9ac9b930. Application1386/no skips includes30 lifecycle SQL and one real-broker tick: HMAC parity/tenant separation, conservative SQL/Python grammar, current owner/steward/CSRF/identity contention, both final-release/tombstone lock orders, stale parse/export refusal, permanent suppression/tombstones, bounded purge/retention/replay, denied private downloads and expiring/revoked existing-member metadata support. Controlled14 independently proves actual response-before-tombstone with no released bytes or post-deletion DNS. Actual UI1 and retained browser/parser/docs pass unchanged boundaries;31 frontend tests include cancelled current-scope search scheduling. Backup tombstone replay is specified, with actual restore deferred to EM-017 as document16 directs. [Evidence](../reports/em014-validation.md) discloses one alias-batch_id warning, historical failures and scoped limits. No scoped criterion is missing; this checkpoint needs its own six gates before dependent progression, and EM-015 still needs real source permissions.


## EM-017a partial restore candidate traceability

Document13 backup ordering, document21 retention/override invariants and document16 EM-017 restore/two-tenant criteria map to `test_restore_contracts.py` (exact disposable context, unsupported authority/accounting/history refusal, readiness/archive grammar) and required actual `test_restore_tenant.py` (same-version pg_dump/pg_restore, closed target before coherent privacy replay, physical no-resurrection/current artifact refusal, unaffected artifact hash, runtime cross-tenant RLS, job/accounting reconciliation and identifier-only broker reconstruction). These are candidate tests, not verified restore outcomes yet. Actual staging RPO/RTO and regional/encrypted infrastructure remain outside this partial exercise; no replacement prerequisite is invented. [Runbook](44-synthetic-restore-exercise.md) / [evidence](../reports/em017a-validation.md).

## EM-017b packaging prerequisite traceability

Documents13/16/21 reproducible packaging inputs map to `scripts/packaging/artifacts.py` bounded manifest/tar/chain helpers, `Metadata.Dockerfile` existing locked metadata-only runtime, `probe.py` in-process metadata/production-refusal/kernel checks and `run_acceptance.py` two uncached builds/owned cleanup. `test_metadata_packaging.py` supplies pure deterministic/tamper/link/path/marker/ownership/profile/minimal-import regressions; actual image evidence requires the separate packaging workflow. Existing tenant/worker/isolation/UI tests retain full synthetic assembly checks after deferred default API imports. This is partial EM-017, with no working service, staging, IdP, storage, signing/commercial-release or production RPO/RTO claim; see [runbook45](45-offline-packaging-prerequisite.md).

## EM-015a ScienceDirect prerequisite traceability

Partial document16 EM-015/document23 onboarding maps to `sources/sciencedirect.py` and `test_sciencedirect_adapter.py`: native request semantics, narrow DOI/PII inputs, bounded JSON, ordered authors, explicit missing contact fields, digest/row provenance, alias dedup/conflict and truthful pagination caps. Network-denied tests and unchanged configuration refusal are independent of live source certification. No public contract/schema, tenant persistence, HTTP authentication, full-text extraction or source-policy grant changes. [Runbook46](46-sciencedirect-adapter-prerequisite.md) and [evidence](../reports/em015a-validation.md) define the acceptance boundary; full EM-015/016 remain unmet.

## EM-015b XML contact observation prerequisite

Partial document16 EM-015, document07 roles/identity/evidence and document11 hostile-XML controls map to `extraction/sciencedirect.py`, `test_sciencedirect_article.py` and the newly authored `fixtures/xml/sciencedirect-article.xml`. Tests cover requested-article identity, original digest/element/attribute provenance, separate first/corresponding roles, direct published addresses, group/explicit affiliations, same-name/shared-address separation, missing/unsupported outcomes, namespace spoofing, duplicate IDs, DTD/XXE/encoding/resource refusals and no I/O. These are parser observations, not accepted identities, tenant persistence or live acquisition. [Runbook47](47-sciencedirect-xml-observations.md) and [report](../reports/em015b-validation.md) distinguish verified native documentation from the pinned wrapper assumption, and pure tests from pending actual XML isolation/integration. No full AT-32/source certification or benchmark claim.

## Owned held-response acceptance cleanup and diagnostics

NFR-009/LIMITS and NFR-010/PERF-FAIR retain the actual blocked-source processing/export test, with failure-safe fixed fixture release and bounded future collection in `scripts/isolation/transport_cleanup.py`. `test_transport_cleanup_contract.py` covers success ordering, once-only/exact acknowledgement, original assertion/cancellation preservation, send/receive/deadline/future/marker failures, poisoned fixture zero-send and poisoned-gateway/healthy-fixture separation, and composed already-successful/failed/cancelled future paths with exactly one final result collection. `test_browser_isolation_configuration.py` exercises the actual route-registration source statements to verify fixed start/completion marker ordering and failure/cancellation stopping before navigation. These pure contracts do not establish browser execution, repair admission/UI stalls, or replace exact-head controlled/UI/service CI. [Evidence and limits](../reports/owned-test-cleanup-validation.md).

## EM-015c synthetic XML integration candidate

AT-03/05/06 explicit source/media admission, AT-10/15/17/18 observed roles/provenance, AT-20 review, AT-21/22 recovery, AT-24 export and NFR tenant/isolation/privacy controls map to `test_xml_pipeline.py` and required actual `test_xml_pipeline_tenant.py`. The latter feeds the fixed network-none container’s returned observation into PostgreSQL, human review and CSV/XLSX, with tenant-B refusal, current authority changes during parse, generation/item/revision binding, locator-only review denial and once-only recovery. `parser_acceptance.py` adds actual hostile XML/resource cases to the unchanged network-none/OOM profile. Migration0012 extends latest0011 guards without grant/RLS changes; schema/example parity covers retained XML, explicit fixture-only source operation and progress reasons. Local service skips remain unmet execution evidence until own-head CI passes. [Runbook48](48-synthetic-xml-pipeline.md) / [report](../reports/em015c-validation.md); no real-source certification, wrapper verification, production or sending claim.

The EM-015c parser-build boundary also maps to `test_discovery.py::test_parser_build_context_includes_only_authored_copy_fixtures`: all fixture `COPY` sources must match the exact deny-all context allowlist, with missing-exception and overbroad-directory mutation sensitivity. This is static packaging evidence, not actual parser isolation.

Bounded opt-in UI worker observations map to `test_worker_diagnostics.py`: current-app/task/owned-queue signal filtering, observational callback return/exception identity, default-off behavior, closed cumulative counters and strict bounded-tail validation. This extends timeout evidence without changing readiness or completion criteria and does not certify a stall cause or broker acknowledgement.

The subsequent diagnostic-routing regression uses real `progress.publish`/pinned Celery message metadata and genuine Request/trace signals, covering both phases and success/empty/error outcomes without sockets. Catalog parity explicitly includes only the XML acquisition route; the decisive XML integration replays its original durable event and separately requires forged-event denial before emitting acceptance proof.

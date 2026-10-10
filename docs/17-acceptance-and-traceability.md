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

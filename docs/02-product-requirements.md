# 02 — Product requirements (PRD)

**Baseline:** v0.1, 2026-10-08. **Priority:** P0 = core release gate; P1 = post-core extension; P2 = separate later release. Detailed semantics live in the linked architecture, orchestration, extraction and policy documents.

## Functional requirements

| ID | Priority | Requirement and acceptance boundary |
|---|---|---|
| FR-001 | P0 | Authenticate users and authorize their active organization and role on every request; forged organization IDs are rejected. |
| FR-002 | P0 | Owners manage membership, role assignments and tenant settings; last active owner cannot be removed without a supported transfer. |
| FR-003 | P0 | Source registry shows connector capabilities, access mode, approval, expiry and health; unsupported does not mean empty results. |
| FR-004 | P0 | Keyword jobs require a source and nonblank original query; optional filters are validated; query changes are explicit. |
| FR-005 | P0 | URL jobs classify search, article, PDF and DOI URLs; unsafe URLs are rejected and homepages require refinement. |
| FR-006 | P0 | Preflight shows sources, caps, author selection, PDF/browser options, policy limitations and estimated units before run. |
| FR-007 | P0 | Discover article links across supported numbered, next-link, cursor, load-more or infinite-scroll pagination; checkpoint every unit. |
| FR-008 | P0 | Canonicalize safely and deduplicate eligible URLs/articles while retaining all evidence and discovery lineage. |
| FR-009 | P0 | Traverse only approved result/article/full-text/contact links within scope; stop loops and document truncation. |
| FR-010 | P0 | Extract title, DOI, journal, dates, author order, affiliations and explicit correspondence markers when present. |
| FR-011 | P0 | Extract addresses from article-associated visible text, mailto links and ordinary public contact attributes; exclude publisher support/ads/reference contacts. |
| FR-012 | P0 | Authorized browser worker supports tooltip/hover and click-to-reveal contact controls without sending a message or bypassing a challenge. |
| FR-013 | P0 | Parse machine-readable PDFs with page/region evidence and bounded resource use; encrypted/unsupported files are explicit outcomes. |
| FR-014 | P1 | Add OCR only when text is missing, within page/CPU limits and a reviewed dependency bundle; mark OCR evidence separately. |
| FR-015 | P0 | Represent first author and zero/multiple corresponding authors independently; no forced one-to-one mapping. |
| FR-016 | P0 | Store candidate addresses and evidence-based author associations with status, reason and version; ambiguous matches require review. |
| FR-017 | P0 | Preserve source URL, acquisition time, extraction method, document/page/DOM locator and evidence digest per accepted association. |
| FR-018 | P0 | Separate syntax/domain checks from identity confidence and delivery status; do not probe SMTP mailboxes. |
| FR-019 | P0 | Tenant-local deduplication reuses verified observations without erasing paper relationships or disclosing other tenants' data. |
| FR-020 | P0 | Reviewers can accept, reject, correct with new evidence, and unmerge mistaken associations; actions are versioned and audited. |
| FR-021 | P0 | Jobs expose lifecycle, stage counters, failures, discovery completion and stop reasons; no invented percentage when total is unknown. |
| FR-022 | P0 | Pause, resume, cancel and controlled retry survive worker restarts and enforce current policy/quotas. |
| FR-023 | P0 | Results support pagination/filtering by job, paper, role, source, association status and presence of email; no raw SQL from clients. |
| FR-024 | P0 | CSV/XLSX exports use explicit fields, tenant authorization, source export permission, formula-injection protection and expiry. |
| FR-025 | P0 | API supports idempotent job creation/start/export and stable cursor pagination with tenant-scoped authorization. |
| FR-026 | P0 | Per-tenant usage reservations, limits and reconciliation prevent repeated retries from becoming duplicate billable units. |
| FR-027 | P0 | Source-wide and tenant-source throttles govern all workers, including browser subrequests; 429/Retry-After is honored. |
| FR-028 | P0 | Audit sensitive reads, exports, administration, policy changes, review actions, deletion and exceptional support access. |
| FR-029 | P0 | Retention, suppression, deletion and stale-result invalidation apply to records, evidence, exports, caches and in-flight tasks. |
| FR-030 | P0 | Dedicated and hosted deployments use the same tenant-aware code with region-aware storage and isolated credentials. |
| FR-031 | P0 | Organization branding and entitlements are server-side configuration, not code forks or client-only restrictions. |
| FR-032 | P0 | Source onboarding supports a new site's adapter, approved scope, fixture suite, canary, health reporting and kill switch. |
| FR-033 | P1 | Optional wider-web/institutional enrichment uses explicitly approved sources and identity evidence; no automatic scope expansion. |
| FR-034 | P1 | Saved searches and recurring runs obey the same consent, source, quota and deduplication controls. |
| FR-035 | P2 | Outreach/mailbox/reply/manuscript modules are separately gated; no outbound actions exist in P0. |
| FR-036 | P2 | Optional AI provider is replaceable, separately approved and auditable; failure never invents data or broadens permissions. |

## Non-functional requirements

These are proposed acceptance targets on a documented reference environment, not guarantees about publisher response times.

| ID | Priority | Target / verification |
|---|---|---|
| NFR-001 | P0 | Zero cross-tenant access in the mandatory API, database, worker, storage, event and export adversarial suite. |
| NFR-002 | P0 | Every production fetch passes URL/DNS/redirect/egress checks; no access to internal/private/link-local/metadata networks. |
| NFR-003 | P0 | TLS for external/service connections; encryption at rest; secret manager or protected deployment secret files; no secrets in logs. |
| NFR-004 | P0 | 100% of accepted associations have evidence plus extraction/policy versions; unknown fields remain null/unknown. |
| NFR-005 | P0 | At least 98% observed author-email precision on the defined blinded pilot; report sample size and interval, not only a point estimate. |
| NFR-006 | P0 | Durable job ledger and replay tests show no lost committed results or duplicate result/usage effects after worker interruption. |
| NFR-007 | P0 | API metadata reads target p95 ≤1 second on 10 concurrent active users and 100k synthetic contacts per tenant; long work is asynchronous. |
| NFR-008 | P0 | Pause/cancel acknowledgement target ≤2 seconds; no new work after acknowledgement; in-flight work stops within configured deadline (default 90 seconds). |
| NFR-009 | P0 | Cursor lists max 200 items; finite download/page/byte/time/job budgets; resource exhaustion tests fail safely. |
| NFR-010 | P0 | At least two concurrently active tenants pass fairness tests; one source outage cannot starve other tenants/sources. |
| NFR-011 | P0 | Accessible keyboard operation, meaningful labels and status text; target WCAG 2.2 AA, verified rather than assumed. |
| NFR-012 | P0 | UTC persistence, Unicode names and emails preserved, explicit timezone display, reproducible export encoding. |
| NFR-013 | P0 | Recovery objectives proposed for commercial pilot: RPO ≤24 hours and RTO ≤8 hours, verified by restore exercise and contract scope. |
| NFR-014 | P0 | No unreviewed critical/high exploitable security findings at release; exceptions need documented owner/mitigation/expiry. |
| NFR-015 | P0 | Versioned, signed release artifacts, dependency inventory/licenses, migrations and tested rollback/forward-repair runbook. |
| NFR-016 | P0 | Core fixture workflow functions without external AI, paid source credentials, SMTP or customer data. |
| NFR-017 | P0 | Per-job structured metrics report wall time, HTTP/browser/PDF units, review effort, result counts and stop reasons without logging contacts. |
| NFR-018 | P0 | Customer-specific policy and deployment settings are validated, audited and consistent across frontend/API/workers. |

## Not acceptance criteria

Universal email coverage, real-time extraction of arbitrary websites, 500 ms total crawling, 100% correct author inference, infinite scaling, a fixed number of replaced staff, and universal legal permission are not release promises.

## Requirement ownership

The product owner approves workflow scope; engineering owns implementation and test evidence; source/data steward approves collection/export configurations; security approves production boundaries; customer/legal review resolves contracts and processing obligations. Traceability maps every FR/NFR to a task and test family in document 17.

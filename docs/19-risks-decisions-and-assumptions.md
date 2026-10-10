# 19 — Risks, decisions and assumptions register

**Baseline:** 2026-10-08. The core can be implemented offline without resolving every production decision.

## Established user requirements

EmailMonitor repository; keyword + selected publisher/source or URL input; automated result-by-result/article/PDF inspection; author/email/affiliation/evidence extraction; many customer organizations; GitHub documentation first, Codex implementation afterward. Downstream outreach/AI/manuscript workflows are later. The repository push is authorized; it is not authorization to crawl publishers, send emails, purchase services or change account/repository settings.

## Design decisions supplied by this pack

| ID | Decision | Rationale / change control |
|---|---|---|
| D-01 | Extraction-first modular monolith with separate workers | Limit initial complexity; ADR-0001 |
| D-02 | Tenant isolation from first persistent implementation | Multi-customer requirement; ADR-0002 |
| D-03 | Hosted and dedicated profiles share one codebase | Reuse and supportability; ADR-0002 |
| D-04 | Bounded approved traversal, explicit unknown/partial outcomes | Honest coverage and safe scope; ADR-0003 |
| D-05 | Evidence-backed observations, not guessed emails/probabilities | Identity reliability; ADR-0003 |
| D-06 | PostgreSQL outbox/leases with at-least-once transport | Recovery/idempotency; ADR-0004 |
| D-07 | No external AI dependency in core | Avoid early vendor/data-flow lock-in; ADR-0005 |
| D-08 | Dependency-license review and no automatic public license grant | Commercial distribution requires deliberate terms; ADR-0005 |
| D-09 | Public repository visibility remains unchanged | User selected this destination; no unrelated setting changes |

These are proposed architecture defaults for implementation. Changes require a reviewed ADR and aligned contracts/tests, not a hidden customer-specific fork.

## Risk register

| ID | Risk | Mitigation | Gate / owner role |
|---|---|---|---|
| R-01 | Source terms do not permit intended commercial extraction | Source/route/purpose approval; licensed API or narrower scope | Before live collection; data steward/legal |
| R-02 | Contact-tool/list rules apply even without sending | Product/jurisdiction review at onboarding, not only campaign time | Before sale/processing; owner/legal |
| R-03 | Wrong author-email associations | Explicit evidence, separate author roles, review, blinded audit | EM-009/016; engineering/QA |
| R-04 | Publisher layout/access changes | Versioned connectors, structural checks, canaries, kill switch | EM-015; connector owner |
| R-05 | Low permitted-source coverage | Pilot by source and use case; report unresolved; price realistic scope | EM-016; product owner |
| R-06 | Tenant leakage | RLS, composite FKs, API/worker/storage tests | Every release; security |
| R-07 | SSRF or hostile browser/PDF content | Enforced egress and parser isolation, limits | EM-004/008; security |
| R-08 | High browser/license/support costs | Metered units, adaptive route order, source qualification | Commercial pilot; operations |
| R-09 | Deletion undone by queued task or backup restore | Tombstones/generations, artifact revocation, replay | EM-014/017; engineering |
| R-10 | Unsupported/incompatible dependency licensing | Exact-version SBOM/license review; parser adapter | EM-001/018; engineering/legal |
| R-11 | Fake completion/benchmarks from AI coding | Evidence-based status, one task per PR, actual command outputs | Every task; reviewer |
| R-12 | Vendor lock-in / confidential data sent to AI | Core without AI, replaceable later adapter, processor gate | Future AI release; owner/security |
| R-13 | Public docs/code conflict with commercial confidentiality | No private info in repo; owner decides future visibility/license | Before proprietary implementation/distribution |
| R-14 | Source counts falsely imply completeness | Separate reported/discovered totals; stop reasons | EM-006/010; QA |
| R-15 | Solo-maintainer support load | Narrow initial sources, explicit support scope, reusable configs | Before paid production; owner |

## Assumptions to validate

A-01: named professional contacts can be processed for a customer-approved purpose on at least a useful subset of sources. Not established for every website.
A-02: initial sources have sufficiently stable/authorized HTML/API/PDF routes. Not yet benchmarked.
A-03: the selected stack can meet control-plane targets on a modest pilot environment. Exact resources and versions not yet measured.
A-04: customers will pay for source quality, evidence and workflow productivity beyond generic email tools. No price validation yet.
A-05: a hosted regional cell plus dedicated profile meets early customer needs; strict isolated-database-per-tenant can be added when contractually needed.
A-06: optional organization branding is useful; white-label/resale rights are not automatically granted.

## Open decisions and safe defaults

| Decision | Needed by | Default while unresolved |
|---|---|---|
| Legal entity, software license and repository confidentiality | EM-018 / before proprietary release | No license grant or visibility change |
| Initial real sources and commercial/API permissions | EM-015 | Synthetic fixtures only |
| Customer data-processing purpose/regions/rights | Real-data pilot | No live contact collection |
| Hosting provider and paid infrastructure | EM-017 | Local isolated development; no purchases |
| OIDC provider and customer domain | EM-002 staging | Test-only provider; production rejects it |
| Exact language/dependency/container versions | EM-001 | Verify supported stable matrix and licenses |
| PDF/OCR parser license choice | EM-008 / OCR extension | Reviewed text parser; OCR off |
| Quotas, retention and support contract | Pilot onboarding | Conservative proposals in document 21 |
| AI vendor / Jev credentials / pricing | EM-EXT-05 | AI off; no assumed vendor SLA |
| Sending countries, provider, templates and mailboxes | EM-EXT-04 | Sending off |

Do not ask the product owner to reapprove already specified core input modes or multi-organization scope. Surface only actual implementation/production blockers; continue independent offline work.

## EM-002 offline privilege separation decision

The authentication verifier and tenant SQL runtime are separate database principals and pools. Only the verifier principal may execute login-flow/session-creation functions; tenant runtime has no role-membership or SET ROLE path to it or the owner. This corrects the initial unshipped shared-role grant identified in independent review. Defensive catalog checks and normal synthetic login regressions cover the correction. A verifier-process compromise and production credential/process isolation remain staging security-review requirements; the test-only single-process assembly is not a deployment certification. No external authentication grant or production role was created.

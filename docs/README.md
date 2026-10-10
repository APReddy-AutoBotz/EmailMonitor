# Documentation map

**Design baseline v0.1 — 2026-10-08.** Core extraction capabilities below remain specified, not implemented; EM-001 scaffold evidence is in the status ledger. [Status ledger](22-implementation-status.md) is the authority for delivery progress.

| Document | Purpose |
|---|---|
| [00 Product charter](00-product-charter.md) | User-approved purpose, boundaries, product principles |
| [01 Business requirements](01-business-requirements.md) | Buyers, outcomes, business rules, commercial validation |
| [02 Product requirements](02-product-requirements.md) | Prioritized functional and non-functional requirements |
| [03 User experience](03-user-experience.md) | Screens, interactions, empty/error/partial states |
| [04 Architecture](04-architecture.md) | Components, trust boundaries, stack and repository layout |
| [05 Multi-tenancy and access](05-multitenancy-and-access.md) | Isolation, roles, organization lifecycle, support access |
| [06 Crawling and source connectors](06-crawling-and-source-connectors.md) | Search, pagination, URL classification, connector contract |
| [07 Extraction and identity](07-extraction-and-identity.md) | HTML/PDF/tooltip extraction and evidence-based associations |
| [08 Data model](08-data-model.md) | Entities, keys, relationships, constraints, deletion |
| [09 API and events](09-api-and-events.md) | Endpoint inventory, idempotency, event envelopes, errors |
| [10 Job orchestration](10-job-orchestration.md) | State machines, retries, progress, limits and recovery |
| [11 Security and threat model](11-security-and-threat-model.md) | Tenant escape, SSRF, hostile documents, secrets and tests |
| [12 Source governance and privacy](12-source-governance-and-privacy.md) | Collection permissions, processing, retention and export |
| [13 Deployment and operations](13-deployment-and-operations.md) | Hosted/private topology, CI/CD, monitoring, incidents, restore |
| [14 Test strategy and benchmark](14-test-strategy-and-benchmark.md) | Test layers, adversarial matrix, measured pilot protocol |
| [15 Commercialization and onboarding](15-commercialization-and-onboarding.md) | Multi-customer packaging, onboarding, pricing hypotheses |
| [16 Delivery backlog](16-delivery-backlog.md) | Dependency-ordered implementation tasks and deliverables |
| [17 Acceptance and traceability](17-acceptance-and-traceability.md) | Requirement-to-task-to-test mapping and UAT scenarios |
| [18 Future outreach and AI](18-future-outreach-and-ai.md) | Separate later-phase boundaries and provider abstraction |
| [19 Risks, decisions and assumptions](19-risks-decisions-and-assumptions.md) | Explicit choices, uncertainties, production gates |
| [20 References](20-references.md) | Primary sources checked for this baseline and limitations |
| [21 Configuration catalog](21-configuration-catalog.md) | Safe defaults, allowed settings and override precedence |
| [22 Implementation status](22-implementation-status.md) | Honest progress ledger and evidence requirements |
| [25 Development runbook](25-development-runbook.md) | Tested EM-001 setup, version/license matrix and rollback |
| [23 Source onboarding playbook](23-source-onboarding-playbook.md) | Site certification procedure and candidate-source register |

Architecture decisions are in [ADR-0001](adr/0001-architecture-and-stack.md), [ADR-0002](adr/0002-isolation-and-deployment.md), [ADR-0003](adr/0003-evidence-and-network-policy.md), [ADR-0004](adr/0004-durable-execution.md), and [ADR-0005](adr/0005-ai-and-dependency-licensing.md).

Machine-readable proposal contracts are in `contracts/`; examples are in `contracts/examples/`. These are normative starting contracts but not a running API. Synthetic inputs and expected observations are in [fixtures](../fixtures/README.md). Repository instructions and the first implementation prompt are at the root.

## Document governance

The user-approved priority is contact extraction from keyword/source or URL input, for many organizations. The rest of this pack supplies implementation decisions and explicit hypotheses. Treat security/source restrictions as invariants; treat throughput, pricing and coverage as targets to test. Change incompatible contracts and requirements together in a reviewed PR, add an ADR for architectural changes, and never overwrite measured results with design targets.

Versioning: documents use Git history; public API uses `/api/v1`; event/schema revisions use a `schema_version`; connectors and source policies have independent versions. Every result stores the extraction, association and policy versions used. Dates are ISO 8601; persisted times are UTC; UI renders the user's selected timezone.

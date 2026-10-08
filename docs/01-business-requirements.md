# 01 — Business requirements (BRD)

**Baseline:** 2026-10-08. Statements below are business requirements or explicitly labeled hypotheses, not a completed market study.

## Business outcome

Replace repeated manual article navigation and copying with a repeatable, evidence-backed academic contact workflow that can be deployed to many organizations. The buyer must be able to explain where a contact came from, how it was matched, what was not found, and what the job cost.

## Stakeholders

| Stakeholder | Needs | Decision authority |
|---|---|---|
| Publisher / services-company sponsor | Productivity, quality, predictable total cost | Pilot budget and purchase |
| Research / acquisition operator | Keyword/URL input, progress, usable records | Run permitted jobs and review assigned work |
| Data steward / compliance reviewer | Source permission, provenance, suppression, deletion | Approve permitted collection/export scope |
| Organization owner / administrator | Users, settings, source credentials, quotas | Tenant administration |
| IT / security | Isolation, identity integration, safe networking, deployment | Technical acceptance |
| Platform operator | Supportable releases, metering, incident response | Service operations, not automatic data access |
| Researcher / data subject | Appropriate handling and correction/removal routes | Applicable requests handled under customer policy |

## Business requirements

| ID | Requirement | Verification |
|---|---|---|
| BR-01 | Accept keyword + source or a URL without manual article opening | End-to-end UAT for both inputs |
| BR-02 | Process eligible results across pagination and show completeness limits | Discovery counts and stop-reason audit |
| BR-03 | Return author/contact details only with attributable evidence | Accepted-record evidence audit |
| BR-04 | Separate first/corresponding authors and support multiple correspondents | Multi-author fixture and human audit |
| BR-05 | Serve multiple organizations without data or credential leakage | Two-tenant adversarial tests |
| BR-06 | Add supported sources through a versioned connector and onboarding process | Connector certification checklist |
| BR-07 | Allow review, export and API consumption independent of sending | Export/API UAT with sending disabled |
| BR-08 | Recover interrupted jobs without duplicate contacts or duplicate usage charges | Worker-crash and replay tests |
| BR-09 | Make cost, quotas, unsuccessful work and policy blocks visible | Per-job usage reconciliation |
| BR-10 | Support hosted and dedicated customer deployment using one codebase | Deployment/restore pilot for both modes |
| BR-11 | Enforce source, privacy, retention, deletion and use restrictions | Policy and deletion test suite |
| BR-12 | Separate later outreach/AI/manuscript features from extraction | Core runs without mail or AI keys |

## Business rules

An extraction result may contain a paper without an email. Absence is a valid result. Never fill a blank using a guessed address. Confidence describes an association assessment, not consent, deliverability or guaranteed truth.

Source access, personal-data processing, evidence retention, data export, and outreach are distinct permissions. An organization's commercial source contract is not inherited by another organization. A permission suspension stops new work immediately and applies to queued work and exports at execution time.

Retain provenance even when article metadata is deduplicated. Do not merge people only because names match. Customer A's correction or suppression must not disclose its records to customer B. No outreach is sent solely because a contact is extracted.

## Operational process change

Current process: search → inspect result → open article → inspect author section/PDF → copy fields → reconcile duplicates → hand off.

Target process: choose source and query → inspect bounded plan → launch job → review evidence/ambiguity → approve applicable records → export dataset → report gaps and effort. Exceptions stay with humans, not hidden in successful totals.

## Pilot business case

Measure baseline on the same authorized paper sample and the same field/quality criteria. Record manual operator minutes, machine cost, review minutes, contact precision, contact coverage, records requiring correction, and usable exports.

Annual capacity value = validated hours saved per job × expected annual job count × loaded hourly staff cost. This is capacity value, not automatically a payroll reduction. Net value subtracts platform fees, implementation, source licenses, infrastructure, review, support and governance costs. Manuscript-conversion uplift is not included until a later outreach pilot measures it.

Pricing and willingness to pay remain hypotheses. Do not carry forward a claim that 50 people can be replaced or that a specific percentage of labor will disappear. Do not buy licenses or claim publisher partnerships as part of this documentation task.

## Commercial go/no-go

Proceed from pilot to paid release only when the target organizations can legally use the necessary sources, contact correctness is independently measured, review cost is economically acceptable, buyers accept the tested price, and security/support gates pass. Stop or narrow a source where collection rights, accessibility, ambiguity or economics make it unsuitable.

## Dependencies and unresolved choices

Source contracts, legal basis, authorized test data, hosting jurisdiction, identity provider, legal entity, licensing model, customer support commitments and first commercial buyers remain production decisions. These do not prevent a synthetic offline build. See documents 15 and 19.

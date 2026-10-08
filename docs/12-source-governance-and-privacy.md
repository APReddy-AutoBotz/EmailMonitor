# 12 — Source governance, privacy and permitted use

**Baseline:** 2026-10-08. This specifies product controls and review workflow, not legal advice or a guarantee that a country/source permits collection or marketing.

## Five separate decisions

1. May this organization acquire the page/API/PDF through this route?
2. May it extract and process named professional contacts for its stated purpose?
3. May it retain raw source or evidence excerpts, and for how long?
4. May it export/share the derived records, to whom and for what purpose?
5. May it contact the person through a later outreach workflow?

Approval of one decision does not approve the others. Publicly visible information is not a universal permission slip. A customer's publisher license does not automatically authorize a vendor to resell extracted contact datasets or another customer to reuse them.

## Source policy lifecycle

`pending_review → approved → suspended / expired / revoked`; amendment creates a new version rather than overwriting prior evidence. Required approval fields: organization, source and routes, exact domains/CDNs, purpose, permitted data fields, permission/contract/reference, reviewer and date, expiry/review date, robots/API handling, rate limits, retention/export permissions, region/processor restrictions and credentials reference where needed.

A planned job snapshots the policy version for reproducibility, but execution and export always consult current revocation/expiry and the more restrictive active controls. Unknown or expired policy blocks new collection. An operator can request onboarding; only authorized stewardship can approve it and cannot override prohibited access or invent a contract.

## Access controls and practical route selection

Prefer supported APIs and licensed/Open Access routes where appropriate, without pretending these always yield the same results as a publisher's website search. Wiley's current guidance routes TDM through its API and distinguishes commercial terms; PMC specifies supported automated retrieval services [S09, S10]. robots.txt supplies crawler rules, not authorization or a substitute for contract review [S05].

Respect access denials, authentication requirements, CAPTCHAs and machine-readable limits. A 403 does not trigger proxy rotation. Browser hover is supported only for ordinary public contact display on an authorized page. Source owners can request review or a stop; kill switches stop pending and active collection under the affected scope.

## Personal-data and jurisdiction review

Collect only professional contact fields necessary for the approved academic purpose. Do not collect home addresses, private telephone numbers, patient data, inferred health attributes, sensitive demographics or unrelated personal profiles. Institutional country is only an observation about affiliation, not proof of citizenship, residence or which law applies.

Legal review must cover where the customer/vendor/recipient are located, source terms, the purpose of collection, transparency/notice, lawful basis, data-subject rights, cross-border processing, and any rules restricting the tool or list itself. It must not reduce these questions to 'US allowed / EU blocked'. Australia's regulator expressly discusses restrictions involving address-harvesting software and lists; therefore review may be needed at collection/product-sale level, not only before sending [S11].

No preapproved global marketing-country matrix is provided. Unknown jurisdiction or unclear purpose enters review. Customers configure approved rules with counsel; software enforces those decisions and records their versions.

## Tenant data controls

Separate each customer's records, permissions and credential use. No global resale pool, cross-customer training or benchmarking with contact-level data by default. Non-content operational aggregates may be used only under contract and with suitable minimization. Dedicated hosting does not excuse unnecessary third-party transfers.

External AI is off in the core. Enabling an AI provider later requires specific processor terms, retention/residency review, approved fields, secret isolation, redaction and disclosure that data leaves the customer environment where applicable. A customer API key alone does not establish privacy compliance.

## Evidence retention and deletion

Default policy proposals are in document 21. Keep a minimal source excerpt and locator only where permitted. Raw PDFs/HTML are temporary by default; do not build an indefinite repository of copyrighted articles. Revalidation dates describe observations, not mailbox delivery proofs.

Provide correction, restriction, suppression and deletion workflows. Verify request authority proportionately without collecting excessive new data. Suppression prevents reuse/export and later contact; a keyed digest can minimize retained data but remains governed pseudonymous information. Scope can be contact, person, domain, source, job or organization as approved.

Deletion fences running tasks, revokes exports, removes live objects/records, and records backup-expiry and any justified legal hold. Reapply tombstones after restore. Do not return suppressed addresses in diagnostic exports. Legal holds are explicit scoped decisions with expiry/review, not an unlimited retention switch.

## Commercial and onboarding artifacts required before production

Customer agreement and permitted-use terms; data-processing roles and agreement where applicable; source/API licenses; privacy/notice process; retention schedule; subprocessor/region register; security support contacts; incident/breach procedure; data-subject request workflow; source takedown procedure; export restrictions. Store signed/confidential artifacts outside the public repository and reference them by ID only.

## Audit outcomes

The system can answer: who requested this job, on what approved purpose/source policy, which routes were used, where each contact was observed, why it was associated with an author, who reviewed it, whether it may be exported, and whether it has been suppressed. It does not claim that an automated policy decision is a legal opinion.

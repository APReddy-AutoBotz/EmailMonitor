# 23 — Source onboarding and connector certification playbook

**Baseline:** 2026-10-08. This is how the product expands across websites without promising universal support or hardcoding a different customer fork.

## Request intake

Capture organization, publisher/site name, sample keyword, sample search URL, sample article/PDF URLs, desired fields, intended purpose, required date/journal filters, expected volume, known access/API contract, robots/terms references and customer contact. Do not ask customers to paste passwords, session cookies or API keys into issues or this public repository.

A source request is not an approval. The product can retain the proposed plan and explain pending requirements while other approved-source jobs continue.

## Assessment checklist

Identify source and exact host/CDN relationships; website versus API search semantics; page type detection; pagination shape and caps; DOI/article identifiers; author markup; ordinary hover/click display; PDFs/full text; response type quirks; license/permission limits; credentials and origin scoping; provider rates; robots/API handling; data/export retention constraints; cost and maintenance owner.

Use public documentation and customer-authorized samples. Do not reverse-engineer access controls, defeat a challenge or assume a customer subscription permits vendor-wide commercial extraction.

## Connector implementation

Create a server-registered adapter with explicit capabilities and semantic version. Implement only reviewed routes using ProtectedFetcher. Add synthetic/sanitized fixtures for successful search/article/contact extraction, no contact, wrong layout, pagination exhaustion and loop/cap cases. Match authors/emails with evidence and return unsupported/ambiguous when necessary.

Keep unsupported filters explicit. A source API that returns broader/different results than the website must be named accordingly in the plan. A generic parser can process its content but does not replace an enumeration strategy or source authorization.

## Certification gate

Record permission reference/version/expiry, supported input types, exact source query semantics, permitted domains and redirects, successful and failure fixtures, tested page cap/exhaustion behavior, author mapping error audit, required credentials, effective limits, cost envelope, canary/rollback, maintainer and customer-facing known limitations.

Approve a limited live sample first. Scale only inside the agreed permission/usage budget. A source remains `pending_review` or `disabled` until these checks pass. Re-certify structural or license changes; a connector code release does not automatically renew an expired source policy.

## Initial source register

| Candidate | Initial role | Baseline state / limitation |
|---|---|---|
| Synthetic publisher fixtures | Offline keyword/search/article/tooltip workflows | Included fixtures only; live execution never permitted |
| Crossref REST API | Metadata/DOI discovery and approved API-backed search | Candidate; current API docs checked; not guaranteed author emails or identical publisher search [S08] |
| PMC supported retrieval services | Permitted structured/full-text route where available | Candidate; use documented automated services, not arbitrary PMC crawling [S09] |
| One customer-authorized publisher website | Actual publisher keyword/search URL and article extraction | To be selected; authorization and structural assessment required |
| Wiley TDM API | Example of a commercial/authorized publisher route | Candidate only; requires applicable permission/token; no browser crawler by default [S10] |
| Europe PMC API | Potential scholarly search/full text | Candidate; official REST docs need re-verification; no capability claimed |
| Institutional/repository sites | Optional later identity enrichment | Deferred; explicit scope/purpose and per-source review |

The first live pilot should include at least one actual approved publisher search interface so it validates the user's primary requirement, not only metadata APIs. Select three structurally different authorized families when available; absence of permission narrows the pilot rather than justifying a bypass.

## Ongoing health and change handling

Canary on a small authorized stable sample; monitor empty-author rate, missing required selectors, pagination errors, access/429 responses, response size and extraction quality. A sudden empty result is suspected drift until verified. Disable the affected version, preserve checkpoints, repair with fixtures, canary and resume. Customers see source degradation and partial outcomes.

## Source removal

Suspend new/pending requests, stop active fetches within bounded deadlines, revoke credentials as needed, invalidate affected export rights, apply retention/deletion terms, record the decision and notify authorized tenant administrators. Do not erase historical audit facts or continue using a previous approved version after revocation.

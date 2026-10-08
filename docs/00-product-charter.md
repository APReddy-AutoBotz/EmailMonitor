# 00 — Product charter

**Status:** design baseline, 2026-10-08. **Product:** EmailMonitor. **Owner:** repository/product owner; legal operating entity remains to be selected.

## Problem and user-approved goal

Academic publishing and related teams manually search publisher websites, open many article pages, inspect author sections and PDFs, and copy contact information. The product must automate that repetitive research workflow while making missing or uncertain information visible.

The user supplies either (a) a keyword plus a publisher/source, or (b) a URL. The system discovers matching articles, follows eligible search-result pagination, visits each scoped article and permitted supporting resource, and extracts the required details. Examples include publication title, journal, DOI, date, first author, corresponding author(s), email(s), affiliation(s), article URL, email evidence URL, and evidence locator.

**Primary outcome:** an auditable contact-research dataset, not an email campaign. The product must be reusable across many customer organizations. It must not be a single customer's hardcoded script.

## Input semantics

- Keyword mode: original query plus an onboarded source and optional date/article filters. Preserve the entered query. A suggestion such as `Myocardial Infraction` → `Myocardial Infarction` is a user-confirmed suggestion, never a silent rewrite.
- URL mode: search-results URL, article URL, direct PDF URL, or DOI URL. Classification uses validated URL, response metadata and supported connector evidence. A source homepage without a query is not a request to crawl its whole domain; return `INPUT_NEEDS_REFINEMENT` with useful choices.
- Unsupported/unknown source: accept the request for planning, but require source onboarding before network extraction. A public URL is not blanket permission to crawl.
- Wider-web enrichment: a later optional, bounded route. Do not silently leave the selected publisher to search the whole web. Show and audit any approved expansion.

## Meaning of 'all results'

Process every eligible, uniquely identified article discovered within the selected source, filters and explicit caps. Do not follow login, advertising, reference-list, social, tracker, unrelated-domain or arbitrary navigation links. Persist stop reasons including source cap, page cap, article cap, repeated cursor, no new results, quota, access block, timeout and user cancellation. A publisher's displayed result count is an estimate, not a verified denominator.

## Core release scope

A web application with organizations and roles; approved source registry; keyword/URL job planning; paginated discovery; queue-backed extraction; HTML and accessible document parsing; authorized dynamic browser interactions; author/email association; source evidence and timestamps; review; tenant-local deduplication; searchable results; CSV/XLSX exports; API; usage budgets; cancellation/recovery; audit; retention/deletion; deployment and support controls.

## Explicit non-goals

No universal-web success guarantee, arbitrary-site self-configuration by an LLM, login/paywall/CAPTCHA bypass, IP/account rotation to evade limits, mailbox existence promises, fabricated email guesses, sale of an unexplained global harvested-email database, shared contact pool between tenants, or autonomous email sending. Peer-review decisions and clinical/medical judgments are outside the product. A medical search term is a topic filter, not health advice or a basis to infer an author's health.

## Customer and product boundaries

Initial buyers are legitimate publishers, journal-portfolio operators and publishing-services teams with recurring contact-research work. Each organization owns its workflow configuration and customer data within the agreed contract. The platform owner manages software and operational infrastructure, not unrestricted browsing of customer records.

Use one codebase and migrations for hosted and dedicated installations. Allow organization-specific logo, display name, roles, quotas, retention and source credentials through configuration. Avoid custom forks. Multiple deployments do not imply automatic sharing or synchronization.

## Success definition

Demonstrate reduced staff minutes per evidence-backed author contact, high identity precision, useful coverage, bounded processing cost, traceable gaps, and no tenant leakage. Benchmark definitions are in document 14. No earlier conversation's estimated market sizes, replacement-headcount claims, model pricing or latency claims become product promises without revalidation.

## Release gates

Offline end-to-end proof precedes live source certification. Source and privacy review precede collecting real contacts. Security, restore and tenant-boundary tests precede customer production. Commercial terms and support ownership precede paid rollout. Sending and AI are separate future-release gates, not blockers for extraction implementation.

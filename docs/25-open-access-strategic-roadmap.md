# 25 — Open Access Publisher Strategic Roadmap & Feature Blueprint

**Document version:** 1.0  
**Target market:** Open Access (OA) Article Publishers, Academic Journal Editors, and Scholarly Societies  
**Baseline date:** 2026-11-11  

---

## 1. Executive Summary & Market Positioning

Open Access (OA) academic publishers face a high-stakes, competitive challenge: discovering, vetting, and inviting qualified researchers to publish manuscripts, edit thematic collections, and review peer submissions. 

Current outreach and editorial sourcing workflows are inefficient and fraught with risk:
- **Low deliverability & spam complaints:** Guessing email patterns or scraping secondary directory sites leads to high bounce rates, spam reports, and domain blacklisting.
- **Author role confusion:** Scraping indiscriminate emails from papers frequently reaches junior student authors or technical staff rather than the **Corresponding / Lead Author** who possesses the decision-making authority and budget for Article Processing Charges (APCs).
- **Brittle web scrapers:** Journal sites employ aggressive anti-bot protections (Cloudflare, Akamai, CAPTCHAs). Brittle scrapers break whenever a publisher updates their HTML DOM.
- **Compliance & GDPR risk:** Reaching out to academic researchers without verifiable provenance (paper title, DOI, publication date) and clear opt-out mechanisms violates EU/UK GDPR and CAN-SPAM regulations.

**EmailMonitor** solves this by delivering an **evidence-backed, compliant academic contact discovery and extraction platform** purpose-built for Open Access publishers.

---

## 2. Current Project Status Audit: Implemented vs. Pending

### 2.1 Codebase Reality Check

The project history encompasses **299 commits across 70 Pull Requests** staged on the integration branch `codex/checkpoint-recovered-focus-20261111` (PR #70). The foundational architecture adheres strictly to multi-tenant isolation, durable job orchestration, and zero-heuristic evidence tracking.

| Component / Layer | Current Status | Implemented Capabilities | Remaining Gaps |
|---|---|---|---|
| **Architecture & Multi-Tenancy** | **Verified (EM-002)** | PostgreSQL Row-Level Security (RLS), OIDC boundary, role capabilities, tenant-isolated transactions. | Multi-region production provisioning. |
| **Source Policy & Security** | **Verified (EM-003, EM-004)** | Egress filtering, SSRF guards, DNS pinning, connection-time timeout/size limits, policy fail-closed rules. | Whitelisting production live domains. |
| **Job Ledger & Execution** | **Verified (EM-005, EM-010)** | Celery/RabbitMQ transactional outbox, idempotent lease fencing, pause/cancel/resume, authorized SSE progress. | Cluster scaling & load tuning. |
| **Discovery & Preflight** | **Verified (EM-006)** | Keyword & URL planning, pagination limits, deduplication, search index abstraction. | Dynamic multi-page search traversal. |
| **HTML & Browser Extraction** | **Verified (EM-007)** | Metadata parsing, role markers, tooltip & click-to-reveal handling, non-executable sandbox. | Headless Chromium popup/focus CI runner stabilization. |
| **PDF Text & Layout** | **Verified (EM-008)** | Isolated byte-to-observation parser, standard fonts, footnote/corresp layout mapping. | Multi-column complex layout & non-Latin scripts. |
| **Identity & Association** | **Verified (EM-009)** | Deterministic author-to-email mapping, evidence links, unlink audit, no guessed contacts. | Institutional email disambiguation. |
| **Results & Exports** | **Verified (EM-011)** | Server-side cursor pagination, cryptographic digests, formula-safe CSV/XLSX generation. | Direct CRM/outreach API webhooks. |
| **Operator UI (Frontend)** | **Verified (EM-012)** | Complete React + TypeScript + Vite SPA, keyword/URL wizards, review workspace, evidence drawer. | Production auth provider binding. |
| **Usage & Fairness** | **Verified (EM-013)** | Multi-tenant rate limits, fair admission queues, tier enforcement. | Automated usage metering alerts. |
| **Lifecycle & Deletion** | **Candidate (EM-014)** | Staged deletion, tombstone replay, generation fences, contact suppression. | Automated database vacuum audit. |
| **Real-Source Onboarding** | **Partial (EM-015)** | ScienceDirect XML parser & isolated Elsevier sample adapter. | Live Open Access API connectors (Crossref, Europe PMC, OpenAlex). |
| **Deployment & Ops** | **Candidate (EM-017)** | Packaging runbooks, synthetic backup/restore exercises, disposable DB test scripts. | Production Kubernetes/Docker-compose live deployment. |
| **Release & Commercial** | **Unstarted (EM-018)** | Pending merge of PR #70 into `main` and production clearance. | Commercial license & customer contracts. |

---

## 3. Why Existing Scrapers Fail for Open Access Publishers

| Failure Point | Generic Scrapers | EmailMonitor's Solution |
|---|---|---|
| **Corresponding vs. First Author** | Grabs the first email found; sends APC invites to students who cannot pay or decide. | Strictly separates First Author, Senior Author, and Corresponding Author. Only verified correspondents receive outreach flags. |
| **Evidence & Provenance** | Returns bare emails in a CSV; no context. | Stores exact publication title, DOI, journal name, year, and raw text snippet where the email was located. |
| **Anticipated Anti-Bot Bans** | Attempts to bypass Cloudflare/CAPTCHA, resulting in IP bans. | Focuses on legal, authorized Open Access full-text JATS XML and REST APIs. Zero evasion tricks. |
| **Email Deliverability** | Includes syntax errors, obsolete institutional mailboxes, and honeypots. | Real-time DNS/MX fail-closed validation, syntax sanitization, and suppression filtering. |
| **Legal Compliance (GDPR)** | Violates GDPR Art 6 (Legitimate Interest) and Art 17 (Right to Erasure). | Automatic Legitimate Interest audit record generation and tenant-wide instant suppression lists. |

---

## 4. The "Sure-Shot Success" Blueprint: 6 Game-Changing Features

To make EmailMonitor the indispensable, market-leading tool for Open Access publishers, the following six core enhancements must be delivered:

### Feature 1: The "Open Access Goldmine" — Direct REST & XML Connectors (Zero-Scrape)
Instead of relying on fragile, slow HTML scraping of journal websites, implement direct ingestion adapters for the world's open scholarly databases:
1. **OpenAlex API Connector:** Ingest over 250 million scholarly works, author affiliations, ORCIDs, and open access full-text URLs in seconds.
2. **Europe PMC & PubMed Central (PMC) REST API:** Download structured, full-text JATS XML for millions of biomedical and life sciences papers without touching a browser.
3. **Crossref REST API:** Resolve DOIs, author identities, funding details, and licensed PDF links.
4. **arXiv & bioRxiv / medRxiv APIs:** Identify corresponding authors of recent preprints *before* they are submitted to competing journals.
5. **DOAJ (Directory of Open Access Journals) Connector:** Target journals with similar scope and APC models.

> **Impact:** 100x faster than browser automation, zero IP blocks, 100% legal, and 99.9% correspondence precision.

### Feature 2: High-Precision JATS XML Extraction Engine
Academic publishing standards rely on JATS (Journal Article Tag Suite) XML.
- EmailMonitor's XML extractor will parse `<contrib-group>`, `<contrib contrib-type="author" corresp="yes">`, `<email>`, and `<aff>`.
- Directly extracts structured author affiliations, department, city, country, and verified email address with zero heuristic ambiguity.

### Feature 3: Researcher Recency & Activity Scoring
Editors do not want emails from researchers who retired or left academia five years ago.
- **Activity Filter:** Identify authors who published an article within the last 6, 12, or 24 months.
- **Affiliation Freshness:** Compare institutional domains across recent papers to detect when an author has moved institutions.
- **ORCID Resolution:** Link ambiguous names (e.g., "Wei Zhang" or "J. Smith") to unambiguous ORCID records.

### Feature 4: 1-Click Cold Outreach & Editorial CRM Export Presets
Enable journal marketing teams and editors to export contact batches directly configured for their outreach platforms:
- **Pre-formatted Export Profiles:** Instantly.ai, Smartlead, Lemlist, HubSpot, Mailtrain, and SendGrid.
- **Dynamic Personalization Variables:**
  - `{{Author_First_Name}}`
  - `{{Recent_Paper_Title}}`
  - `{{Target_Journal_Name}}`
  - `{{Publication_Year}}`
  - `{{Affiliation_Institution}}`
  - `{{DOI_Link}}`
- **Formula-Safe Encoding:** Guarantees protection against CSV formula injection (`=cmd|...`).

### Feature 5: Enterprise Compliance & Universal Suppression Hub
Open Access publishers must adhere strictly to GDPR, CASL, and CAN-SPAM.
- **Documented Legitimate Interest:** Every contact record includes an immutable audit receipt stating the exact published work where the author publicly listed their correspondence address.
- **Universal Suppression List:** When an author unsubscribes or requests deletion (GDPR Right to Erasure), EmailMonitor suppresses the email across all current and future jobs within the organization.
- **Domain-Level Blacklisting:** Block entire institutions or competitor publishing houses from accidental outreach.

### Feature 6: Topic & MeSH Smart Search (Thematic Issue Sourcing)
Editors launching a Special Issue (e.g., *"CRISPR Gene Editing in Crop Resistance"*) need granular discovery:
- **MeSH (Medical Subject Headings) Filtering:** Query precise biomedical terms.
- **Boolean & Keyword Logic:** Combine keywords (`"perovskite" AND "solar cell" NOT "silicon"`).
- **Target Journal Exclusion:** Exclude authors who have already published in the editor's journal within the past 12 months to avoid spamming existing contributors.

---

## 5. Phased Delivery Roadmap

```mermaid
flowchart TD
  subgraph Phase 1 [Phase 1: Foundation & Merge]
    P1A[Resolve Chromium CI focus runner] --> P1B[Merge PR 70 to main]
    P1B --> P1C[Tag v0.5 Core Release]
  end

  subgraph Phase 2 [Phase 2: Open Access Connectors]
    P2A[OpenAlex REST Connector] --> P2B[Europe PMC JATS XML Engine]
    P2B --> P2C[Crossref & arXiv Previews]
  end

  subgraph Phase 3 [Phase 3: Quality & Recency]
    P3A[ORCID Disambiguation] --> P3B[Recency Scoring 12-24 mo]
    P3B --> P3C[Automated Syntax & MX Verification]
  end

  subgraph Phase 4 [Phase 4: Commercial & Outreach]
    P4A[Instantly / Smartlead Exporters] --> P4B[Universal Suppression Hub]
    P4B --> P4C[v1.0 Production Launch]
  end

  Phase 1 --> Phase 2
  Phase 2 --> Phase 3
  Phase 3 --> Phase 4
```

### Phase 1: Staging Reconciliation & v0.5 Core Release (Weeks 1–2)
1. Stabilize the isolated Chromium runner in CI to clear the remaining operator UI focus-guard regression.
2. Merge PR #70 into `main`.
3. Verify all 599+ backend and frontend tests pass in the integrated tree.
4. Publish official v0.5 core tag with verified multi-tenant RLS, durable Celery outbox, and operator React SPA.

### Phase 2: Open Access Direct Connectors & JATS XML (Weeks 3–5)
1. Implement OpenAlex API connector (filter by topic, publication date, open access status).
2. Implement Europe PMC / PubMed Central full-text JATS XML parser.
3. Build Crossref metadata resolver.
4. Integrate unified search query interface in the operator UI.

### Phase 3: Researcher Intelligence & Deliverability (Weeks 6–7)
1. Add publication recency scoring (flags authors with publications in 2025/2026).
2. Add real-time syntax, MX record, and disposable domain detection.
3. Link author records with ORCID profiles for unambiguous identification.

### Phase 4: Publisher Outreach Handoff & Enterprise Compliance (Weeks 8–9)
1. Deliver 1-click export presets for Instantly, Smartlead, and HubSpot.
2. Deploy universal tenant suppression and unsubscribed domain management.
3. Conduct held-out benchmark (EM-016) measuring precision against 1,000 real open access papers.
4. Deliver production deployment compose/Helm charts (EM-017) and commercial readiness checklist (EM-018).

---

## 6. Success Metrics & KPIs for Publishers

- **Extraction Precision:** $\ge 99.0\%$ correct corresponding author email identification on JATS XML and verified PDF sources.
- **Zero Guessed Emails:** $100\%$ of exported emails backed by cryptographic hash of the source document and exact text offset.
- **Outreach Deliverability:** $\ge 98.0\%$ inbox placement rate due to active-researcher scoring and MX health checks.
- **Time-to-List:** $< 60\text{ seconds}$ to discover and extract 500 relevant, active researcher contacts for a new Special Issue.
- **Zero Compliance Violations:** Complete audit trail for GDPR Legitimate Interest defense.

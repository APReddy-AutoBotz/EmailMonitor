# 20 — Primary-source references and verification notes

**Checked for this design baseline: 2026-10-08.** These references support specific technical/access considerations, not blanket authorization or measured product capability. Recheck mutable documentation and exact dependency licenses at implementation/release. Product policies, thresholds and architecture are our proposed design choices.

| ID | Primary source | Relevance and limitation |
|---|---|---|
| S01 | [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) | RLS, default-deny policy, owner and BYPASSRLS behavior; application design must test runtime roles |
| S02 | [Celery tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html) | Idempotency, acknowledgement, worker-loss nuances and timeouts; queue configuration alone does not provide exactly-once effects |
| S03 | [OWASP SSRF prevention](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) | URL/IP/allowlist and network-layer defenses; our complete test matrix is a product requirement |
| S04 | [Playwright locator API](https://playwright.dev/python/docs/api/class-locator) | Locator hover/click and DOM interactions; capability is not permission to bypass restrictions |
| S05 | [RFC 9309, Robots Exclusion Protocol](https://www.rfc-editor.org/info/rfc9309/) | Crawler rules are distinct from access authorization and commercial source rights |
| S06 | [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) | Text/layout/scanned-document limitations; no universal PDF success claim |
| S07 | [PyMuPDF license and copyright](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) | AGPL/commercial dual licensing requires a deliberate deployment/distribution decision |
| S08 | [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | Scholarly metadata discovery; does not establish guaranteed author-email coverage or rights to linked full text |
| S09 | [PMC developer guidance](https://pmc.ncbi.nlm.nih.gov/tools/developers/) | Supported automated retrieval routes and policy distinctions; not a blanket HTML crawling authorization |
| S10 | [Wiley TDM guidance and agreement](https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining) | API routing, commercial/source/article-license considerations; customer-specific terms may differ |
| S11 | [ACMA — Avoid sending spam](https://www.acma.gov.au/avoid-sending-spam) | Consent and address-harvesting software/list considerations; qualified review is needed for applicability |
| S12 | [OpenAI Codex AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md) | Repository instructions and discovery; official page redirected to ChatGPT Learn when checked |
| S13 | [GitHub repository licensing](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository) | Public visibility is not equivalent to choosing an open-source license; no license selected here |
| S14 | [RFC 5321 — SMTP](https://www.rfc-editor.org/rfc/rfc5321.html) | Mailbox/local-part and DNS routing semantics including address-record fallback; not a mailbox verification procedure |
| S15 | [RFC 7505 — Null MX](https://www.rfc-editor.org/rfc/rfc7505.html) | Distinguishes an explicit no-mail-service DNS declaration from ordinary absence of MX |
| S16 | [WCAG 2.2](https://www.w3.org/TR/WCAG22/) | Accessibility target; conformance must be tested |
| S17 | [Pydantic documentation](https://docs.pydantic.dev/latest/) | Typed validation/schema support; shape validation does not prove extracted fact correctness |
| S18 | [FastAPI deployment concepts](https://fastapi.tiangolo.com/deployment/concepts/) | Deployment considerations; final production topology remains customer-specific |
| S19 | [pypdf license](https://github.com/py-pdf/pypdf/blob/main/LICENSE) | Review exact chosen version and transitive dependencies before distribution |

## Explicit verification limits

The Europe PMC REST documentation URL could not be reliably retrieved during this preparation; its integration is a candidate and needs current official verification in source onboarding. pdfplumber is a parser candidate, not a completed exact-version license approval. No live publisher connector or contact extraction sample was executed for this documentation pack.

Earlier conversational claims about market counts, competitor prices, Jev availability/pricing/latency, savings or coverage were not adopted as verified product requirements. They require a separate current commercial/vendor study before use in sales collateral or an investment case.

No primary-source page grants universal access to every academic website. Source permissions, retention, exported derived data, privacy and marketing rules must be assessed for the customer, route, purpose and jurisdiction. Do not replace this register with unsourced numerical claims.

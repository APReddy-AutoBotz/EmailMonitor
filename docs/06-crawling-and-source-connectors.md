# 06 — Discovery, crawling and source connector specification

**Baseline:** 2026-10-08. All real publishers are candidate integrations until explicitly reviewed and tested. The fixture source is not a publisher partnership or live connector certification.

## Connector contract

Each server-registered connector implements capabilities rather than assuming every website supports everything:

```text
capabilities() -> supported input types, filters, pagination, extraction routes
classify(input, safe_response_metadata) -> page kind + confidence/reason
build_search(query, filters) -> approved request plan
parse_results(response, checkpoint) -> article links + next checkpoint + count hints
parse_article(response) -> metadata + author blocks + candidate contacts + allowed follow-up links
browser_plan(page_kind) -> bounded allowlisted interactions, or unsupported
healthcheck(fixture) -> versioned structural checks
```

A connector receives a ProtectedFetcher capability. It cannot create arbitrary sockets, load user-supplied scripts, install packages, choose a proxy, or change authorization. All returned URLs are candidates and must pass scope/security/source policy before scheduling. Browser plans come from reviewed code/config, not untrusted page instructions.

## Input classification

Validate scheme, hostname, port, length and credentials first. Resolve DOI redirects through the protected gateway. Use approved connector patterns, content type and safe parsing, not extension alone. Support `search_results`, `article`, `pdf`, `doi`, `collection`, `homepage`, `unknown`. A direct PDF response mislabeled as HTML is checked by signature within byte limits. Unknown or unsupported types produce an actionable result, not a speculative crawl.

Keyword mode invokes the selected source's actual supported search route. An API-backed fallback must be labeled as such and disclose differences in index/query/filter semantics. Do not tell the user an API query processed the identical publisher search-result universe unless verified.

## Search enumeration

Persist `(organization_id, job_id, source_id, checkpoint, page_fingerprint)` before/after each page. Adapters support numbered pages, next links, API cursors, POST search forms, load-more and bounded infinite scroll as applicable. Keep source-reported totals separate from discovered unique articles.

After each step: validate response; extract only article-result links; canonicalize; insert unique frontier records; persist next checkpoint; schedule next step only if budget and policy allow. Commit discovery state and outbox together so crashes do not skip a page. Replaying a page inserts no duplicate article unit.

Stop when the connector proves exhaustion, no next control exists, the next cursor repeats, page content repeats, a bounded no-new-results threshold is reached, source limit is reached, user cap is reached, quota expires, access is blocked, or cancellation occurs. Inconclusive stops set `discovery_complete=false` and report a reason. Do not equate missing pagination selectors after a website redesign with normal exhaustion.

## Link scope

Follow search-result article links, explicit article full-text/PDF links and author-contact controls needed for the selected fields. Do not recursively crawl references, recommendations, advertisements, navigation menus or all hyperlinks. Default maximum link depth from a result is 2; authorized source-specific mappings can state a different finite bound.

Allowed domains are exact hostnames and explicit subdomains in source policy. A PDF CDN requires its own approved relationship/route. Match hostname boundaries, not `endswith('publisher.com')` alone. Redirects and browser subresources also require approval. A consent/login page or alternate access host is not an automatic bypass route.

## Canonicalization

Preserve original, normalized and final URLs. Remove fragments for fetch identity; lowercase host; normalize IDNA; reject userinfo. Preserve query parameters needed for search, article identifiers, signed access and cursor state. Drop only connector-declared tracking parameters. Do not blindly sort/drop query parameters or equate different article versions. DOI-normalized identity can deduplicate article records while keeping all source observations.

Store credential-bearing URLs only in an encrypted short-lived execution field; redact tokens from logs/UI and canonical evidence links where possible. Do not make a signed PDF URL a permanent public provenance link.

## Fetch policy and throttling

Each fetch uses current source permission, purpose, tenant status, global safety policy and a quota lease. Web routes respect robots where applicable, but robots is not a license or authentication mechanism [S05]. API routes follow provider rules. Unknown permission is not treated as allowed. PMC explicitly distinguishes supported automated retrieval services from arbitrary crawling [S09]; Wiley publishes API/commercial TDM requirements [S10].

Apply deployment-wide per-origin and per-provider-account budgets, plus tenant-source limits. Read configured/provider limits at runtime; avoid hardcoded vendor quotas from old documents. 429 honors Retry-After. 401/403/challenges stop or enter an access-review outcome, not repeated credential/proxy attempts. Transient 5xx/timeouts use bounded exponential backoff and jitter. Operators can disable a connector globally with an audited kill switch.

## Browser execution

Fresh context per tenant/job or more restrictive scope; no persistent shared cookies. Allow only required selectors/interactions. A hover may reveal text already in `mailto`, title or DOM; inspect static data first. Click-to-reveal must not submit a contact form, send an email or accept new legal terms. Never launch a mail client. Abort unauthorized downloads, popups, WebSockets, service workers and internal destinations. Browser automation supports interaction, not access-control evasion [S04].

## Generic versus specialized extraction

Generic HTML/PDF parsing is reusable after approved acquisition. It does not imply generic permission or perfect discovery for unknown websites. A new source requires a manifest, scopes, approval, examples, fixture tests, paging strategy, DOM/PDF mapping, failure semantics, limits and canary. See document 23.

## Source certification outputs

Connector version; supported inputs and fields; allowed routes; filters actually implemented; pagination cap behavior; sample coverage/precision and denominators; known failure cases; permissions record and expiry; performance/resource envelope; egress host list; owner; rollback version; last canary. UI exposes this support matrix rather than claiming every site is supported.

# 03 — User experience and screen specification

**Baseline:** 2026-10-08. This is a functional design specification, not a live UI or finished visual design.

## Navigation and organization context

Persistent header: organization switcher, product/customer display name, source/environment indicator, notifications and user menu. Main navigation: Dashboard, New extraction, Jobs, Contacts, Review queue, Exports, Sources, Usage, Audit, Settings. Hide unauthorized actions but also enforce authorization in the API. Platform operations lives in a separate interface/context, not a hidden customer-admin tab.

Show the active organization on every screen and confirmation. Organization switch clears caches, cancels subscriptions, and reloads data under new server-authorized context. A stale tab cannot keep streaming another organization's data. No customer can see another tenant's names, counts, job IDs or quotas.

## New extraction wizard

### Step 1 — Input

Two tabs: **Keyword + source** and **URL**. Keyword tab offers an onboarded-source selector, query text and optional publication date/journal/article-type filters. URL tab accepts a search-results, article, PDF or DOI URL. Support paste, clear validation and retry without losing input.

Preserve `original_query` and `effective_query`; a spelling suggestion is presented as an explicit action. Default example topic: `Myocardial Infarction`. Source selector badges distinguish `active`, `approval needed`, `unsupported`, `temporarily unavailable`, and `credential required`.

### Step 2 — Scope and options

Choose max articles, max search pages, author target (`corresponding`, `first`, `both`, `all`), enabled permitted HTML/PDF/browser routes, and whether unresolved results remain in the output. Default author target is `both`; this never assigns a correspondent's email to the first author. Wider-web expansion and OCR are unavailable until their own feature/source approvals exist.

A homepage URL gives a useful refinement state: enter a keyword or paste a search/article URL. Do not launch a domain crawl. Unknown domains can enter source onboarding, not unrestricted extraction.

### Step 3 — Plan and launch

Display normalized input, connector, policy version, allowed domains/routes, limits, expected cost units if estimable, and caveats. Show `source reported results` separately from `verified discovered articles`. Estimate may be `unknown`; do not fabricate a cost or count. A source already approved for this organization does not require approval on every run.

Launch is available only when plan validation, source permissions and quota reservation pass. Approval-needed jobs offer `Request source review`. Explicit source revocation overrides an older approved plan.

## Job workspace

Header: job title, status, created by, active organization, query/URL, created time, connector/policy versions. Controls depend on lifecycle: Start, Pause, Resume, Cancel, Retry failed items. Cancellation text explains retained partial results and no refund assumptions.

Progress summary: result pages visited; unique article URLs discovered; article units terminal/total discovered; articles with contact; no contact; review needed; policy/access blocked; failed; duplicates skipped; current stage; unit/time usage. Show an indeterminate discovery indicator until enumeration ends. A percentage may describe completion of already discovered work only and must be labeled accordingly.

Tabs: Results, Review, Activity, Failures, Source plan. Every incomplete job displays a stop-reason banner such as `Stopped at the configured 500-article limit; more source results may exist`. `No contact found` differs from `PDF blocked`, `unsupported page`, and `could not complete search`.

## Result grid

Default columns: article title, publication date, first author, corresponding author(s), selected author/contact, affiliation, email state, association state, source/evidence, last observed. DOI/journal and technical checks are optional columns. Multiple corresponding authors expand into related rows; do not concatenate mismatched names and emails.

Filters: job/source/date, author role, has email, accepted/review/unmatched, evidence route, access outcome. Server-side cursor pagination; no attempt to load a whole tenant's database into the browser. Saved column views are user preferences, not schema changes.

## Evidence drawer and review

Show article identity, ordered authors, all candidate addresses, actual excerpt, source link, acquisition time, HTML locator or PDF page/box, extraction version, association reason and independent technical checks. Display an evidence strength label, never `99% certain` from a heuristic. A redacted/expired source has a clear state and requires revalidation before a new acceptance.

Review actions: accept association, reject candidate, choose another author, attach a new permitted source, mark obsolete, suppress or request deletion. Corrections require evidence and reason; optimistic concurrency prevents overwriting another review. The UI never permits inventing an observed address with no source.

## Export flow

Select contact dataset or article-status report; choose allowed fields, format and current filters. Preview eligible counts and excluded reasons (suppressed, no identity evidence, export restricted). Store export purpose and policy snapshot. Run asynchronously. Show expiry and revoke/download controls. A recheck at download blocks a revoked/suppressed record from an old generated artifact; regenerate a safe artifact rather than serving stale bytes.

XLSX should contain Contacts, Article outcomes and Readme/Provenance sheets where permitted. CSV consists of separate files in a ZIP when multiple tables are requested. Exports are not marketing-approved mailing lists; include source and use-state fields.

## Settings and enterprise screens

Membership and roles; organization display/branding; source policies and credential references; retention; quotas; export settings; OIDC configuration; audit; optional support-access grants. Never expose plaintext saved secrets. Platform support cannot impersonate a tenant invisibly.

## Accessibility and interaction quality

Use spacious enterprise tables with readable density controls, keyboard-accessible drawers, clear focus states and text status labels. Do not rely on red/green color alone. Announce job state changes accessibly without flooding screen readers. Preserve filters in navigation; confirm destructive actions; show UTC-derived local time with timezone; handle Unicode names without truncation of exported values.

## Required states

Every data view has loading, empty, permission-denied, network-error, stale and populated states. Job views additionally have approval-needed, quota-exhausted, partial, paused and cancelled states. Demo/sample mode is visibly labeled and never mixed with live records. EM-001 can render a scaffold but must not pretend extraction exists.

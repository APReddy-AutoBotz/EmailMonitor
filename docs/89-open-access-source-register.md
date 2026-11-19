# 89 — Open Access source register (pre-onboarding)

**Checked:** 2026-11-14 against publicly available provider documentation (links below). Terms and limits change; re-verify on the day a source policy is approved. This register is input to the [source onboarding playbook](23-source-onboarding-playbook.md) and the owner decision listed in [document 88](88-open-access-pipeline.md). It grants no permission: every source below is **fixture-only** in this repository until a source-policy record is approved and a production egress path exists.

## Summary for the owner decision

| Source | Used for | Access model (as published) | Practical limits (as published) | Content terms | Code status |
|---|---|---|---|---|---|
| Europe PMC REST (`www.ebi.ac.uk/europepmc/webservices/rest`) | Keyword/DOI search → PMCID; full-text JATS (`/{PMCID}/fullTextXML`) | No key documented | No official per-second figure found; third-party guides cite ~10 req/s and HTTP 429 when exceeded (**unverified**) | Full-text XML only for the open-access subset; articles stay copyrighted under a CC or similar license and the user is responsible for complying; check per-article license | Search planner/parser + full-text boundary implemented; fixtures only |
| OpenAlex (`api.openalex.org`) | Work discovery, ORCID/affiliation metadata, PMCID/DOI bridge | Basic queries work without a key; a free key (query `api_key=` or `Authorization: Bearer`) is required for cursor paging and raises the budget; usage-priced beyond the daily allowance | 10 req/s without key, 30 with free/prepaid key, 50 on annual plans; free key ≈ US$1/day budget; `per_page` ≤ 100; basic paging capped at 10,000 results | Metadata (OpenAlex states CC0 for its data — re-verify) | Planner/parser implemented; **no key field**: a key is a credential and must come from the credential resolver, never a request body |
| Crossref REST (`api.crossref.org`) | DOI resolution, search, author sequence | Public pool; polite pool via `mailto` parameter plus an identifying `User-Agent`; paid Metadata Plus key | Public 5 / polite 10 / Plus 150 (interval from `x-rate-limit-interval`); concurrency public 1 / polite 3; honour `x-rate-limit-*` and `x-concurrency-limit` headers, cache, back off; abusive clients get 403 | Metadata; abstracts may carry publisher copyright | Planner/parser implemented; fixtures only |
| bioRxiv/medRxiv API (`api.biorxiv.org`) | Recent preprints by date window or DOI; JATS path per preprint | No key documented | `details` serves **30 records per call** (cursor paging); no published rate limit — use a conservative client throttle | Each preprint carries its own license (some are not CC); bioRxiv site-wide TDM terms not confirmed | Planner/parser + DOI-keyed JATS fixture gateway; no keyword search exists upstream, so filtering is local |

## Owner decisions recorded 2026-11-19

* Europe PMC: **approved** as the first live source (implementation per document 90 still required; fixtures only until then).
* OpenAlex: **deferred** (no key or budget approved).
* Crossref: polite pool will use an owner-chosen **role mailbox** via configuration; none supplied yet, so fixture-only.
* bioRxiv/medRxiv: no decision; fixture-only.
* Licence stance: **allow but flag** (item 6 below; implemented as OA-026).
* Throttles (item 4) and retention (item 5) remain open.

Details: [document 19](19-risks-decisions-and-assumptions.md).

## Decisions needed before any live call (original list)

1. **Approve or reject each source** for the stated purpose (academic contact discovery for publisher outreach), per jurisdiction. A provider's API availability is not permission for this purpose; see [document 12](12-source-governance-and-privacy.md).
2. **Contact identity for polite use.** Crossref's polite pool needs a contact email in `mailto` and `User-Agent`. That must be a role mailbox the owner chooses (not a personal address, not committed to Git), injected through configuration.
3. **OpenAlex key and budget.** Decide whether to buy/obtain a key and the monthly spend ceiling. Without a key, cursor paging is unavailable, so OpenAlex discovery stays at one page per query.
4. **Rate limits to enforce** in the shared throttle (EM-013) — proposed starting values below, all below published ceilings.
5. **Retention** of raw full text: proposed none (parse then keep only evidence excerpts and digests), consistent with document 12.
6. **License stance**: whether contacts from articles with `license_category` of `other`/`unknown` (e.g. some bioRxiv preprints) are allowed, flagged, or excluded.

## Proposed starting throttle (owner to confirm)

Note: the current source-policy model enforces concurrency 1 and at least 5 seconds between requests per source (`sources/policy.Limits`). The table below is only reachable through a reviewed policy change; until then the 5-second floor applies. See [document 90](90-open-access-live-transport-design.md).

| Source | Requests/s | Concurrency | Page size | Max pages/job |
|---|---|---|---|---|
| Europe PMC search | 2 | 1 | 100 | 5 |
| Europe PMC fullTextXML | 2 | 1 | — | ≤ articles cap |
| OpenAlex (free key) | 5 | 1 | 100 | 5 |
| Crossref (polite) | 3 | 1 | 100 | 5 |
| bioRxiv | 1 | 1 | 30 | 10 |

## Gaps found while checking (tracked)

* The [strategic roadmap](25-open-access-strategic-roadmap.md) describes OpenAlex as free/unauthenticated and claims "zero IP blocks", "100% legal" and "99.9% correspondence precision". The first is outdated (keys and usage pricing since early 2026); the others are targets, not measurements, until EM-016 measures them.
* `BioRxivQueryPlanner.limit` allows up to 100, but the upstream `details` endpoint returns 30 per call; a live adapter must page by 30.
* OpenAlex keyless budgets are small; a live adapter must read `X-RateLimit-Credits-Used` and stop at the configured budget.

## Sources consulted

* OpenAlex — [Rate limits and authentication](https://help.openalex.org/how-to-use-the-api/rate-limits-and-authentication); user-group announcement of API keys ([openalex-users](https://groups.google.com/g/openalex-users/c/rI1GIAySpVQ)).
* Crossref — [Access and authentication](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/); [Announcing changes to REST API rate limits](https://crossref.org/blog/announcing-changes-to-rest-api-rate-limits/).
* Europe PMC — [Developers](https://europepmc.org/developers); [Copyright](https://europepmc.org/Copyright); [Help](https://europepmc.org/Help). The RESTful service page refused automated retrieval, so rate limits remain unverified.
* bioRxiv — [API summary](https://api.biorxiv.org/).

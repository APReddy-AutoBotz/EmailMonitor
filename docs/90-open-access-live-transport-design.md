# 90 — Design: live Open Access API access through the protected fetch layer

**Status:** proposal for owner review (2026-11-15). Europe PMC approved 2026-11-19. **Partly implemented (OA-027, 2026-11-19):** the exact search query grammar in `classify_url`, the Europe PMC connector (`sources/europepmc_live.py`) behind a `ProtectedTransport` port with approval, throttle, back-off and stop rules, and a Europe-PMC-only composition (`discovery/openaccess_live.py`). Still not implemented or enabled: the production transport, EM-013 shared throttle, persisted tenant policy and per-tenant flag. No live call is possible from this repository. It turns the decisions listed in [document 89](89-open-access-source-register.md) into a concrete, reviewable engineering task once the owner approves specific sources. Rules: [AGENTS.md](../AGENTS.md) items 3–6 and 9; existing boundaries: [document 33](33-shared-fetch-hop-planner.md), [document 49](49-disabled-provider-binding.md), [document 50](50-controlled-provider-gateway.md).

## Goal and non-goals

Goal: let an approved organisation run the Open Access pipeline ([document 88](88-open-access-pipeline.md)) against Europe PMC, OpenAlex, Crossref and bioRxiv with the same guarantees the offline pipeline has today, plus enforced egress, throttling, credentials and durable state.

Non-goals: generic web crawling, following publisher landing pages or PDF links found in API responses, any bypass of access controls, and any change to the extraction/association rules.

## Request path (per hop)

```text
OA work item (durable job, server-authorized tenant)
  -> typed planner (EuropePmcSearchRequest, EuropePmcRequest, OpenAlexSearchRequest,
     CrossrefQueryPlanner, BioRxivQueryPlanner) produces ONE canonical URL
  -> source policy evaluation (approved source, operation, purpose, limits, validity)
  -> shared throttle / fair admission (EM-013): per source, across tenants
  -> credential resolver (OpenAlex key only), dispatch-scoped lease, never logged
  -> protected gateway (EM-004): DNS snapshot + public-address pinning, TLS
     verification, no redirects off-host, byte/time ceilings, Connection: close
  -> response boundary: status, media type, size, SHA-256; JSON/XML parsed in the
     network-none parser worker (EM-008) for full text
  -> existing parsers -> observations -> association review queue (EM-009)
```

Every live response is untrusted data. It cannot add hosts, follow links, change limits or select credentials. Links such as OpenAlex `oa_url`, Crossref `link[]` or bioRxiv `jatsxml` are recorded as metadata and are fetched only when they resolve to an approved host and operation in the same policy (for bioRxiv JATS: `www.biorxiv.org`, a separately approved `fetch_xml` operation).

## Required changes, by component

| Component | Today | Change needed |
|---|---|---|
| `fetching/safety.classify_url` | Denies every query string except the Elsevier `view=FULL` selector | Per-source **exact query grammars** produced by the typed planners (allowlisted parameter names, bounded values, canonical ordering); anything else stays denied. No free-form query passthrough. |
| `sources/policy.PolicyProposal` | `execution_mode` is `fixture` only; one synthetic host | Add a reviewed `live_api` mode with a closed host set per source (`www.ebi.ac.uk`, `api.openalex.org`, `api.crossref.org`, `api.biorxiv.org`, optional `www.biorxiv.org`), `robots_handling` value for documented APIs, and approval provenance. |
| Policy `Limits` | ≥5 s between requests, concurrency 1, ≤500 articles/job | Keep as the default. If the owner wants faster API runs, add per-source limits below the providers' published ceilings (document 89) via an ADR; never above them. At 5 s, a 100-article Europe PMC run is about 101 requests ≈ 8.5 min. |
| Credentials | `CredentialResolver` port exists; no backend | OpenAlex key via the resolver (header `Authorization: Bearer`, never a query parameter, so it cannot reach URL logs). Crossref and Europe PMC need no key. |
| Contact identity | none | A configured role mailbox for Crossref's polite pool (`mailto` and `User-Agent`), owner-chosen, not in Git. |
| Gateway | Test-only composition | Production composition with the same single TLS/DNS path; honour `Retry-After`, `X-Rate-Limit-*`, `x-concurrency-limit`, OpenAlex `X-RateLimit-Credits-Used`; stop at a configured daily budget. |
| Orchestrator | Gateways injected; fixtures by default | Inject live gateways that call the protected gateway; the orchestrator code and outcomes stay identical. Per-source `source_errors` already isolate failures. |
| Persistence | Per request | Durable job + item rows (EM-005/010), idempotent per (source, work key), resumable cursors, retained digests/excerpts only. |

## Caching and data minimisation

* Cache search pages and full text **by digest for the job's lifetime only**; the default raw retention stays 0 hours (document 12). Excerpts and digests are what persist.
* Never store API keys, polite-pool addresses or response headers that echo them.
* Respect the per-article license: `license_category` is recorded on each outcome; the owner's license decision (document 89) becomes a policy rule, not code in the parser.

## Failure handling

| Condition | Behaviour |
|---|---|
| 429 / 503 with `Retry-After` | Back off per source, keep the item pending; never retry faster than policy |
| 403 / blocked | Stop the source for the tenant, mark items `failed` with a safe reason; no identity rotation, proxying or retry storms (AGENTS.md rule 4) |
| Budget reached (OpenAlex) | Stop discovery for that source; report partial results truthfully |
| Malformed/oversized body | `FetchDenied` reason, item `failed`; other items continue (already the offline behaviour) |
| Redirect off-host | Refused by the gateway |

## Acceptance tests (to write with the implementation)

1. Planner URLs pass `classify_url`; any other query string, host, scheme, port, fragment, encoded path or literal IP is refused.
2. Two tenants: the shared throttle serialises requests to one source; neither tenant can read the other's job, items, contacts or cache.
3. A response containing links to unapproved hosts causes no request to them.
4. OpenAlex key appears only in the lease-scoped header; never in URLs, logs, errors, exports or fixtures.
5. Back-off obeys `Retry-After`; 403 stops the source without retries.
6. Recorded-response replay (synthetic) through the live code path yields byte-identical observations to the offline gateway.
7. Kill/restart the worker mid-run: no duplicate contacts (deterministic IDs) and no duplicate billing units.

## Rollout

1. Owner approves sources, contact identity, budget, limits and license stance (document 89). *Status 2026-11-19: Europe PMC approved, OpenAlex deferred, Crossref role mailbox pending, licences allow-but-flag (done, OA-026). 2026-11-21: Europe PMC 1 request/s with concurrency 1, raw retention 0 hours (both in code, OA-028). Production transport blocked on the deployment egress decision (document 19).*
2. Implement behind a per-tenant flag that defaults off; run acceptance tests above against recorded synthetic responses.
3. Pilot one tenant, one source (Europe PMC: no key, full text with clear OA licensing), measured with the EM-016 protocol on approved held-out articles.
4. Add the other sources one at a time.

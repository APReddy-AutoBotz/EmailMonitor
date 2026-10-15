# 51 — Controlled provider keyword-to-export journey (EM-015f)

Status: local candidate, partial EM-015. This slice connects one controlled keyword search to the protected provider gateway, actual isolated XML parser, durable tenant observations, conservative review and existing CSV/XLSX. It is executable through the trusted `ProviderJourney` composition, with the same `Progress` work leases and application services. Default workers refuse these routes unless that composition is explicitly supplied. [Validation](../reports/em015f-validation.md) separates local checks from required actual PostgreSQL/container CI.

## Request and identity semantics

The distinct synthetic keyword `Controlled provider journey` plans a single registered search route. The ordinary synthetic keyword and original two-page/four-HTML-article flow remain unchanged. Native PUT `/content/search/sciencedirect` carries the canonical `qs`/`display` JSON request. Three authored result entries resolve through the server-owned catalog to two unique DOI/PII articles; conflicts and unknown identifiers refuse. The native bounded search reducer must establish one exhausted page before the durable reducer applies the customer's article cap. A capped job remains `completed_partial`; it cannot claim exhaustive enumeration or acquire a second article.

Article requests explicitly select GET `?view=FULL`. The [official Article Retrieval WADL](https://dev.elsevier.com/documentation/ArticleRetrievalAPI.wadl) documents META as the default and FULL as an available view. The typed request permits only exact FULL for article requests; search requests cannot carry a view. The shared URL classifier accepts only that exact query on the fixed API DOI/PII routes, retaining all existing fragment, host, encoded-path and arbitrary-query refusals. FULL is a requested representation, not a grant of full-text rights. API credentials alone do not establish entitlement. The [official search WADL](https://dev.elsevier.com/documentation/ScienceDirectSearchAPI.wadl) remains the native PUT reference. No live API call is made.

Three identities remain distinct:

- Durable source identity: `synthetic-publisher` and its registered `https://synthetic.publisher.example/provider-*.xml` URL, governed by the tenant's synthetic policy.
- Requested document identity: a normalized DOI or PII and an immutable owner-maintained alias/digest/profile registry.
- Transport identity: the canonical API request URL, fingerprint, requested FULL view and explicit `controlled_fixture` acquisition mode.

The trusted registry is catalog metadata, not caller input or a runtime-writable table. Search-provided URLs never become fetch targets. The catalog contains only the synthetic source; its SQL policy cannot authorize actual Elsevier traffic. Both authored XML fixtures use reserved example contacts. The existing single fixed XML route and its strict original digest/profile rules are preserved.

## Durable execution and source accounting

`ProviderJourney` re-reads current server-authorized membership/session, source policy/revision, discovery revision, execution lease/generation and deletion state before dispatch and at each existing provider-boundary callback. `BoundResources` maps only the exact current canonical request to its registered logical synthetic route and obtains a genuine `SourceAdmission` lease. Native search uses the `search` operation; XML uses `fetch_xml`. Shared source-wide spacing, tenant HTTP capacity and completion accounting apply. No database connection spans DNS, TLS, HTTP or parser work.

The controlled provider pipe must report exactly one owned acquired/completed resource ticket before success. Invalid, duplicate, missing or uncertain lifecycle frames poison the channel. Cleanup happens once; cleanup failure cannot hide the original protocol error or leave an uncertain channel reusable. Existing bounded SQL expiry remains the final fence if authority revocation prevents normal cleanup. Diagnostic no-resource mode remains solely for the pre-existing transport cases; the durable journey always supplies real resources.

Acquired XML bytes, identifier, digest and expected profile travel through the existing network-none parser. Its returned observation is compared against the original acquisition and trusted registry, then transformed into the retained envelope. `commit_xml` independently reloads the registry and current authority. SQL repeats the registry, provenance, privacy/deadline, generation/revision and execution-lease checks; an after-read cancel/revocation or after-parse deletion/retention change cannot commit stale observations. Excerpt retention controls still strip excerpts; locator-only evidence cannot be accepted as an author/address association.

A committed search page or article observation is recovered before further acquisition. A new durable lease derives the existing association batch/effect once; duplicate delivery does not re-fetch or re-parse. XML associations start in `needs_review`. Only evidence-backed human acceptance enters contacts/exports. Technical mailbox status stays `not_checked`, outreach stays `not_assessed`, and there is no sending path.

## Additive migration and schema

Migration `0013_provider_journey` follows `0012_xml_pipeline`. It adds only three exact synthetic routes and two owner-owned document bindings, extends closed route/kind/operation constraints, and replaces affected security-definer functions using their latest complete 0012 definitions. It preserves RLS, role grants, source locks, session/deletion/retention/lease fences and immutable-observation rules. No existing tenant policy is approved, rewritten or given new allowed operations. A tenant must already authorize each relevant operation under the existing policy mechanism.

The retained XML schema adds optional explicit provider provenance and two registered identifier/profile variants; an absent provider block retains exact legacy semantics. `article_observations` keeps the same storage shape. The general read cap becomes the existing 500-article platform ceiling rather than silently stopping after four fixture rows. Migration is forward-only: use a reviewed forward repair for durable state. A source revert by itself is not a database downgrade. No deployed database is changed by this candidate.

## Required actual acceptance

The controlled workflow runs a third sequential instance of the unchanged owned dual-stack topology, after both earlier modules clean up. Only another source-controlled XML fixture is copied into its private fixture build context. IPAM, security profiles, capabilities, mounts, network settings, command/frame/output limits, parser Dockerfile and dependencies are unchanged. Provider hostnames resolve solely to those owned fixture endpoints, and the only credential value is the existing fixed fake value.

The required 41-case controlled gate includes:

- The inherited 31 protected transport/provider cases.
- IPv4 and IPv6 native PUT search → two distinct FULL GETs → two actual isolated parses → same tenant SQL → explicit review → CSV and XLSX, with digest-backed evidence and source/batch links.
- Alias duplicate count, committed-observation crash/recovery with no repeat HTTP/parser, once-only effects, all three SQL tickets finished, zero active HTTP units, and SQL admission reservation spacing of at least five seconds.
- Tenant-B refusal and invalidation of already-created exports after retention change.
- An article-cap case proving only one article is fetched and the job stays partial.
- Seven authority races before acquisition, after actual response or after actual isolated parse, with no observation/effect persistence.

Pure tests also exercise registry conflicts, exact FULL URL/fingerprint semantics, no live policy/implicit dispatch, SQL provenance forgeries, pause/session/lease changes and owned-pipe cleanup. Collection and local service skips do not establish actual execution. The unchanged original four-article UI, parser/browser, packaging, docs and application gates remain required on the new exact head.

## Remaining pilot gates

The controlled journey now joins acquisition to retained review/export; it does not certify a real source. Actual source rights and FULL entitlement, approved representative response compatibility, real credential-store integration, live source-specific admission and a reviewed usable live DNS/egress composition remain separate activation gates. Default production configuration and worker registration remain denied. No user credential, source grant, network/security setting, deployment or merge was made. An authorized pilot must first resolve those exact gates; this candidate is not evidence that credentials are the sole missing step.

Next: immutable review, coordinator publication and all seven actual own-head CI gates. Only then reconcile the controlled proof and select the next bounded pilot prerequisite.

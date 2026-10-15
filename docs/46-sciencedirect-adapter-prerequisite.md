# 46 — ScienceDirect adapter prerequisite (EM-015a)

Status: local candidate; offline parser/request-planning prerequisite only. EM-015 live certification remains incomplete. There is no migration, new dependency, credential, source activation or deployment.

## Executable boundary

`services/backend/src/emailmonitor/sources/sciencedirect.py` supplies reusable, inert adapter primitives:

- `SearchRequest` preserves the original general query (including Boolean case and spelling), produces the native V2 PUT JSON body and a disabled request description for the fixed Elsevier API origin/path. It supports query, offset, page size and relevance/date sorting only. Unknown fields and unsupported filters are rejected, not silently discarded.
- `normalize_identifier` accepts a bounded bare DOI, journal/book PII, HTTPS doi.org DOI URL or exact ScienceDirect article/PII URL. `article_path` builds only a normalized article retrieval path. It does not fetch a resource or infer which full-text view is permitted. The intentionally narrow DOI grammar rejects other valid DOI forms as unsupported.
- `parse_search` consumes caller-supplied UTF-8 JSON bytes with a 1 MiB byte cap, depth/node limits, duplicate-key refusal, strict result/author bounds and fixed refusal reasons. It returns ordered author metadata, DOI/PII, title, source title and publication-date text. Response URLs are ignored, never followed or used to broaden egress. Date text is retained as metadata, not validated as an actual publication date.
- Each row has the input digest and JSON row locator. These are metadata provenance, not contact or correspondence evidence. Missing authors remain empty. Search does not establish emails, affiliations or corresponding-author roles: `contact_status=not_available_in_search` remains explicit.
- `advance` performs bounded pure pagination with DOI/PII alias deduplication. A more complete duplicate replaces a whole observed row with its own provenance; it never combines separately sourced fields. Conflicting or bridging identifiers stop as partial and retain only earlier pages. Result offsets count raw rows, not deduplicated articles. Page/article/provider caps, repeated payloads, no new identities, changing counts and incomplete pages remain partial with a reason.

The state is an internal trusted composition value, not a public resumable token. Production callers must bind it to current tenant, source policy, query/job, generation and lease before persistence or execution. The parser does not grant authorization or implement tenant storage. A response must be accepted only after an approved protected transport validates HTTP status, content type, origin, size, current policy and authentication. Deserializing untrusted checkpoint state is unsupported.

`completed/reported_exhausted` describes only the bounded response sequence relative to the publisher-reported total, not a verified publisher-wide denominator. A nonzero starting offset describes that suffix only. Neither a parsed row nor an open-access marker permits retrieval/export or proves that contact extraction occurred.

## Sources and semantics

Reviewed October 15, 2026:

- [ScienceDirect V2 migration/schema](https://dev.elsevier.com/tecdoc_sdsearch_migration.html): request `qs` and `display` fields, paging and response metadata structure.
- [Search API reference](https://dev.elsevier.com/documentation/ScienceDirectSearchAPI.wadl): native PUT endpoint and JSON media type.
- [Public response example](https://dev.elsevier.com/payloads/search/scidirV2PUTSearchResp.json): field shapes and author order, including journal and book PIIs.
- [Article retrieval reference](https://dev.elsevier.com/documentation/ArticleRetrievalAPI.wadl): DOI/PII retrieval routes and entitlement-dependent views.

The selected route is explicitly ScienceDirect API V2 general search, not website scraping. Provider documentation describes website-aligned search; this implementation has not independently established live website/API equivalence or filter parity. Search URLs, PDFs, full-text parsing and filters beyond this declared subset are unsupported. A homepage is not a whole-site crawl request.

The private documentation-sample check parsed two metadata rows with two/four authors and explicit missing contacts. The sample's incomplete page is not discovery-complete. It is documentation compatibility evidence only, not a live API request or live extraction. Actual researcher records and the sample payload are not committed. Tests use original synthetic names/titles/identifiers and reserved-domain inert links.

## Safety and packaging

No adapter registration, API/UI wiring, network client or secret access exists in this slice. Existing `Settings` live-source refusal, fixture-only source policy, tenant boundaries, protected gateway and source-approval rules remain unchanged. No production flag can enable this adapter. Importing or parsing has no outbound behavior. Existing metadata-image packaging still excludes extraction/source modules; this does not assemble the working service.

## Next executable integration

The bounded XML contact observation candidate is now described in [runbook47](47-sciencedirect-xml-observations.md). Its pure byte parser does not establish network-none process acceptance. Next verify isolated XML-worker integration and actual authorized response compatibility. Keep transport and activation separate. Then connect V2 discovery and article retrieval through the protected fetch layer, current tenant/policy/quota checks and secret references; never put keys in URLs, code, logs or repository files.

Before a bounded live pilot, establish the actual organization's approved API entitlement/authentication route, allowed use/retention/export and request budget, and certify an authorized sample. No claim is made that the user lacks an agreement or credentials; their existence and applicability remain unverified.

## Verification and rollback

See [EM-015a evidence](../reports/em015a-validation.md). Focused tests cover malformed/hostile inputs, caps, pagination/dedup/conflicts, provenance, no-network behavior and unchanged live refusals. Existing aggregate checks and exact-head CI are required before accepting this slice. Remove the unregistered module/tests to roll back; no database or deployed runtime changes occur.

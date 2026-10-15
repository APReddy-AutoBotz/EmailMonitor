# 47 — ScienceDirect XML contact observations (EM-015b)

Status: local candidate, partial EM-015. This is an inert byte parser with synthetic tests, not a live connector, acquisition service, isolated-runtime certification or production capability. No dependency, migration, credentials, source activation, API/UI wiring or deployment changes.

## Supported profile

`extraction/sciencedirect.py:parse_article(bytes, ArticleIdentifier)` supports a bounded journal-head profile. Inputs are strict UTF-8 XML, at most 2 MiB, 20,000 elements, depth 48, 1 MiB decoded text, 32 attributes per element and 2,048 characters per attribute value. It parses with the existing Python standard library. DTDs, entity declarations, external entities and processing instructions are rejected; predefined XML escapes and numeric character references remain literal document text. No URL, external schema, XInclude or document instruction is followed.

Two explicitly labeled envelopes are recognized:

- `xocs_document`: native `xocs:doc`, requiring the requested DOI or unformatted PII in its own `xocs:meta`.
- `article_retrieval_response`: a pinned candidate wrapper `full-text-retrieval-response` in `http://www.elsevier.com/xml/svapi/article/dtd`, requiring the requested identifier in `coredata` and the native document in `originalText`. A same-kind identifier present in native metadata must also agree; overlapping DOI/PII values are checked for conflicts. The public XML sample was unavailable here; this wrapper namespace is a compatibility assumption, not verified real-response acceptance.

The native document path is `xocs:doc/xocs:serial-item/ja:article/ja:head/ce:author-group`. Expanded namespace URIs, not prefix spelling, identify elements. The parser preserves direct contributor order across groups, including simple collaborations. `first` denotes first listed contributor, including a group if listed first; it does not claim sole or unequal contribution. Unknown corresponding status is null. A referenced `ce:correspondence` asserts correspondence only; an email alone does not.

Only direct author/collaboration `ce:e-address` email elements produce candidates. Exact literal text or an exact `mailto:` attribute is required; conflicting text/href, encoded or multi-address forms stay partial. Non-email URL/social entries are ignored. Addresses remain raw observations, `needs_review`, technically `not_checked`, delivery `unverified`, outreach `not_assessed`. No address guessing, syntax/domain/mailbox validation or identity acceptance occurs.

Affiliations use explicit same-group references, or the documented implicit group relation only when the group has no references and all affiliations are unlabelled. Human-readable `ce:textfn` is retained; structured-only affiliations and unresolved links to present group affiliations stay partial. A correspondence postal address is never silently copied as an affiliation. Equal-contribution footnotes do not assert correspondence.

## Evidence and integration boundary

The parser reuses existing `AuthorFact`, `CandidateFact` and `Evidence` fields without reclassifying XML as HTML. Its envelope has `route=article_xml`; evidence is structured metadata. Each response has a SHA-256 digest and canonical identifier-only source URL. Every fact has an exact positional XML element/attribute locator and an actual normalized excerpt; linked candidates also retain author-context evidence. `xml:/1/2/3` means element-child indices from the document root, independent of prefix spelling; attributes append `/@refid` or `/@xlink:href`. Comments and processing instructions do not count as elements (processing instructions are refused).

The source URL is derived from the requested identifier, not trusted response links or a receipt that the resource was fetched. Future acquisition must bind the digest, actual safe source URLs, timestamp, current tenant/source/purpose/policy, item generation and lease. These bytes do not authorize collection, retention, export or persistence. No existing synthetic persistence or association path accepts the new envelope automatically. Reusing fact models does not bypass their source-specific service gates.

## Honest outcomes and exclusions

- `observed`: supported head profile produced candidates.
- `no_contact`: no email candidate in the supported head profile. It does not mean no email anywhere in the article or elsewhere.
- `partial`: supported authors with unsupported email/affiliation or unstructured contact material; reasons remain visible.
- `unsupported`: missing full text/identity/authors or unsupported/ambiguous structure, with no author or candidate assertions.
- Fixed `FetchDenied` reasons: unsafe/malformed/over-limit XML, duplicate/invalid IDs or mismatched requested article. Raw source text and parser error details are not exposed.

Books, converted articles, nested collaboration members, alternative name markup, plural `ce:cross-refs`, cross-group correspondence references and some valid email/affiliation encodings are deliberately unsupported. Cross-group correspondence is valid Elsevier markup, but this profile does not resolve it. Same-name authors and shared addresses retain separate positions and evidence; no global identity merging occurs. Body, references, support text and source instructions never become author contacts.

Pure no-I/O tests are not network-none process acceptance. No XML payload has yet run through the actual isolated parser worker, protected transport, tenant persistence, UI or export. Existing live/production refusals and all seven inherited CI gates remain required. Metadata packaging still does not include the working extraction service.

## Primary documentation reviewed October 15, 2026

- [Article Retrieval API reference](https://dev.elsevier.com/documentation/ArticleRetrievalAPI.wadl): native XML, identity routes and entitlement-dependent formats/views.
- [Official JSON example](https://dev.elsevier.com/payloads/retrieval/articleRetrievalResp.json): wrapper local names, `originalText`, `coredata.pii` and `prism:doi`. This is documentation, not a live API result or a wrapper namespace proof.
- [Elsevier Journals Data XML guide](https://supportcontent.elsevier.com/Support%20Hub/DaaS/Journals_Data_XML.pdf), PDF pages 2–3 and 15–20: native namespaces and journal hierarchy.
- [Elsevier tag manual](https://supportcontent.elsevier.com/Support%20Hub/DaaS/36178_ConSyn_XML_Tag_by_Tag_Documentation.pdf), printed sections for author-group, collaboration, correspondence, cross-ref, e-address and text: contributor order, identity links, affiliations and electronic-address fields. `ce:e-address` inside correspondence `ce:text` is not the documented standard shape.

The linked [XML example](https://dev.elsevier.com/payloads/retrieval/articleRetrievalResp.xml) and [XOCS schema](https://schema.elsevier.com/dtds/document/fulltext/xcr/xocs-article.xsd) could not be inspected: web rendering rejected the media type; ordinary public-document HTTP reads returned an unavailable page. No real paper or researcher contact data was retained in Git. Fixtures are newly authored synthetic content shaped by the readable documentation, not copied samples.

## Checks, rollback and next slice

See [validation evidence](../reports/em015b-validation.md). Run focused tests with `uv run --project services/backend pytest services/backend/tests/test_sciencedirect_article.py`, then the normal aggregate and a new empty Python environment. Skipped local services are pending actual CI, not passed tests.

Rollback removes this standalone module, fixture and documentation; no durable state or schema is changed. The next executable slice is reviewed XML-worker integration with real network-none resource/refusal receipts and current tenant/policy binding. Protected acquisition/authentication and an authorized source pilot remain separate; verify the actual wrapper against an approved response before relying on that compatibility path. Full EM-015/016 and production extraction remain incomplete.

## Subsequent synthetic integration candidate

EM-015c adds a separate bounded isolated-parser→tenant persistence→review/export path for one authored synthetic XML URL. The original parser/profile limitations above remain in force. See [runbook48](48-synthetic-xml-pipeline.md) and [candidate evidence](../reports/em015c-validation.md) for the current integration boundary, exact checks and pending actual CI. This does not certify a real Article Retrieval wrapper or activate ScienceDirect.

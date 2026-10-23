# Proposed contracts

These JSON Schemas are implementation-starting contracts, not deployed API handlers. They use JSON Schema draft 2020-12 and schema_version `1.0`. Validate examples with `python scripts/validate_docs.py` after installing the documentation requirements.

- `job-request.schema.json`: client request body; organization authorization comes from the authenticated server context/path, never a trusted body field.
- `contact-record.schema.json`: an author/email association read model; no-contact articles use the separate article-outcome API described in document 09.
- `source-policy.schema.json`: policy record with explicit fixture/live execution distinction; approval is a server-authorized action, not a client-writable permission grant.
- `event.schema.json`: minimal internal event envelope without contact payloads.

JSON Schema validates shape, not source permission, tenant membership, reachable URL safety, identity truth, query equivalence or semantic state transitions. Implement those in domain services and test them. `default` annotations do not mutate requests; server configuration applies effective defaults and the most restrictive caps.

All examples are synthetic. Reserved example domains do not authorize a live request; fixture transport is offline/test-only. The contact example's digest refers to the committed synthetic article-a HTML, not a collected real article. A sample timestamp is fixture metadata, not a claim that a live job ran.

The event schema intentionally has a bounded payload field set. Add event-specific semantics/tests when endpoints exist. Generate and test OpenAPI from real backend handlers; do not pretend these four schemas define every completed endpoint.

`negative/source-policy-credential.json` is deliberately invalid: the fixture source requires an explicit null credential reference. It is tested as rejection evidence, never a valid policy example. Generic future source-reference vocabulary does not enable real credential use.

EM-011 adds result-contacts/result-outcomes and export-request/export-state contracts with synthetic examples. JSON Schema validates shape; immutable snapshot membership, current policy/role/retention/revision/download authority and accepted-evidence semantics remain server/runtime checks. Export requests contain options/identifiers, never arbitrary document/contact/artifact content.

EM-012 adds export-preview and allowlisted optional_contact_fields (affiliations/article_title) to export-request. Existing requests default to both columns; mandatory evidence/source/use-state fields cannot be omitted. Preview returns only current eligible counts and fixed exclusion reasons, never suppressed counts or an artifact/access grant. Runtime export fences revalidate at every existing stage.

EM-015d adds internal Python request/dispatch-binding and `xml-input-v1` byte-channel contracts documented in [runbook49](../docs/49-disabled-provider-binding.md). They are not public request schemas or source-policy grants. In particular, opaque credential references and generalized XML identifiers cannot be submitted through the existing fixture-only policy or retained-observation schemas; those remain unchanged. The parser frame excludes tenant/lease/credential authority, and the host compares its own expected request, digest and profile after parsing.

EM-015e adds the internal dispatch-only `CredentialResolver`/`CredentialLease` interface and closed controlled-provider owned-pipe diagnostic in [runbook50](../docs/50-controlled-provider-gateway.md). Neither is a public credential API, authority grant or production transport registration. Credential values are confined to the gateway and excluded from all request/response/parser/pipe contracts. The existing public JSON schemas, fixed synthetic policy and persistence guards remain unchanged.

EM-015f extends `xml-retained-observation.schema.json` with optional provider provenance: controlled acquisition mode, source ID, exact canonical transport URL/fingerprint and requested FULL view. Server catalog/SQL guards independently bind identifier, profile and digest; schema shape cannot grant permission. An omitted provider block retains the exact original fixed-XML semantics. Search rows never supply fetch URLs, and synthetic logical routes remain distinct from API transport URLs. [Runbook51](../docs/51-controlled-provider-journey.md) documents the additive forward-only migration and retained evidence behavior.

The bounded retained-article filter increment adds optional `item_id` and
`article_outcome_presence` to `export-request.schema.json`. A non-null item requires
`job_id`; the exact selector applies to both tables, while presence filters only
article outcomes. Legacy defaults serialize without the new default keys; existing
outcome records remain unchanged. Internal filtered snapshots contain exact
captured item/source fingerprints for private current-authority validation.
See [document 69](../docs/69-retained-article-filters.md); these fields authorize no
new source, worker capability or acquisition route.

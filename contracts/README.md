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

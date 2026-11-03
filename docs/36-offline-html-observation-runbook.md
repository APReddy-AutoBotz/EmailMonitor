# EM-007 — Offline HTML/browser observation runbook

## Boundary

This candidate implements the synthetic HTML/browser observation foundation from document 16, after verified EM-006. It does not activate live sources or production workers. Default UI controls stay disabled and explain that extraction is unavailable there. All assemblies require explicit `test`/fixture configuration; production refuses it. No new dependencies, browser security profile, capabilities, network configuration or initializer settings are added.

The stdlib inert HTML parser consumes at most 32768 UTF-8 bytes, 2048 tags, 64 levels, 35 attributes per element and bounded field/author/contact/link counts. It requires the registered article/main/author structure, ignores scripts/styles/templates/hidden/support/footer/reference/form blocks, preserves Unicode names and raw observed addresses, and does not evaluate HTML or source instructions. Mailto query/body/subject are not contacts. Only reviewed public contact attributes in author/correspondence blocks are admissible. Follow-up links are safe, scoped, depth-bounded unscheduled candidates; the selected job's depth budget still applies.

Metadata precedence selects an observed structured field before article DOM, keeps all conflicting observations, and represents missing title/journal/date/DOI with null. Authors remain ordered instances, with first-author position separate from explicit correspondence assertions. Equal-contribution markers, name substrings and ambiguous same-name instances do not establish correspondence or merge people. Group/ORCID values require explicit source attributes; no identity verification is implied.

Candidate addresses have locators, short permitted excerpts and structural author-position hints only. Association is `unmatched` or `needs_review`, technical status `not_checked`, delivery `unverified`, outreach `not_assessed`. Conservative normalization, accepted associations and review belong to EM-009; no probabilities, mailbox tests or sending exist.

The JSON Schema validates structural constraints and required browser-plan presence. The trusted worker additionally validates cross-field semantics in ArticleObservation: author-position references must exist and preferred metadata must match the observed facts and precedence. JSON Schema alone does not establish those relational properties.

## Test-only API

Use the existing synthetic identity/database setup and complete or partially enumerate an authorized job's discovery frontier. Draft job semantics remain unchanged; these short idempotent observation transactions do not masquerade as completed extraction jobs, persistence probes or billable effects.

- POST `/api/v1/organizations/{organization_id}/jobs/{job_id}/extract-fixture-article` with `article_url` from the four registered authored paths and `expected_revision` equal to the discovery checkpoint revision
- GET `/api/v1/organizations/{organization_id}/jobs/{job_id}/article-observations`

POST requires current server-authorized acquisition capability/CSRF, job ownership/status/generation, deletion generation, discovered URL, current approved source/version/HTML and contact-extraction operation, matching purpose and permitted contact retention. Acquisition uses the existing fixture gateway; commit reacquires the policy fence after byte processing. No endpoint accepts HTML, selectors, observations or browser scripts. An exact observation replay preserves revision/time and emits no extra audit/usage effect; divergent static observations refuse. An unresolved tooltip may be upgraded only by trusted isolated browser composition with the registered acquisition digest.

Rows use composite tenant/job/source relations and forced RLS. Runtime has no DELETE or catalog UPDATE; authenticator has no table access. Reads require active tenant context, unexpired retention and current approved/enabled extraction source/version. Excerpts are removed when separate excerpt retention is not permitted. Server-derived expiry uses the smaller applicable source contact/excerpt TTL. Expired records cannot be revived by a replay. Physical retention purge remains EM-014; this is not a production deletion certificate.

## Actual browser/parser acceptance

The four article fixture byte digests are pinned separately from manually authored expected outcomes. Static parsing must leave the tooltip address unresolved, even though its script contains the text. The existing network-none, nonroot Chromium guest loads the real authored tooltip and its actual script plus fixed hostile-boundary controls. Only the reviewed `#contact-reveal` hover is used; it neither clicks mailto nor submits forms. The resulting visible `#contact-tooltip` DOM is parsed by the same inert parser.

Three hashes have distinct meanings: source_digest is the authored original fixture version; acquisition_digest is the exact gateway response before interaction (including fixed diagnostic controls for browser acceptance); content_digest is the actual parsed bytes/rendered DOM snapshot. A hash establishes byte equality, not truth or ongoing availability. The browser acquisition manifest is pinned and checked against the composed fixture response.

The controlled transport CI must persist and replay the actual browser observation under current SQL tenant/source authority and retain all existing selected-peer, cross-tenant, revocation, credential/subresource, sandbox and strict cleanup gates. Only bounded digest/count summaries are printed; observation content stays in the owned test protocol and tenant database. Standalone browser and parser jobs remain mandatory. Parser CI parses all four original articles inside the unchanged network-none resource boundary and retains actual OOMKilled/exit137 proof. No local browser, container, topology or initializer execution is part of this candidate's validation.

## Migration and validation

Apply Alembic `0005_article_observations` with the disposable migration role. It adds only the tenant observation table, narrow transition guard/RLS and truthful synthetic catalog support metadata; authentication/runtime role separation is unchanged. Destructive downgrade is refused; use a forward repair or restore a disposable test database. Upgrade/replay from empty and existing migrations is required in actual CI.

Run `scripts/check.sh`, the focused HTML/contract/tenant tests, and required actual application/controlled/browser/parser/docs CI. Skipped local service tests do not establish SQL or browser acceptance. See [validation](../reports/em007-validation.md). EM-008 remains gated until independent exact-tree review and actual required CI verify the declared EM-007 slice. No real-source certification or benchmark result follows from these fixtures.

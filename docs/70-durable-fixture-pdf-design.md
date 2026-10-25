# Durable authored-PDF journey: retained contract and execution design

Status: **isolated implementation candidate; acceptance incomplete**. Published
PR50 remains unchanged. The candidate adds explicitly opted-in authored fixture
execution only. External PDF fetching remains disabled.

## Scope

The selected outcome implements the existing FR-005/006/013/015–017/020–025/029
requirements using only the nine digest-pinned authored PDFs in
`extraction/pdf_fixture.py`. A direct fixture identifier selects one local file;
it is never a request to resolve DNS, download a PDF, traverse links, open an
arbitrary path, upload content or use publisher credentials. No new PDF parser
profile, OCR, dependency or resource limit is proposed.

The existing stateless parser and pure association mapping are prerequisites,
not proof of durable PDF support. Default PDF planning refusal remains unless both job and source opt in.

## Retained schema

`extraction/pdf_retained.py` adds a `RetainedPdf` subtype of the existing
`PdfObservation`. It preserves every raw observation invariant, author order,
candidate/evidence relation, metadata fact, complete-scan flag, page count,
unsupported reason and coarse page-region precision. It adds:

- `retention_profile=authored-pdf-retention-v1` and
  `input_mode=authored_local_fixture`;
- an exact organization/job/item/generation/deletion-generation/policy-version/
  discovery-revision binding;
- an explicit excerpt-retention marker, consistent with retained facts.

The identifier and content digest must match the existing authored manifest.
Early disabled/byte-cap observations without a content digest cannot become a
retained source record. Such failures belong to the job outcome, not a fabricated
observation. The serialized envelope is bounded to 131072 bytes. Constructing or
validating this object does not establish authorization, isolation or persistence.

This bounded first version retains literal parser evidence only when excerpt
permission exists. It refuses locator-only retention rather than stripping text
and pretending the raw parser validators still prove it. Unsupported observations
with no facts may have no excerpts. A future locator-only representation needs its
own explicit model; it is not silently introduced here. No publication date is
created from acquisition or completion time.

## Execution contract

1. The normal authenticated planner accepts only an exact registered authored PDF
   identifier with `allow_pdf` enabled and a current source policy explicitly
   covering that local route. Unknown, live and disabled routes retain refusal.
   Discovery marks one selected article, never publisher-wide completeness.
2. Normal durable start/outbox/claim supplies the current fenced lease. No queue
   argument selects a path, module, parser command, credentials or authority.
3. Before reading bytes, check current membership/session or service delegation,
   job/item/generation, source/version/expiry, purpose, retention and admission.
   Read only the existing bounded manifest loader. No HTML-fetch relabeling.
4. Feed the same immutable bytes plus exact fixture identifier/digest into a new
   fixed PDF stdin protocol in the existing network-none parser profile. The
   new durable PDF pipe entrypoint preserves the exact
   nonroot, network, capabilities, read-only filesystem, memory/CPU/PID and pipe
   limits; verify the original inspected command/image and never fall back to
   host parsing. XML/private-sample channels remain unchanged.
5. Revalidate bounded output and identity/digest, then construct the retained
   record using the trusted current binding. At commit repeat all current SQL
   authority, policy, lease, generation, deletion and retention checks.
6. Retain in `article_observations`, derive through the existing deterministic PDF
   association mapper, and finalize through the existing durable effect/outcome
   mechanism. Extend readers and quality projection explicitly for the new
   retained profile; no reinterpretation as HTML or XML.
7. Existing evidence/review and results/export release fences remain mandatory.
   Full scan with no candidates may be no-contact; page-capped empty output stays
   unresolved; observed positive candidates remain distinguishable from accepted
   associations. Unsupported input cannot acquire fabricated facts.

## Explicit synthetic capability

The synthetic capability does not confer real-resource or external access.
`parse_fixture_pdf` is a distinct opt-in operation for the nine authored URLs and
exact digests. Existing policies are not rewritten. `fetch_pdf` remains refused,
`pdf_supported` remains false for external acquisition, and existing default policies contain no PDF capability. A false job
`allow_pdf` also refuses the route. Tests create disposable policies through the existing normal approval route.
No database-role grants, credentials, account permissions or network settings are
added by the migration. Installed availability remains unclaimed until its actual
execution gates pass.

## Migration, replay and rollback contract

Forward-only migration `0018_authored_pdf`, after `0017_execution_receipt_lock`,
extends retained-profile guards, provenance mapping and current read/release
predicates for the exact authored profile. It registers only synthetic catalog
capability and routes. It preserves existing policies, tenant keys, forced RLS,
roles and ACLs; no historical observations or reviews are rewritten. Service-schema
readiness and restore-version expectations advance together.

The existing `(organization, job, article_url)` source identity and current
source revision remain authoritative. Exact repeat bytes, binding and canonical
payload return the original row without resetting expiry, review or usage;
changed payload/revision refuses. Stale generation, cancelled/deleted work or
revoked authority cannot commit or revive a prior record. Finalization must
remain one durable effect under duplicate broker delivery and worker restart.

Upgrade proof must compare populated-history fingerprints, ACLs/role attributes,
old-profile behavior and exact schema readiness, then run restore compatibility.
Destructive downgrade is refused. Recovery is a compatible forward repair or
restore of the owned disposable database; old code must not serve a newer schema
by weakening version checks. Local migration execution is tracked separately from deployment; no deployment is authorized.

## Acceptance inventory

- Contract: all nine real authored parser outputs, byte/digest/identifier binding,
  malformed/extra fields, forged model copies, every binding field, permission
  loss, unsupported facts, complete versus partial and unchanged evidence.
- Actual PostgreSQL: valid source and retained-profile admission; unchanged old
  policies; two-tenant/RLS and narrow worker scope; current source/session/member
  revocation, cancellation, deletion and retention; identical replay and changed
  payload refusal; duplicate finalization and preserved review/expiry.
- Actual isolated execution: all fixture profiles with unchanged limits, malformed
  pipe/output, resource failure, verified owned cleanup and no network fallback.
- Durable/installed/UI: normal create/plan/start/claim, broker restart/duplicate,
  retained evidence/review, no-contact/partial/unsupported, CSV/XLSX filter and
  preview parity, stale-response and organization-switch invalidation.
- Migration/restore plus normal/fresh and every unchanged hosted gate. Report
  missing infrastructure separately; schema unit tests never stand in for these.

## Current evidence and remaining gates

Actual PostgreSQL targeted checks cover all nine authored profiles through durable
persistence, replay, association/review, results and CSV/XLSX export, plus explicit
default/unknown refusal and nine current-authority invalidations. SQL-only tests
construct authored observations directly and do not establish parser isolation.
Pure protocol tests preserve JSON geometry and reject changed/unknown input.

The parser-only Docker client configuration
verifies the existing default local endpoint, creates an owned temporary
configuration without automatic proxy injection, pins that same endpoint for all
parser controls, and removes the configuration afterward. It copies no host
credentials and changes no host/daemon proxy settings. Environment and isolation
guards, immutable image selection, pull-never and resource limits remain unchanged.
Endpoint overrides refuse rather than silently selecting another daemon.

The standard image build is currently blocked by certificate verification inside
the locked dependency build. No trust-store, TLS or proxy-policy change is applied.
An offline development image assembled from locked runtime dependencies provides
separate local parser evidence; its source/dependency artifact modes must permit
the existing nonroot user to read them. This is not standard packaging acceptance.
The local actual PDF pipeline completed 39 tests with zero skips using that
development image, including isolated parsing and post-parse authority fences.
This evidence is separate from pure protocol and SQL-only proof. The controlled worker now receives an explicit PDF byte-parser capability from
its supervisor; only the nine pinned fixtures can use the new closed RPC command.
The supervisor selects the immutable image, never a message field. Gateway
acquisition is absent on this path, and normal admission/commit fences remain.
Nine actual isolated RPC cases and two actual tenant SQL cases validate the byte
transport, replay/review/export and cancellation-before-commit boundary. Installed
artifact/browser execution, service broker/restart, complete migration/restore
and hosted gates remain pending. The guarded migration tests require genuine CI;
local checks never fabricate that context. No full PDF acceptance or publication
is claimed. Earlier failures remain historical, not retroactively successful.

The held export-reconciliation proposal, live publisher certification, broader
date filtering and cross-job paper identity remain separate.

The controller stream test retains its 20-second limit and existing assertions.
An owned diagnostic file now records fixed phase names/monotonic elapsed times and
a delayed stack trace, attached only if that deadline expires. The historical
timeout has no captured stack and cannot be attributed retrospectively to test
contention or a product defect. This instrumentation is not a claimed repair.

## Installed acceptance candidate

The existing installed service harness now includes a distinct authored-PDF keyboard
journey: explicit PDF policy review, a default-off job opt-in, the fixed article-a
fixture, retained page/region evidence, review, CSV/XLSX export and tenant switching.
The existing XML and browser policy option positions remain stable.
A separate PDF case kills the real installed service worker after its observation
commits, then requires broker redelivery/lease recovery to finish one durable effect
without a second parser invocation or any provider request. Both cases use the
standard verified service archive and curated parser image; original deadlines and
CI guards remain unchanged. These are implemented tests, not passed installed
acceptance until their genuine hosted execution succeeds.

The first hosted installed run passed the PDF post-observation SIGKILL/recovery
case but refused PDF launch from the browser. The composed service binding's
route inventory still contained only HTML/XML. The correction recognizes the nine
registered authored PDF URLs only in the composed isolated-parser profile. The
default HTML profile still refuses every PDF, and arbitrary/modified URLs remain
refused. Normal job/source authorization and the existing SQL delegation calls
remain unchanged; there is no new role, privilege, credential or external route.
Closed-route unit tests and a real-SQL default-profile rollback regression cover
this correction; a new exact-head installed run remains required.

The PDF browser case opens Contacts for the fixed article-a fixture's already
accepted association, then inspects its retained evidence and saves explicit review.
It does not search the needs-review-only XML view or change association semantics.
A local regression maps the actual authored PDF and checks the selected view against
that association state. Page evidence and saved-review assertions remain mandatory.

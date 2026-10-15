# 48 — Synthetic isolated XML pipeline (EM-015c)

Status: candidate, partial EM-015. This extends the inert EM-015b parser into one synthetic single-article job. Actual-container/database acceptance remains an exact-head CI gate; local pure tests and service skips are not that evidence. There is no live ScienceDirect registration, permission, credential, acquisition or deployment.

## Scope and prerequisites

The previous cleanup baseline closed all seven gates in Draft PR24; the authoritative receipts are linked in the [EM-015c report](../reports/em015c-validation.md). Existing HTML/browser/PDF behavior, the original two search pages and their four unique articles remain unchanged. XML is a separate URL job at `https://synthetic.publisher.example/article-xml.xml`, with the existing authored `fixtures/xml/sciencedirect-article.xml` bytes and fixed DOI `10.9999/synthetic.1`.

Migration0012 adds exactly that synthetic route to acquisition, extraction, excerpt and export support. A new tenant policy must explicitly approve `fetch_xml`; existing approved policies are not modified. XML is never registered as `fetch_html`, browser or search. Its fixture response media type is `application/xml`. The canonical API document URL is retained separately as identifier-derived metadata; it is not a fetched address, source permission or real-wrapper certification. Results and exports continue to cite the actual synthetic acquisition URL.

## Byte channel and trust boundary

The credentialed host authorizes the tenant, job, source policy, purpose, frontier, generation, deletion epoch, discovery revision, admission and exact current item lease before opening authored bytes. `XmlExtraction.isolated_fixture` then obtains those bounded bytes through the explicit XML fixture gateway. It invokes one fixed command, `python -m emailmonitor.parsing.xml_worker`, through stdin/stdout. No host XML parser fallback exists on this execution path.

The channel resolves the already-built local image to its immutable image ID and uses `--pull=never`. It creates a disposable container with the existing parser settings: network none; UID/GID65532; read-only root; all capabilities dropped; no-new-privileges/default seccomp;128MiB memory and swap ceiling;0.5 CPU;32 PIDs;64 file descriptors; zero core files; existing16MiB noexec/nosuid temporary filesystem. There are no bind/volume/socket mounts, database/broker secrets, tenant IDs, leases or arbitrary commands in the parser. Inspect-time image/config/mount/environment checks supplement the child’s kernel checks. No host security setting or inherited sandbox limit changes.

Both control and attached-process streams are bounded while running. XML input is at most2MiB; the observation envelope is at most128KiB; stderr is bounded4KiB; the attached process has a30-second deadline. Timeout, oversized output, malformed or duplicate-key JSON, nonfinite numbers, trailing data, unexpected profile, identifier/digest mismatch, stderr/nonzero exit or OOM all fail closed. The owned container is force-removed on every post-creation exit. Raw XML and parser exceptions are not logged.

The child returns observations only. The host checks the digest against the exact input bytes and the registered synthetic digest, checks the requested identifier/profile, and attaches the server-owned binding. Parser self-report never supplies tenant authority. Before committing, a fresh transaction rechecks current membership/session, policy, purpose, job/item/lease, generation/deletion, discovery revision, quota, suppression and retention.

## Retention, review and truthful outcomes

`RetainedXml` is a separate typed model from `XmlObservation`. Raw parser candidates require literal excerpts. The host validates that raw result before applying excerpt-retention policy; locator-only records are then validated as retained facts, never as raw observations. Acquisition/canonical URLs, digest, identifier, profile, status/reasons and server-owned binding remain explicit. Envelopes and association bundles retain the existing128KiB ceilings.

The mapper consumes original XML `association_evidence`, preserving author-context and literal address provenance. All structural mappings start `needs_review`; no XML rule auto-accepts. Existing evidence-backed human review is required before default CSV/XLSX contact export. Locator-only records cannot be accepted. Syntax/technical/domain/delivery/outreach states remain separate; nothing checks mailbox existence or sends mail.

`unsupported` and `partial` observations produce explicit `unsupported` item outcomes with `xml_unsupported` or `xml_partial` reasons. The retained observation still distinguishes the two. These are extraction gaps and yield `completed_partial`, even when there are no candidates. Ordinary observed XML needing review remains a successfully processed article with unresolved identity quality.

A persisted observation can recover after a lost completion without reparsing or duplicating observations, associations, effects or resolution units. Existing RLS, current-source reads, cancellation, suppression, deletion and retention fences remain in force. XML is immutable after insertion; the inherited HTML→browser upgrade rule remains exclusive to that prior route.

## Checks and operation

Run focused checks:

```sh
UV_CACHE_DIR=/tmp/emailmonitor-uv-cache uv run --project services/backend pytest services/backend/tests/test_xml_pipeline.py services/backend/tests/test_xml_pipeline_tenant.py
UV_CACHE_DIR=/tmp/emailmonitor-uv-cache scripts/check.sh
```

The deny-all root build context admits exactly the authored XML fixture using an allow/re-exclude/exact-file rule block. The ordered fixture-context regression also checks every parser Dockerfile fixture `COPY` source exists and is admitted, while unknown XML siblings and descendants remain excluded. This check prevents the original PR25 missing-fixture build failure from passing local static checks; actual Docker builds are still required.

The application CI job builds the existing pinned parser Dockerfile and sets `EM_REQUIRE_XML_ISOLATION=true`. The actual integration suite calls the fixed container channel and feeds that same returned result into PostgreSQL, existing review and both export formats. It also covers tenant B, missing XML permission, changed authority during parsing, item-binding mismatches, locator-only review refusal and duplicate recovery. It cannot substitute a host parse; missing required Docker/image execution fails. The parser-isolation job adds XML observations and actual hostile DTD/XXE/depth/text/byte refusals to its inherited network-denial/resource/OOM proof. All seven inherited gates remain required, including actual UI and controlled transport.

PR25's recurring unrelated UI worker stall has bounded opt-in fixture diagnostics, enabled only by the actual operator UI test. Closed cumulative worker/signal/claim/process counters are parsed from the existing bounded owned log tail. Unknown or invalid evidence has no counters. Truncated/saturated evidence is labelled and may retain the last complete cumulative snapshot; these are last-observed lower bounds, so a zero stage does not prove no later activity. No task content or exception text is emitted, and no wait, readiness synchronization, prefetch, acknowledgement or sandbox setting changes. A postrun signal does not prove broker acknowledgement; the admission wrapper may return before recording a delivery. These observations support diagnosis, not a stall-fix claim.

Migration0012 is additive and forward-only. It extends the latest0011 lifecycle-aware definitions, preserves existing grants/FORCE RLS/restrictive policies and introduces no new table or role. Rollback requires a reviewed forward repair preserving retained state, not a destructive downgrade. No source policy or sandbox setting should be relaxed to make a failing test pass.

## Remaining limits and next work

This is one newly authored XML fixture, not live ScienceDirect retrieval or a measured source benchmark. The Article Retrieval wrapper namespace remains an explicitly unverified compatibility assumption. The existing operator screens are reused; the inherited UI gate does not become a keyboard XML-specific demonstration. Metadata packaging still does not package a deployed extraction service. Full EM-015/016 acceptance needs approved real-source permissions, verified response profiles and authorized held-out samples; production packaging/deployment remain separate approvals. See [report](../reports/em015c-validation.md) for actual test evidence and unexecuted gates.

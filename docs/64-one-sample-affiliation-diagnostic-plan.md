# Proposed one-sample private affiliation diagnostic

Status: scope independently reviewed and approved for implementation. The new
runner/workflow remains unpublished pending synthetic tests, independent exact-tree
review and normal/new-empty gates. Publication of the separately scoped draft is
authorized only after those gates and the allocation/overlap checks below. This
document alone is not a reusable acquisition authorization.

## Purpose and immutable source

Inspect only the fixed structural counters supported by the accepted PR43 guest
for the SAME article representation previously evaluated by PR42. Determine
whether the current conservative selection gate explains missing affiliation
selection for those bytes. Do not establish correct researcher identity, intended
affiliation association, completeness, mailbox validity, accuracy or production
readiness. If counts do not distinguish the cause, report the uncertainty and
stop; do not relax the parser or fetch more data.

Reuse the recorded article-specific rights evidence and attribution in
[runbook62](62-elsevier-one-sample-validation.md), including CC BY 3.0 and the
conflicting legacy boilerplate. This is a new narrowly scoped diagnostic decision,
not reuse of the previous one-shot execution authorization or a legal certification.
Preserve the credited authors/title/year/journal/DOI and license link there.

Exact anonymous source:
https://raw.githubusercontent.com/elsevierlabs/OA-STM-Corpus/0ed398ec9288fd8936a24f9486647ecfcbf2d972/SourceXML/S0960148113005727.norm-xml

- Corpus revision: 0ed398ec9288fd8936a24f9486647ecfcbf2d972
- Size: 143976 bytes
- SHA-256: 7c0add248911ef4a442b5a0b9569c605bf47aee2ccfc1315bfba7bf25d1e2c25
- Requested DOI: 10.1016/j.renene.2013.10.041; native xocs_document profile
- New decision reference: em015-elsevier-ccby3-affiliation-diagnostic-20261020
- New manifest purpose and rights scope: one-file-private-affiliation-diagnostic
- Decision class: AffiliationDiagnosticRightsDecision, bound to this new manifest

No source retrieval is needed for the design review. The existing recorded
article-level rights evidence is the input to that review; unresolved rights or
scope means stop before publishing an executable acquisition path.

## Exact proposed changes

Add, without editing the original PR42 files:

1. scripts/packaging/run_private_affiliation_diagnostic_once.py: a standalone
   exact-event admission/lifecycle composer. It may import only the unchanged
   fixed acquire, bounded event reader and private-removal helpers from the old
   runner, plus its immutable source constants. Never call old execute/main or
   reuse its rights decision. New event guards/decision/output live in this new
   composer; do not monkeypatch the old module's constants or functions.
2. .github/workflows/elsevier-one-sample-affiliation-diagnostic.yml: a separate
   initial-event workflow, fixed new PR/ref/base and read-only repository access.
3. Authored synthetic runner tests, scoped decision/runbook and validation receipt.
   Update status/traceability/changelog after implementation. No real XML fixture,
   excerpt, manifest payload, private path, sample artifact or cache is added.

Preserve all PR43 guest, core counter, private admission and transport source
bytes. Preserve normal parser, association, API/tenant/source-policy/queue/export
behavior, existing seven synthetic workflows and their predicates. The new
one-shot workflow is additional; it cannot replace any synthetic gate.

## Workflow and host guards

Proposed exact PR number: 44. Check allocation before publication; a different
number must fail closed, never be accommodated by rerun or post-trigger widening.
Any change requires a revised reviewed decision before its own initial event.

- Repository and both PR head/base repositories: APReddy-AutoBotz/EmailMonitor
- Event: pull_request; action/types: opened only; run_attempt exactly 1
- PR: integer 44; GITHUB_REF exactly refs/pull/44/merge
- Head branch: feat/elsevier-one-sample-affiliation-diagnostic
- Base branch: feat/synthetic-affiliation-diagnostic
- Base SHA: 93f72166ea246b47f585bf278d681bff8dc2fe79
- Workflow concurrency: elsevier-affiliation-diagnostic-pr44-initial;
  cancel-in-progress false
- Checkout exact event head SHA, persist-credentials false; Python checks HEAD
  equals that event SHA and image preparation requires clean tracked source.
- Before opening the PR, verify the remote head tree equals the independently
  reviewed frozen tree and the expected base remains unchanged.
- Ubuntu 24.04, same pinned checkout/setup-node actions and existing pinned
  uv/pnpm/Node/locked dependency setup; 15-minute job timeout; contents:read only.
- No push/synchronize/reopened/dispatch/schedule/pull_request_target trigger;
  no environment secrets, artifacts, cache, uploads or credentials.
- Workflow AND Python enforce repository/ref/base/event/attempt guards. Python
  rejects Docker/TLS/proxy overrides and credential variables, including
  SSLKEYLOGFILE, just as the existing reviewed acquisition boundary does.
- Wrong event/ref/head/base/platform/argument/override refuses before build or GET.

This permits one new initial-event attempt, not a durable global exactly-once
claim. Concurrency serializes duplicate deliveries but is not a replay ledger.
No new persistent access or writable GitHub token is introduced to solve that
separate problem. Any failure after publication is reported without retry,
reopen, alternate URL or extra real acquisition. Synthetic-only repairs remain
possible without triggering this opened-only workflow again.

## Data flow and isolation

1. Validate event/context; build and probe the curated PR43-capable image from
   exact clean reviewed source BEFORE source acquisition. Install/verify only the
   invocation-owned alias and image. Build failure prevents GET.
2. Issue one fixed anonymous GET using the unchanged reviewed acquire helper:
   all DNS answers public, one selected literal-IP connect, exact peer binding,
   system-CA hostname/SNI validation, identity encoding, exact length/digest;
   no retry, redirect, alternate address/URL, proxy, cookie, credentials or links.
   Preserve 30-second network deadline and outer 40-second DNS/header bound.
3. Create one mode-0700 temporary directory outside checkout/build/archive and
   one exclusive mode-0600 sample file. No XML host parsing. Drop redundant bytes
   after write. Construct the new diagnostic manifest/decision in memory only.
4. Evaluate through PR43 evaluate_private_affiliation_diagnostic. Full XML parser
   and identifier/digest/profile validation happen only in the isolated guest.
   Unlike PR42, no author/email observations leave that guest; only fixed counters.
5. The standalone composer temporarily wraps ONLY the new diagnostic channel's
   verifier to call its unchanged exact-profile validation and additionally
   enforce the invocation-owned immutable image ID and owner label on original
   inspect metadata. No metadata rewriting. Restore the original verifier in
   finally; no API or concurrent application invocation uses this composer.
6. Revalidate the exact result type and canonical bounded diagnostic schema before
   retaining counters for output. Refusals carry no diagnostic counters. Retain
   the existing evaluation/process budgets and no tracebacks/process log output.
7. Remove the private directory with the prior bounded two-attempt helper and
   verify absence; independently reconcile owned Docker image/container/alias.
   Keep 30-second private cleanup and 180-second Docker reconciliation bounds;
   attempt Docker cleanup even if file deletion fails. Keep the owned directory
   reference across context-exit failure. Defer ordinary SIGINT/SIGTERM during both
   independently alarm-bounded cleanup phases and contain transition failures;
   pending termination is delivered after both checks and conservatively refuses.
   Ordinary signal cleanup is bounded;
   SIGKILL/VM loss relies on hosted-runner disposal, not secure physical erasure.
8. Only after both cleanup checks emit one bounded canonical JSON line. Never
   serialize the manifest, URL, DOI, digest, XML, path, exception, node value,
   excerpt or contact into evaluation output. Workflow setup may show reviewed
   code/commit metadata, never the source bytes or the sample's private path.

## Public result schema

Exactly four keys, max 4096 ASCII bytes including newline:

- status: diagnosed or refused
- reasons: [] on success; one fixed runner_refused, preparation_refused,
  acquisition_refused, diagnostic_refused or cleanup_refused on refusal
- diagnostic: PR43 private-affiliation-counters-v1 object on diagnosed only;
  otherwise null. All 12 counters remain strict integers 0..20000.
- cleanup_status: verified after BOTH file absence and owned Docker cleanup;
  not_started for pre-resource context refusal; refused if either cleanup fails.

No success/counters may appear with cleanup_status other than verified.
Cleanup refusal overrides earlier results and drops any counters. Exceptions
produce only the appropriate closed refusal record, with nonzero exit status.
No variable-length reason text, metadata, source identity or raw output fields.

For one group with affiliation_count > 0, zero affiliation-reference edges and
labels, a correspondence reference plus groups_implicit_disabled_by_reference and
authors_without_selected_affiliation can support the explanation that the current
reference gate prevented selection of existing affiliation nodes. A zero-affiliation
input cannot support that explanation. affiliations_with_direct_textfn > 0 shows
only presence of direct textfn nodes; it does not establish that their values are
nonempty, uniquely structured, acceptable to _value or attributable to any author.
Counts cannot prove that disabling the gate would yield valid affiliation strings,
or that any implicit affiliation should be accepted. Other vectors must be
interpreted literally without forcing the hypothesis.

## Required pre-publication validation

- Independent review of this scope, new rights disposition and exact event boundary;
  parent reviews the proposal before any executable acquisition publication.
- Implement and test only authored synthetic bytes. No real source calls locally.
- Refuse changed event/action/PR/refs/base/head/repository/platform/attempt and
  credential/proxy/TLS/Docker overrides before build or network.
- Verify build precedes GET; one acquisition and diagnostic call only; no retry;
  exact new manifest/rights purpose; old authorization fails; exact owned image
  and owner label; untrusted output cannot add fields/count types/identifiers.
- Verify temporary permissions/outside-build placement; success only after both
  cleanup checks; delete failure/interruption/deadline/silent failure still runs
  Docker reconciliation and strips counters; signal/refusal paths stay redacted.
- Assert original PR42 files and PR43 diagnostic modules are unchanged; all
  existing normal/new-empty aggregates and synthetic gates remain required.
- Independent source/frozen-tree review, remote tree/base verification and explicit
  parent authorization of the reviewed real-run publication before opening PR44.
- After the sole attempt, record exact head/run/attempt, closed counters/refusal,
  cleanup evidence and uncertainty. Never rerun to obtain a nicer result.

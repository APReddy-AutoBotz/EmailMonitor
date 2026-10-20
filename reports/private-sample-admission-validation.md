# Private offline sample admission validation

Candidate based on accepted Draft PR40 head
`8c7b06ceac5b84eaee36447e2ba70311aef8fcf0`, tree
`00b57e8761ec8ec61832b0a290df40c7b86047aa`.
[Runbook](../docs/61-private-offline-sample-admission.md).

## Initial assessment

Official Elsevier documentation and corpus provenance were checked on 2026-10-20.
The corpus supplies individual normalized XOCS XML without an API key. Corpus
CC-BY statements, absent version detail and legacy article rights metadata were
kept distinct; no scoped real-sample admission decision was fabricated. A source
selection is not permission to bypass access controls or expand live grants.

Current cloud has no reviewed Docker runtime/socket; no real sample was parsed.
The existing worker explicitly requires the synthetic marker, so merely supplying
fixture settings for real input was rejected in design. The authorized candidate
adds a distinct private boundary while retaining existing controls.

At initial assessment, implementation and all review/testing gates were pending.
Subsequent local receipts follow; actual own-head CI remains required. No real personal contact data is placed in the
public repository or CI payload.

## Implemented boundary and focused evidence

The private host harness, distinct fixed worker mode and shared bounded container
runner are implemented. Existing fixture entry and OS/protocol restrictions are
retained. Controlled transport acceptance keeps its original 41 cases and adds a
separate one-case private-mode gate using self-contained authored synthetic bytes.

Focused private/XML/packaging/provider regressions: 333 passed, three existing
service skips in 9.03s. Local actual-private case skipped because owned Docker
acceptance is unavailable. Independent review found no source blocker: 53 private
cases plus one actual skip, and 183 shared XML/packaging regressions passed.

Development corrections are preserved: forged model_copy extras were initially
lost during serialization; exact-field checks and warnings-as-errors revalidation
now refuse them without exposing warning data. The actual test initially depended
on a backend test helper import, replaced with self-contained synthetic input.
An incomplete import replacement was corrected. A partial mypy invocation omitted
packaging source paths and reported module errors; focused checking passed and the
full aggregate remains authoritative. Tools use the established writable uv cache
rather than the unavailable default cache path. No real data was parsed.

The first full aggregate stopped at repository-wide import ordering, and the next
at one actual-test formatting difference. Both were corrected with the existing
full-scope Ruff configuration; the failures occurred before pytest. Corrected
normal aggregate exits 0: 2552 passed/303 explicit service skips in 112.07s,
48 React tests, mypy 266 files and all existing local gates. Fresh aggregate and
all seven actual own-head gates remain pending.

## Local aggregate receipt

Normal and genuinely new-empty Python aggregates both exit 0: 2552 passed/303
explicit service skips (112.07s/124.22s), 48 React, mypy 266 files, and all existing
documentation/contracts, Ruff, inventory, frontend type/lint/build gates. Fresh
Python environment absence was verified before creation; shared uv cache and
frontend dependencies were reused. No local actual-Docker or real-source result
is inferred. Required own-head evidence is 2855 backend/no skips, the original
41 transport plus one private-entry synthetic isolation case and four operator
journeys, with all seven workflows.

## First-head actual CI failure and bounded instrumentation correction

The first published head `40d796c7a8b55b2667e2e14ac6be0c1ea65f60c0`
(tree `f587cc3122425885ab189f6172e0f308e695dbbc`) failed controlled transport
run `39349969305`, job `118391594320`: 39 passed and two failed in 187.12s.
Both IPv4/IPv6 keyword-to-review/export cases failed because their existing
`verify_profile` instrumentation wrapper did not accept the shared runner's new
explicit `private_offline` keyword. This was a deterministic test-signature
mismatch, not accepted parser or full-journey evidence. The later private-entry
and operator gates did not execute in that failed transport consumer.

The bounded correction updates all three legacy fixture-only instrumentation
wrappers (provider journey, operator provider and XML tenant acceptance). Each
accepts the keyword with default `False`, requires it to be exactly `False`, and
forwards it to the original verifier before unchanged owned-image and profile
recording checks. No application source, isolation configuration, acceptance
predicate, timeout, source permission or real input changes.

Three pure regressions execute those actual nested wrapper bodies without needing
Docker/SQL/UI: default and explicit fixture mode pass the unchanged profile;
private and non-boolean modes refuse before recording; a private command is still
rejected under fixture mode. Initial full mypy found only a test AST list variance
annotation; that was corrected. Focused private/XML regressions pass 101 tests;
full-scope mypy passes all 266 files, and focused Ruff lint/format passes. Corrected
own-head actual CI and repeated aggregates remain required before acceptance.

Correction aggregates both exit 0: normal 2555 passed/303 explicit service skips
in 126.34s; genuinely new-empty Python environment 2555/303 in 130.62s. Both
include 48 React tests, mypy 266 files and all existing checks. Shared uv cache
and frontend dependencies were reused. Independent correction review passes,
including 101 focused tests in 4.33s. Corrected actual backend target is 2858
without skips; actual transport/private/operator and all seven own-head gates
remain required. This does not establish real-sample clearance or extraction.

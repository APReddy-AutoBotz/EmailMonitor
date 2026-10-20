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

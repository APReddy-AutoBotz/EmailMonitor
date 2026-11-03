# EM-004e shared per-hop planner validation

Date: 2026-10-12. Stacked on verified Draft PR #8 head e92806ac92c63a0ef09444eb067048fa028c39e7/tree 7d407157906b0879eaa88b3a2e66d89b67d95b50. Its exact-head application CI 38201053457 passed 291 tests/no skips/no pytest warnings; docs 38201053477, actual DNS-gated browser 38201053467 and parser 38201053463 passed. Checkout merge a8d4c697 exact tree/parents was verified. [Prior synthetic evidence](em004d-validation.md) remains unchanged.

The new planner is network-free metadata and stage contracts for the required generalized transport: immutable tenant/source/version/operation/approved origin, complete public DNS snapshot, selected literal peer, fixed HTTPS port, one absolute deadline, current authorization callback stages and bounded fresh redirect history. It has no private fixture exception or production activation. No permission, actual resolver/socket/TLS/firewall or acquisition acceptance follows from a constructed plan.

## Pre-publication local snapshot

Focused 42 pure tests pass, Ruff and strict mypy pass two files. Normal aggregate and a fresh empty locked Python/frontend installation both passed scripts/check.sh: 279 Python tests with 54 explicitly unavailable PostgreSQL/broker skips and no pytest warnings; docs/contracts/fixtures, Ruff lint/format (62 files), strict mypy (60 files), inventory (63 Python/159 JavaScript), frontend peers/types/lint/one React test/build passed. Required actual application count is 333 with no skips. Independent exact-tree review and published-head CI remain pending. Tests only establish planning invariants; full EM-004 remains PARTIAL/EM-006 gated. [Runbook](../docs/33-shared-fetch-hop-planner.md) explicitly assigns actual DNS/socket/CA/SNI/current-policy/enforced mediation responsibilities to the future transport.


## Verified planning-only checkpoint

Independently reviewed code tree 536ec48e4cbee643a67416084683e2e10b02ef04 was published as Draft [PR #9](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/9) head 5ee5712d1c0a7379876dca265e0e3a65fc57b522. Checkout merge 739f5137ceff45780655a798a73c9024d16e22a7 has the exact reviewed tree, with verified parents PR #8 head e92806ac and PR #9 head 5ee5712d.

[Application CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38202490798) passed 333 tests/no skips/no pytest warnings, including 42 pure planner invariants and prior actual PostgreSQL/broker/DNS/TLS checks, plus all aggregate/frontend gates. [Docs CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38202490797) passed. The unchanged [actual browser](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38202490683) recorded 4 synthetic DNS queries/two verified TLS source receipts plus the existing Chromium sandbox/network/subresource/worker/popup/download/credential evidence; [parser CI](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38202490718) again recorded IPv4/IPv6 ENETUNREACH/only lo and OOMKilled=true/137. These workflows do not wire the new planner to an acquisition transport.

The unused shared planner is verified as planning-only preparation in an unmerged Draft PR. The actual generalized protected transport, a separately reviewed and specifically approved controlled synthetic network, and actual IPv4/IPv6 peer/TLS/non-bypassable mediation evidence remain required. Full EM-004 is PARTIAL/EM-006 gated. No new network configuration or transport execution occurred. This documentation-only reconciliation requires exact-tree review and its own published-head CI.

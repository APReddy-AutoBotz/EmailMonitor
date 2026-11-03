# EM-017c isolated XML worker package validation

## Accepted baseline and candidate boundary

Draft [PR31](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/31) remote head `04a3b6e2abb74c89c84bb252daf0455274e07923` and reviewed tree `9e14c951a49cfe59ad3ceb2fe60c965a89afde2f` passed all seven actual first-attempt gates: application 2234/no skips/31 React, controlled 41 and separate provider operator 1, static UI, browser, parser, packaging and docs. Its final PR body preserves exact receipts and unresolved historical popup causality. No repeated passing browser run is used as causal evidence.

The new [EM-017c runbook](../docs/53-isolated-xml-worker-package.md) scopes an additive, explicitly synthetic-only XML worker artifact. It preserves runtime sources, protocol and isolation, and separates absent fixture assets from retained synthetic helper code. No dependencies, migrations, production activation or live-source grants are introduced.

## Candidate evidence

Historical initial snapshot: implementation, pure checks, normal/new-empty aggregates, independent review and actual own-head CI were pending. No packaged-worker runtime acceptance is inferred from prior diagnostic-image execution. Actual two-build equality, stdin protocol and refusal checks, kernel restrictions and owned cleanup must be observed on the exact reviewed tree.

## Reviewed implementation

The separate context contains 33 existing source files in the XML entrypoint's observed import closure, two locked build inputs, five notices and one canonical manifest. Every runtime source is unchanged. Shared helpers include dormant non-XML paths; the artifact does not promise that every callable in those helpers is usable independently. Repository tests and fixture assets are excluded from both build stages; third-party wheels remain intact.

The existing metadata packaging gate is unchanged. An additional step in the same read-only-token workflow builds two XML images without cache. The probe compares its manifest digest to the host's trusted collector, checks exact source hashes/layout and installed distributions, and observes actual uid/gid, capabilities, no-new-privileges, seccomp, loopback-only interfaces and IPv4/IPv6 ENETUNREACH. Defined content hashes cover `/opt/emailmonitor`; OCI timestamps and base-system artifact equality are not claimed.

Seven actual worker cases per image are required: valid observation; malformed frame; malformed XML; digest mismatch; trailing XML bytes with a matching digest; DTD refusal; and valid input without the synthetic activation marker. The existing stdin/stdout channel and exact container profile are reused. Negative acceptance requires an independently inspected stopped exit 1/no OOM/no runtime error plus empty stdout and exactly the fixed parser-refusal stderr. A timeout, output overflow, arbitrary crash or merely absent output cannot pass. An early broken pipe is provisional only and must satisfy the same independent refusal evidence. Positive acceptance compares the complete decoded observation, including unknown corresponding status for the first author, rather than flattening unknown to false.

Control/build/log processes have while-running bounds on both output streams, fixed errors and bounded termination. Names are registered before potentially ambiguous creates, immutable image IDs are checked, and cleanup removes only exact ownership-labeled resources, verifies absence and continues reconciliation after an individual failure.

## Local evidence and limits

Focused package/probe/runner coverage passes 90 tests in 1.94s; the independent reviewer separately passes 90 in 1.84s. Tests cover exact source closure, deterministic canonical artifacts, tampering/path/link/nonregular refusal, excluded unlisted content, source/dependency drift, strict profile/image/environment checks, valid and hostile protocol frames, fake-container full worker orchestration, exact refusal logs, broken pipes, output/timeout bounds, ambiguous creation and cleanup ownership/failure. They do not execute Docker or prove kernel isolation.

The genuinely new Python environment was confirmed absent before creation and installed 63 locked packages. Its aggregate returned exit 0 with 2064 passed/260 explicit service/container skips in 75.50s, 31 React tests, strict mypy 236 files, Ruff/format, inventory, peer checks and frontend build. Download caches and existing frozen frontend dependencies were reused; a wholly uncached system install is not claimed. All 260 skips are inherited actual-service/container cases and remain mandatory in CI.

The first normal aggregate was interrupted after 2064/260 in 74.50s, inventory and frontend install; no aggregate success is inferred. Its output is retained separately. The clean normal rerun returned exit 0, with an explicit exit-code receipt: 2064 passed/260 explicit skips in 75.97s, 31 React tests and every aggregate gate. Docker is absent in this local environment; no host security settings or alternate sandbox route were changed.

## Required actual acceptance

The 90 added pure cases raise own-head application acceptance to 2324/no skips, plus31 React tests. All seven workflows must pass on the exact independently reviewed tree: application with actual PostgreSQL/RabbitMQ/restore, controlled 41 plus normal-provider operator 1, original static operator UI, browser, parser, extended packaging and documentation. Packaging must execute both existing metadata builds/probes and both new XML builds/probes with 14 worker executions and owned cleanup. Final immutable commit/tree/merge/run receipts belong in the Draft PR evidence record. No local skip or diagnostic-image result substitutes for that execution.

No migration, dependency, identity/source grant, source activation, registry publication, deployment or production-readiness claim. The existing application continues selecting its diagnostic parser image; this slice prepares a separate synthetic worker artifact only. Real source samples/rights and full runtime/operations acceptance remain separate unmet gates.

## First published-head failure and narrow startup correction

Draft [PR32](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/32) first head `833dbc1a18e9f4ec023d19356ca7f04ea1841b13` / tree `7d997caa4b8aabb2f9a9e6b678ebbf8015e3a4b5` ran the additive packaging job. [Run38937229850/job117095675203](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38937229850/job/117095675203) passed both original metadata builds/probes and owned cleanup, then the new standalone XML runner failed at import with `ModuleNotFoundError: No module named 'emailmonitor'`. No XML Docker execution occurred. Pytest's configured source path had masked the standalone workflow omission; this is a concrete startup configuration cause, not an isolation failure.

The correction adds the existing repository source path only to the new workflow step. A separate subprocess test reads that actual workflow value, launches the real script with no CI context and an empty executable search path, and requires its fixed CI refusal after successful imports. It cannot pass on a Python import traceback, and no Docker binary is available to that subprocess. Source review independently verifies that require_ci is main's first action; the shared fixed error alone is not used to infer that ordering. Runtime, worker protocol, image context, isolation and all success predicates remain unchanged. Focused coverage rises to 91 cases; next-head actual application requirement is 2325/no skips. All new-head local, review and actual workflow gates remain mandatory; the failed attempt is retained rather than rerun unchanged.

Corrected normal and genuinely new-empty Python aggregates both returned exit 0: 2065 passed/260 explicit inherited skips in 77.14s/78.64s, 31 React tests and all static/docs/inventory/build checks. The new environment was absent before creation and installed 63 locked packages. Focused 91 cases pass in 2.48s; independent corrected review separately passes 91 in 2.62s. Own-head actual application 2325/no skips and all seven workflows remain pending.

# EM-015g — normal controlled operator candidate validation

## Baseline and scope

Accepted Draft PR28 remote head a04f9d29e04e2e8687606df639ca7d64b318da73 corresponds to recovered local HEAD a7ba0292409c6746509e6f6ba04fb8f44d5b464a and exact tree3728a95976c4bf5736bf9f95fd186b84612a7e09. Its final PR body records all seven passing gates,2160 application cases/no skips,31React and41controlled. Its inherited warning and earlier intermittent UI exception remain open.

The four unfinished inherited files were inspected before editing. This candidate adds a trusted Python-only dispatcher factory in the ordinary registered task, preserving default provider refusal, and a separate controlled normal-worker/operator acceptance. [Runbook52](../docs/52-controlled-provider-operator.md) describes preconditions and limits. No migration, dependency, policy default, live access, credential, network/security setting, merge or deployment changes.

## Review corrections and actual local checks

Independent design/source review caught and corrected an inherited default-path URL lookup that broke minimal claimed-work stubs; the provider test's async-generator misuse; strict-text selectors incompatible with nested normalized-address text; ambiguous duplicate download evidence; missing provider-branch service-worker verification; and unsafe pipe ownership on worker teardown failure. The per-I/O revocable capability permits bounded pipe cleanup without locking across SQL. Worker construction is covered by lifecycle cleanup. Existing diagnostic test kwargs now use an exact TypedDict after the typed factory parameter made their earlier inferred dictionary ambiguous to mypy; behavior and assertions are unchanged.

- Focused dispatcher plus existing actual solo-callback, diagnostics and phase queues:176 passed in42.02s.
- New owned pipe lifecycle/control contracts:12 passed in0.50s.
- Whole-source mypy:230 files passed after the test typing correction.
- Earlier authoring checks found formatting/type issues; fixed before final aggregate gates.

Final local aggregate checks and independent source review passed; actual exact-head CI remains pending. No actual Docker/PostgreSQL/RabbitMQ executable or fixture service is available locally. Actual acceptance must run in the existing reviewed disposable CI workflows; local service/container skips are explicit missing execution evidence.

## Own-head requirements

All seven workflows must pass for the same published commit. Application requires2194 cases/no skips (2160 baseline plus34 new pure cases),31React and all static/docs/inventory/build checks. Controlled transport retains its existing41 actual cases and separately requires one normal operator-provider case with `NORMAL_OPERATOR_RABBITMQ_PROVIDER_ISOLATED_REVIEW_EXPORT`, two parser profiles, three finished source tickets, two reviewed contacts and both distinct private artifacts. The original operator UI gate must independently pass unchanged. The final PR record must reconcile the remote commit/tree and exact-head workflow identities; an earlier baseline or rerun on another head cannot satisfy this requirement.

## Final local candidate gates

Resumed normal aggregate `UV_CACHE_DIR=/tmp/emailmonitor-uv-cache scripts/check.sh` exited0:1934 passed/260 explicit service-container skips in64.44s,31React and all aggregate gates. Log `/tmp/em-operator-resumed-normal.log`. The earlier interrupted run reached the same Python count but did not complete frontend checks and is not counted as a full pass.

A genuinely absent `/tmp/emailmonitor-operator-empty-hijRku/venv` was verified before locked synchronization. `UV_PROJECT_ENVIRONMENT` selected it for the same complete aggregate:63 packages installed,1934 passed/260 skips in65.14s,31React and all gates, exit0. Log `/tmp/em-operator-empty.log`. Download cache and frozen frontend installation were reused; no fresh frontend dependency claim. Both use Python3.12.14, lint/format232 files and mypy230 files, docs/contracts/examples/inventory, TypeScript/ESLint, peer checks and built UI. Neither local pytest run emitted a warning summary; historical EM-WARN-01 remains open.

Independent final16-file review cleared the candidate, separately passing42 focused cases in1.35s and scoped lint/format/diff checks. Reviewed changed-file content/mode manifest SHA25635b3aaa3f4a2495b66847144b881eb774285801402788f3eaed8e68b5e10ca49 and tracked diff SHA25608f5ae8f50c4b7e52509e68f4ff18386398402894fef2aa59cf661af28c97882 predate only this report/status receipt update. Final commit/tree and remote-parent reconciliation belong in the PR record. No local skip, mocked pipe test or source review replaces required actual connected acceptance.

## First published candidate and bounded selector correction

Draft PR29 head `d77bae6edaf697a57460d105574db04fe185bb81` preserves local commit `48af65f0a19f3b7d3f3600f4d2284e4796c71997` and tree `5a5feb40baf972bcdcd3fa91562ffc9eb0e7eed8`. The tested PR merge `35a7ca901d5ebfed5cad73874231ac56a27041ed` has that identical tree and the accepted PR28 parent. The initial controlled workflow passed its existing 41 cases in 175.55s, then failed the new provider case in 22.38s at `keyword_plan`, with no 201 creation response recorded. Its sanitized Error/unknown receipt does not establish the underlying historical exception. Original static UI independently passed in 64.57s; browser, parser, packaging and documentation passed. Application was still running when this checkpoint was written.

Independent source inspection establishes that Dashboard and Workspace navigation both contain an exact `New extraction` button. The provider case previously used an ambiguous global selector. The bounded correction scopes only that first provider activation to the named Workspace navigation. The static case, all deadlines, policies, worker and isolation controls are unchanged. A source-AST selector regression proves that the authored target selects the navigation button despite the duplicate dashboard shortcut; it is a model, not actual browser evidence. Independent review passed all 13 worker/selector tests in 0.53s and scoped lint/diff checks. New required application total is 2195 with no skips (one additional pure regression). Fresh seven-workflow execution remains required.

Correction local gates both exited 0: normal aggregate passed 1935/260 explicit service-container skips in 66.66s; genuinely absent `/tmp/emailmonitor-selector-empty-VzZK3p/venv` was synchronized with 63 locked packages and passed 1935/260 in 68.63s. Both passed 31 React and all static, contract, inventory and build checks. Logs: `/tmp/em015g-correction-normal.log` and `/tmp/em015g-correction-empty.log`. The download cache and frozen frontend install were reused. These local skips remain missing execution evidence; actual new-head acceptance is pending.

The first head's application run 38841761747 subsequently completed successfully: 2194 actual cases, no skips in 623.75s, plus 31 React and aggregate checks. It has no pytest warning summary; inherited EM-WARN-01 remains open, and infrastructure warnings remain visible. Thus six first-head workflows passed; only the new provider UI acceptance failed. All seven initial runs were terminal before publishing the selector correction.

# EM-015c — synthetic isolated XML pipeline candidate

Date:2026-10-15. Status: local candidate, partial EM-015; no live/production acceptance.

## Accepted dependency and scope

The coordinator independently reconciled the preceding owned cleanup checkpoint, Draft/open/unmerged [PR24](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/24), remote head `dfe2c5a77b1703adb26e871b01dd9b4960c2e60b`, with all seven attempt1 gates successful: application1760/no skips/no pytest warnings in453.35s plus31React; controlled14 in92.95s; actual UI1 in62.83s plus31React; browser/parser/docs/packaging passed. This local work began at `67f38a0`, tree `3e3592191a5aada97e34436100411c5aa9dcbfe3`, matching that reconciled parent tree and actual merge `12ec7ff43a0aa2b4c5cfe4f76c84a52b8e3ebe89`. Historical PR23/24 report entries are not rewritten by this candidate.

Boundary: one fixed authored XML URL, actual bounded isolated parser result, current tenant persistence, review and existing exports. No publication, merge, deployment, live grant, credential, new dependency, sandbox control or security-setting change is authorized or performed here. [Runbook48](../docs/48-synthetic-xml-pipeline.md) defines capabilities and exclusions.

## Implementation and review corrections

- Fixed local-image-only parser command; stdin bytes and bounded stdout observation, current fixed digest/identifier/profile validation, no host XML fallback, no mounts/secrets/tenant authority in the child.
- Typed retained XML distinguishes literal raw evidence from policy-stripped locator-only retention. Canonical document metadata remains separate from actual synthetic acquisition provenance.
- Additive0012 preserves latest0011 privacy/deletion/session/lease/retention guards, existing role grants and RLS. XML requires explicit fixture-only source permission. Existing four-article searches and HTML/browser invariants remain intact.
- XML structural association evidence is consumed; identity starts needs_review, human acceptance requires retained evidence, technical/domain/delivery/outreach states remain separate.
- Incremental independent read-only review found and corrected implicit image-pull risk, missing mount checks, partial status incorrectly implying job completion, and unsupported/empty excerpt-flag semantics. Final independent review of staged tree `30231be443e759dbc5c32c1fcf1af24cdb9e6574` versus `67f38a0` cleared source after correcting a missed multiline excerpt-permission condition and the CSV bundle-member assertion. The reviewer confirmed unchanged lifecycle/ACL/RLS, fixed route, local immutable image/no-pull/bounded IPC, no child authority/host fallback, conservative mapping and explicit partial outcomes. `git diff --cached --check` was clean. Final report-only updates are separately reconciled before commit.

## Local checks

Initial development aggregate after the first integration tests:1582 passed/239 explicit skips in23.25s;31React; docs, contract examples, ruff, mypy, inventory, frozen dependency install, peer checks, TypeScript, ESLint and production frontend build passed. This was an intermediate tree. The239 skips comprise219 inherited service-dependent cases plus20 then-new XML database cases.

Before original PR25 publication, runtime/test tree aggregate checks both passed:

- Normal `UV_CACHE_DIR=/tmp/emailmonitor-uv-cache scripts/check.sh`:1586 passed/242 explicit skips in22.52s,31React and all static/docs/inventory/dependency/type/lint/build gates.
- Genuinely new empty Python environment `/tmp/emailmonitor-em015c-empty-ITsebE/venv`, verified absent before `uv sync`, using the same bounded uv cache and `UV_PROJECT_ENVIRONMENT`:1586 passed/242 explicit skips in24.37s,31React and the same full gates. The log records creating the environment and installing63 locked packages. No warm project venv substitutes for this check.
- Focused XML tests:45 pure passed;23 actual service/container cases explicitly skipped locally.242 aggregate skips comprise219 inherited service cases plus23 XML integration cases. That original candidate expected1828 application cases with no service skips and all seven gates; the correction below adds39 pure diagnostic cases.
- Current docs validation:66 Markdown documents,252 local targets,56 JSON files,24 schemas,27 examples; four unique original fixture articles remain unchanged.

No actual Docker/PostgreSQL/RabbitMQ/XML integration execution was available in this local workspace; absent service tests are explicit skips, not passes. Source approval and local gates do not establish runtime acceptance.

## Required actual own-head CI evidence

All seven inherited jobs remain mandatory. Application builds the reviewed parser image and requires `EM_REQUIRE_XML_ISOLATION=true`; its new tests send the actual channel result into tenant persistence, review and both export formats. The successful same-container test emits `XML_SAME_CONTAINER_DATABASE_REVIEW_EXPORT` with the checked image ID, network/read-only/memory/PID/cap profile, digest and persisted/reviewed/exported counts directly into the application job log (not only captured test output). Acceptance includes tenant B, no XML permission, stale/revoked/expired session/lease, cancellation/deletion/suppression/retention, binding mismatch, duplicate recovery and no-excerpt review refusal. Parser isolation retains actual network denial and OOM evidence and adds hostile XML/resource refusal. Controlled transport, browser, actual operator UI, docs and metadata packaging remain unchanged acceptance obligations.

Corrected-head CI remains required. Coordinator publication must reconcile actual remote parent/tree and independently verify every current-head full job log. Prior successful jobs never substitute for this candidate’s own gates.

## Migration, risks and next boundary

Migration0012 is forward-only and keeps128KiB envelopes; no new table, runtime privilege, policy bypass or live source appears. A rollback needs a reviewed forward repair preserving retained state. Missing real-wrapper/source permissions and authorized real samples remain EM-015/016 blockers; metadata packaging is still not a deployed extraction service. XML-specific browser keyboard acceptance is not claimed by reusing the prior Results/review/export screens. Historical intermittent test causes remain unproven/open.

## PR25 original-head failures and bounded correction

[PR25](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/25) original head `ce51d002117a6e6f37729fc3a5c40f073a936d1f`, actual merge `58094718af4cecb2b1090bb67c42321eb4fdd782`, uses the reviewed local tree `d349a1310a8a0e96fde398e0c6b39dbc2e3eccd4`. All seven attempt1 runs reached a terminal state before correction began. The [application build](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38667884199/job/116203889486) and [parser build](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38667884201/job/116203889142) failed before parser execution: `Dockerfile.parser:10` could not find `fixtures/xml/sciencedirect-article.xml` in the build context. The fixture was tracked, but the deny-all `.dockerignore` admitted only HTML/PDF fixtures. The prior static context test did not compare every fixture `COPY` source, so local passing tests missed this packaging defect.

The correction adds only an XML-directory allow/re-exclude pair and the exact authored fixture exception, leaving unknown XML siblings/descendants and final environment-file exclusions denied. The existing ordered-context regression now compares every parser fixture `COPY` source with the exact admitted-file set, verifies sources exist, rejects unknown XML siblings/nesting, and demonstrates both missing-file and broad-directory mutations. The enhanced test failed before the allowlist correction;95 focused discovery/isolation/XML cases passed afterward. Actual corrected-head builds remain required; pure ordered-rule checks are not Docker execution evidence.

The original [operator UI run](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38667884197/job/116203889057) separately passed31React but failed its one actual test in59.08s. Diagnostics showed a living worker, no publisher error, one parse consumer with three ready messages, three pending article items at attempts0, one observed/succeeded article and two succeeded discovery items. This repeats a prior stall signature; its cause remains unproven and is not explained or fixed by the XML context correction. Controlled transport passed14 in93.74s; docs, browser and packaging passed. Original failures are retained and no unchanged broken-code rerun substitutes for correction. All seven corrected-head gates,1867/no-skip application and the same-container persistence/review/export proof remain pending.

### Bounded UI worker observation, not a stall fix

Because the existing UI stall signature recurred, the corrected candidate also adds explicitly opted-in synthetic-UI-only worker observations. Supported Celery signals are filtered to the exact created application, execution task object/name and owned direct queue/exchange; readiness additionally requires the exact owned queue set. Thirteen closed stage counters distinguish worker readiness, task receipt/entry, successful envelope validation, claim entry/empty/acquired/error, processing entry/return/error and Celery postrun/failure. The worker emits at most512 cumulative fixed-prefix snapshots, each below1024bytes; it emits no task IDs, args, queue names, URLs, configuration, exception text or tracebacks. Normal fixture workers remain off by default. Observer failures preserve task return values and original exceptions.

The existing65,536-byte owned log tail is parsed with exact keys/stages, strict bounded integers, duplicate-key refusal and cumulative progression checks. Missing or invalid evidence has no count dictionary. Partial/truncated or saturated evidence is explicitly labelled and may retain the last complete cumulative snapshot; those counters are last-observed lower bounds, and a zero stage never proves no later activity. Truncation cannot reset a surviving cumulative snapshot. Only the sanitized snapshot joins existing timeout diagnostics. The existing8-second completion wait, consumer readiness, broker-probe deadline, solo pool, prefetch, acknowledgement settings and all sandbox controls are unchanged. A Celery `task_postrun` signal is **not** proof of broker acknowledgement; its pool callback happens later. Migration0010's admission wrapper can return before the inner deliveries counter, so attempts/deliveries0 does not prove that no broker delivery occurred. No admission or queue behavior is changed and no stall cause is claimed.

Pure diagnostic tests cover opt-in/off and foreign application/task/queue filtering, exact success/empty returns and claim/process exception identity, output bounds, hostile fields/text, invalid/truncated tails and cumulative cap semantics. Normal/new-empty aggregate receipts for this corrected tree are recorded below; final independent exact-tree review is required before commit. Actual corrected-head CI remains the next acceptance boundary.

### Corrected candidate local gates

- Enhanced build-context regression failed before its narrow allowlist fix; focused discovery/isolation/XML checks passed95. Final combined diagnostic/protocol/context/XML focused set passed218 in3.22s, including39 new worker diagnostic cases.
- Normal `UV_CACHE_DIR=/tmp/emailmonitor-uv-cache scripts/check.sh`:1625 passed/242 explicit service skips in24.03s,31React and all docs/schema/examples, ruff, mypy208files, license inventory, locked dependency/peer, TypeScript, ESLint and frontend build gates passed.
- Genuinely new empty Python `/tmp/emailmonitor-em015c-correction-empty-FhSAPX/venv`, verified absent before sync:1625 passed/242 explicit service skips in25.41s,31React and the same complete gates passed. The log records environment creation and installation of63 locked packages.
- The unchanged242 service skips remain219 inherited plus23 XML service cases. No local Docker/PostgreSQL/RabbitMQ execution is claimed. Corrected own-head CI must run1867 application cases without service skips and all seven gates, including actual same-container XML persistence/review/export and the unchanged actual UI acceptance.

Raw local receipts are `/tmp/em015c-correction-normal.log` and `/tmp/em015c-correction-empty.log`. The source/test candidate tree is `430e98adf25e8fe86d86f9307f36ffd3324c0f32`; final documentation-only reconciliation and exact-tree review precede commit. Static documentation validation still covers66 Markdown documents,252 local targets,56 JSON files,24 schemas and27 valid examples. No source authority, sandbox profile, migration, live permission or dependency changes are added by this correction.

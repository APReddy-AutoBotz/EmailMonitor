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

Final runtime/test tree aggregate checks both passed:

- Normal `UV_CACHE_DIR=/tmp/emailmonitor-uv-cache scripts/check.sh`:1586 passed/242 explicit skips in22.52s,31React and all static/docs/inventory/dependency/type/lint/build gates.
- Genuinely new empty Python environment `/tmp/emailmonitor-em015c-empty-ITsebE/venv`, verified absent before `uv sync`, using the same bounded uv cache and `UV_PROJECT_ENVIRONMENT`:1586 passed/242 explicit skips in24.37s,31React and the same full gates. The log records creating the environment and installing63 locked packages. No warm project venv substitutes for this check.
- Focused XML tests:45 pure passed;23 actual service/container cases explicitly skipped locally.242 aggregate skips comprise219 inherited service cases plus23 XML integration cases. Actual CI must run1828 application cases with no service skips and all seven gates.
- Current docs validation:66 Markdown documents,252 local targets,56 JSON files,24 schemas,27 examples; four unique original fixture articles remain unchanged.

No actual Docker/PostgreSQL/RabbitMQ/XML integration execution was available in this local workspace; absent service tests are explicit skips, not passes. Source approval and local gates do not establish runtime acceptance.

## Required actual own-head CI evidence

All seven inherited jobs remain mandatory. Application builds the reviewed parser image and requires `EM_REQUIRE_XML_ISOLATION=true`; its new tests send the actual channel result into tenant persistence, review and both export formats. The successful same-container test emits `XML_SAME_CONTAINER_DATABASE_REVIEW_EXPORT` with the checked image ID, network/read-only/memory/PID/cap profile, digest and persisted/reviewed/exported counts directly into the application job log (not only captured test output). Acceptance includes tenant B, no XML permission, stale/revoked/expired session/lease, cancellation/deletion/suppression/retention, binding mismatch, duplicate recovery and no-excerpt review refusal. Parser isolation retains actual network denial and OOM evidence and adds hostile XML/resource refusal. Controlled transport, browser, actual operator UI, docs and metadata packaging remain unchanged acceptance obligations.

No exact-head CI result is claimed in this local report. Coordinator publication must reconcile actual remote parent/tree and independently verify every current-head full job log. Prior successful jobs never substitute for this candidate’s own gates.

## Migration, risks and next boundary

Migration0012 is forward-only and keeps128KiB envelopes; no new table, runtime privilege, policy bypass or live source appears. A rollback needs a reviewed forward repair preserving retained state. Missing real-wrapper/source permissions and authorized real samples remain EM-015/016 blockers; metadata packaging is still not a deployed extraction service. XML-specific browser keyboard acceptance is not claimed by reusing the prior Results/review/export screens. Historical intermittent test causes remain unproven/open.

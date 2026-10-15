# EM-015f — Controlled provider keyword-to-export journey

Status: local candidate, partial EM-015. No live publisher traffic, real credentials, source activation, security/network changes, new dependency, merge or deployment. Required actual own-head database/container gates remain pending.

## Baseline and implementation

The baseline local `d26212fb` / tree `609831a13104bd76ae1aafa3f4a48cec4f7821ad` matches reconciled Draft [PR27](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/27) head `86c59f30391c4b67227d092e646040067badbf0f`. The coordinator recorded all seven terminal successful workflows, including 2057 application/no skips/one inherited Pydantic warning, 31 React and 31 controlled transport cases. Those earlier provider HTTPS→parser and fixed XML→database proofs were separate; they did not establish the connected journey implemented here.

Branch: `feat/em015f-controlled-provider-journey`. The bounded bridge connects one controlled keyword to native PUT search, two registry-bound DOI/PII FULL GETs, same-byte isolated parsing, current-authority SQL retention, conservative association review and CSV/XLSX. Server-owned logical source identity remains distinct from canonical API identity and explicit controlled-fixture provenance. Source admission uses genuine SQL tickets rather than diagnostic booleans. Original four-article HTML and fixed XML flows remain intact. See [runbook51](../docs/51-controlled-provider-journey.md) for request semantics, invariants, migration, actual acceptance and activation limits.

Files: provider document registry and durable journey modules; retained XML model/schema and service; canonical request/shared URL safety; source/discovery/extraction/progress integration; additive migration0013; authored PII fixture; controlled fixture/owned-pipe/topology and journey acceptance; pure/SQL/RPC/CI/catalog regression tests; workflow and documentation.

## Review and observed attempts

- Early inherited provider/boundary/XML/fetch/discovery focus: 306 passed, 3 explicit actual-container skips in 4.49s.
- New pure/SQL/XML focus: 62 passed, 15 actual-database skips in 1.18s. These SQL tests supply host observations and expressly do not claim transport proof.
- Subsequent shared provider/XML/safety/admission focus: 295 passed, 18 explicit skips in 5.39s.
- Independent moving-tree review checked complete latest0012 guard preservation, source/transport identity separation, registry fixture hashes and canonical FULL fingerprints. It found cleanup failure could skip poisoning and resource-mode success could omit a ticket. Both were corrected; missing/duplicate/valid lifecycle and cleanup-error tests were added. Focused RPC/registry suite: 32 passed in 1.31s.
- Review recommended an actual one-article cap test and SQL admission-spacing/source-accounting assertions. Both are included in the required actual gate, now 41 cases across three sequential unchanged topology instances.
- Follow-up independent review found the actual acceptance selected an unused `path` column outside the runtime column grant. The query now selects only permitted operation/state; no grant was expanded.
- Review also distinguished admission spacing from variable DNS/TLS-to-HTTP arrival delays. The journey test now checks actual tenant SQL reservation timestamps across all three acquisitions, and unchanged timestamp on recovery, rather than a potentially flaky HTTP arrival delta.
- First aggregate stopped at one overlong catalog test assertion. Formatter repaired it; no test execution or passing full gate is inferred from that attempt.

## Verification

- Focused provider journey/SQL boundary/transport/RPC/binding/XML/safety/admission command: `UV_CACHE_DIR=/tmp/emailmonitor-uv-cache uv run --project services/backend pytest -q services/backend/tests/test_provider_journey.py services/backend/tests/test_provider_journey_tenant.py services/backend/tests/test_provider_transport.py services/backend/tests/test_provider_rpc.py services/backend/tests/test_provider_boundary.py services/backend/tests/test_xml_pipeline.py services/backend/tests/test_fetch_safety.py services/backend/tests/test_admission_acceptance_contract.py`; 298 passed, 18 explicit service/container skips in 4.89s. Log: `/tmp/em015f-focused.log`.
- All three controlled modules collect 41 cases with the workflow's exact `PYTHONPATH=services/backend/src:services/backend/tests:scripts/isolation`; collection took 0.78s. Log: `/tmp/em015f-collection.log`. Collection is not execution.
- Normal aggregate: `UV_CACHE_DIR=/tmp/emailmonitor-uv-cache scripts/check.sh`; 1834 passed, 260 explicit service/container skips in 53.87s, plus 31 React and all aggregate gates. Log: `/tmp/em015f-normal-attempt2.log`. Documentation was subsequently added and revalidated in the new-environment gate.
- Genuinely new environment `/tmp/emailmonitor-em015f-empty-26kIpU/venv`, verified absent before sync: `UV_CACHE_DIR=/tmp/emailmonitor-uv-cache UV_PROJECT_ENVIRONMENT=/tmp/emailmonitor-em015f-empty-26kIpU/venv scripts/check.sh`; 1834 passed, 260 skips in 54.86s, plus 31 React and all aggregate gates. Creation and installation of 63 locked packages are recorded in `/tmp/em015f-empty.log`.
- Both use Python 3.12.14 and pass Ruff lint/format (227 files), mypy (225 files), locked install/peer checks, inventory (64 Python/159 JavaScript packages), TypeScript, ESLint and frontend build. The new-environment documentation gate checks 69 Markdown files/280 local targets, 56 JSON files, 24 schemas and 27 valid examples. Neither local pytest run emitted a warning summary; inherited EM-WARN-01 remains open.

- Post-recovery final-source aggregates both exited 0: normal 1834 passed / 260 explicit service skips in 52.76s; independently new absent-before-sync Python environment `/tmp/emailmonitor-em015f-recovered-empty-9tOpbY/venv` 1834 / 260 in 52.91s. Both passed 31 React and every aggregate gate. Logs: `/tmp/em015f-recovered-normal.log`, `/tmp/em015f-recovered-empty.log`. Cache and frozen frontend installation reused; no fresh-frontend claim.
- Independent recovered-source review cleared the entire bridge and corrections at worktree content tree `fb8044318746c074a289a1ddd17a49e4646c21b6`, with 298 focused passes / 18 service skips in 4.67s and 41 controlled cases collected. It verified latest SQL guard preservation and actual runtime SELECT grants for the corrected admission timestamp query. Final report-only result recording follows that review.

No local Docker or PostgreSQL executable is available, so actual service/container behavior is not claimed. The 37 added application cases require 2094/no-skip own-head application CI, with 31 React, while the controlled workflow requires 41 actual cases/no skips/no warnings. All seven own-head workflows must pass without substituting collection, local skips or historical success. Final report-only updates rerun documentation and diff checks; immutable-tree independent approval is recorded in the handoff.

## Migration and remaining work

Migration0013 is forward-only and preserves all inherited tenant/source/privacy/session/lease controls. It seeds only owner-maintained synthetic route/document metadata and does not approve or broaden an existing tenant policy. Source revert is not a database downgrade; durable repair requires a reviewed forward migration. This candidate does not apply a deployed migration.

Real source authorization/FULL entitlement, representative approved samples and wrapper compatibility, credential-store integration, live source admission/DNS/egress composition and production registration remain unimplemented or unverified. The controlled integration makes those boundaries explicit rather than treating an API key as sufficient. EM-015/016 and authorized pilot acceptance remain partial. Inherited EM-WARN-01 remains open and unsuppressed.

Next: final immutable-tree review, coordinator publication on the reconciled parent, all seven actual own-head CI and evidence reconciliation. Exact commit/tree identifiers are provided in the handoff rather than self-referenced in this report.

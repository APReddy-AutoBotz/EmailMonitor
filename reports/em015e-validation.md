# EM-015e — Controlled executable provider gateway prerequisite

Status: local candidate, partial EM-015. No real provider traffic, source grants, credentials, security/network-setting changes, dependency, migration, merge or deployment. Actual controlled HTTPS/parser execution requires new own-head CI; local simulation is not that proof.

## Baseline and bounded change

Baseline local `cadbf9b` / tree `7ed147ee83a0c5b8915c53927a293b371d566095` was reconciled by the coordinator with corrected Draft [PR26](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/26) head `13a83fdc732bd0c7ee10945521ee4448e4263fd3`. Its all-seven-gate acceptance includes 2006 application/no skips and 31 React, with one inherited Pydantic warning still open. This new feature branch `feat/em015e-controlled-provider-gateway` needs its own evidence.

The shared `ProtectedGateway` now dispatches typed native PUT search and GET XML through its existing literal-socket/TLS boundary. Added credential-reference resolver port defaults to unavailable, validates exact dispatch scope and confines a short-lived value to the original fixed origin. The controlled fixture supplies only one fake value. Shared HTTP framing/byte/deadline/cleanup checks reject redirects, challenges and invalid streams; provider authority is rechecked across admission, credential/DNS/TLS latency, reads and release. The old HTML callback schedule and all network/security profiles remain intact.

Official native method and default-view/entitlement limitations were independently reviewed against the [search WADL](https://dev.elsevier.com/documentation/ScienceDirectSearchAPI.wadl) and [article WADL](https://dev.elsevier.com/documentation/ArticleRetrievalAPI.wadl). No API call was made. Details, limits and rollback: [runbook50](../docs/50-controlled-provider-gateway.md).

Files: backend fetching `protected.py`, `sciencedirect.py`, new `credentials.py`; provider transport/RPC tests; controlled fixture/gateway/topology and new owned-pipe provider diagnostic/module acceptance; existing ephemeral certificate helper; exact CI-count regressions/workflow; runbooks49/50, contracts notes, status, traceability, changelog and this report. No public JSON schema changes.

## Review corrections and observed attempts

- Early focused provider/shared-boundary run: 134 passed/3 actual-container skips. After transport regressions, 232 passed/3 skips in 3.81s. These precede final RPC/CI fixes.
- First full aggregate reached 1793 passed/245 skips and 7 failures in 51.50s; every failure was an obsolete expected 14-case controlled-workflow count. Assertions were changed to the exact 31-case gate, preserving substring/invalid-summary refusals.
- Independent source review caught the legacy receipt validator rejecting new fixed provider headers; it now validates closed separate shapes, with a regression preserving exact legacy headers and rejecting unredacted credentials.
- Review reproduced 33 callbacks for a legitimate fragmented two-hop legacy response against its 32-frame protocol cap. Shared read mechanics now take an internal check callback: legacy keeps its original deadline-only read schedule/current release check; provider rechecks current authority before/after each read. No protocol cap is raised. A one-byte-fragment regression guards the legacy behavior.
- Review identified aggregate fixture lifetime-command pressure from adding provider cases to the legacy held-response polling budget. Provider 17 cases now run in a second sequential module-scoped instance of the unchanged owned topology after legacy cleanup; existing 128-command, frame/output and network/security limits remain unchanged.
- Malformed terminal/current-binding protocol regressions cover wrong query, lease, boolean revision, digest, peers and unknown fields. Invalid or uncertain protocol poisons the channel; exact denied completion remains reusable. 51 focused provider transport/RPC tests passed in 3.33s before the final module split.
- Local test collection initially omitted the workflow PYTHONPATH and failed to import a helper. With the workflow’s exact PYTHONPATH, both controlled modules collect 31 tests. Collection is not execution.

## Final local verification

- Focused command: `UV_CACHE_DIR=/tmp/emailmonitor-uv-cache uv run --project services/backend pytest services/backend/tests/test_provider_transport.py services/backend/tests/test_provider_rpc.py services/backend/tests/test_provider_boundary.py services/backend/tests/test_protected_transport.py services/backend/tests/test_transport_cleanup_contract.py -q`; 244 passed/3 actual-container skips in 4.54s. Log: `/tmp/em015e-focused.log`.
- Normal aggregate: `UV_CACHE_DIR=/tmp/emailmonitor-uv-cache scripts/check.sh`; 1812 passed/245 explicit service/container skips in 52.16s, 31 React and every aggregate gate. Log: `/tmp/em015e-normal.log`.
- Genuinely new Python environment `/tmp/emailmonitor-em015e-empty-Mm18VL/venv`, verified absent before sync: `UV_CACHE_DIR=/tmp/emailmonitor-uv-cache UV_PROJECT_ENVIRONMENT=/tmp/emailmonitor-em015e-empty-Mm18VL/venv scripts/check.sh`; 1812 passed/245 skips in 53.71s, 31 React and every aggregate gate. Creation/installation of 63 locked packages is recorded in `/tmp/em015e-empty.log`.
- Both full gates used Python 3.12.14, passed Ruff lint/format 221 files, mypy 219 files, locked installation/peer checks, inventory 64 Python/159 JavaScript locked packages, TypeScript, ESLint and frontend build. Documentation check: 68 Markdown documents, 271 local targets, 56 JSON files, 24 schemas, 27 valid examples. No local pytest warning summary; inherited EM-WARN-01 stays open.
- Independent corrected-source review found no remaining blocking source defect; independently passed 244 focused/3 container skips, 51 provider transport/RPC and 31 controlled test collection. A no-I/O execution of the exact imported module-scoped fixture confirmed start→close→start→close. A fragmented two-hop source reproduction used 17 callbacks against the unchanged 32-frame cap. These are protocol/lifecycle observations, not actual Docker evidence.

Docker is not available locally, so no controlled topology, real services or isolated container run is claimed. Existing 245 service/container skips remain unmet local evidence. The 51 added pure tests require 2057/no-skip application acceptance; the separate controlled gate requires 31 actual cases/no skips/no warnings. All seven own-head gates and final immutable-tree review remain required. Final report-only edits rerun the documentation validator and diff check; exact tree identity is in the commit handoff rather than self-referenced here.

## Remaining acceptance and next task

Live source authorization/entitlement and approved actual samples remain unverified. Real tenant/provider admission, secret-store implementation, usable public DNS/egress composition, live worker/API registration, full-text view/compatibility, pilot and held-out benchmark remain unimplemented or unverified. The controlled authoritative resolver intentionally rejects ordinary recursive/CNAME/long-TTL responses. Existing fixed synthetic persistence restrictions remain unchanged. Credentials are not the only remaining activation prerequisite.

Next: exact-tree independent review, coordinator publication on the reconciled remote parent, and all-seven actual own-head CI/evidence reconciliation. No local mock, skip or collected test can close the HTTPS→isolated-parser gate. Rollback is a source revert and rebuild of matching diagnostic images; there is no durable data migration or deployed service change.

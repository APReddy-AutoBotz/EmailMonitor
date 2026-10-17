# EM-017e packaged-base inventory validation

## Accepted baseline

Draft PR33 head `f7dd90921b3229407350256b39e078414909120f`, tree `eef3775a7f946ed1d2511c07756b5466cfafd17a`, passed all seven first-attempt workflows: 2384 actual backend tests without skips, 31 React tests, controlled 41 plus normal operator 1, static UI/browser/parser/docs and both metadata/XML reproducibility gates. Actual application/provider/operator parser image IDs matched each prepared curated artifact; artifact hashes matched independent packaging builds and owned cleanup passed. Final published receipt was independently reviewed.

On resumption the recovered original cloud workspace was clean at local equivalent `ab2b9fb8d90f7e299e1071fff5ef87eb28b5a922`, with the exact accepted tree. No environment restart or switch was performed. No competing EmailMonitor worker or running acceptance was found. Docker remains unavailable locally.

## Candidate scope and required gates

The bounded inventory-only addition uses fixed read-only image inputs and the existing same-container probes. No runtime/dependency/base/security/source change is intended. Focused tests, normal/new-empty aggregates and independent source review passed. Final exact-tree review and all seven actual workflows are pending. Local mocked/fixture inventory does not establish installed-image evidence. Whole-image attribution, complete SBOM, signing, vulnerability/license clearance and production readiness are not claimed.

## Local source checks

Independent review ran 316 relevant packaging tests, including 65 collector cases, composed-payload execution, both two-build consumer gates and XML integration refusal paths. The final collector source is 18,854 bytes; its SHA256 is `a9ce1897ee4d12e8dc6b55d4699d4eacb18cdf3cd54fe269a61a0b8df9f677ca`. Review found no blocking source issue. Actual pinned-base format compatibility and the report-size bound still require installed-image CI evidence.

An initial normal aggregate was interrupted after 2213 Python tests passed with 260 service-dependent skips, strict mypy over 245 files, license-inventory validation, and frontend dependency/peer checks. Its polling action was rejected because of an unrelated-project authorization classification; the specifically authorized identical retry returned an unknown process ID. The retained log has no aggregate exit receipt, so that run is not counted as a successful aggregate. A clean rerun is required; the interrupted output is preserved separately.

The clean normal aggregate completed with exit 0: 2213 Python passes, 260 explicit service-dependent skips in 72.13 seconds, strict mypy over 245 files, all Ruff/docs/contracts/inventory checks, 31 React passes, frontend type/lint/build checks. A separately created Python environment, confirmed absent before sync at `/tmp/emailmonitor-em017e-empty-eQAFfC/venv`, also completed the full aggregate with exit 0: 2213 passes/260 skips in 73.09 seconds and the same 31 React passes/checks. Dependency download caches and the existing frontend installation were reused; the second Python environment was genuinely new. Local Python was 3.12.14; installed-image Python remains the pinned 3.12.13 base and must be exercised in actual CI.

All 260 skipped service-dependent cases still require the actual application workflow. Docker is unavailable in this cloud workspace. No installed-image, source-policy or production-readiness claim is inferred from local fixture tests. Independent exact-tree review and seven own-head workflow results remain publication-time gates; the final draft description will carry immutable receipts without rewriting the accepted tested tree.

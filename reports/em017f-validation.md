# EM-017f test runtime composition validation

## Accepted baseline and recovery

Draft PR34 head `ecf314a09f9ec2c07f02714802a95ad123f14515`, tree `453edbeb8c532c23b618b9a196baf54f95f8cebb`, retains all seven first-attempt successful workflows. Its final reviewed description records 2473 actual backend tests without skips, 31 React tests, controlled 41/operator 1 and six reconciled installed inventories.

On explicit restart, the original cloud workspace was available but its clean checkout had reverted to an earlier PR25-era snapshot. No implementation or tests ran on that stale tree. The 101 differing public Git blobs were retrieved from their immutable GitHub IDs, individually hash-verified, and restored on a separate recovery branch. The resulting local tree exactly equals PR34; recovery commit `dd63a06b596a340930413e42fc1ac0501a392758` is local bookkeeping, not remote ancestry. No competing EmailMonitor writer or protected acceptance run was found. Further publication must parent the accepted remote PR34 head, not accumulated recovered local history.

## Candidate boundary

Independent design review found the owned test API/authentication/publisher SQL composition dependency-ready. Existing worker, broker semantics, source policy, private SQL artifacts, parser/browser isolation and production refusals remain unchanged. The actual operator case must consume the composition. Partial-startup cleanup, closed-app admission, configuration/secret refusal and real SQL authority evidence are required. No global request-drain/deadline or owned broker-pool claim is made.

Focused checks and normal/new-empty aggregates passed. Independent final exact-tree review and all seven own-head actual workflows remain pending. Local service/container skips must remain explicit. No live-source, production identity, hosting/storage/secrets provisioning, release, merge or deployment acceptance is claimed.

## Local validation and independent review

The implementation adds 123 pure runtime cases. Independent focused checks passed 137 cases (new runtime plus existing provider-worker cases), with four explicit actual-PostgreSQL skips. The combined runtime/scaffold/framework-warning regression run passed 145 cases without skips/warnings. Scoped Ruff, formatting and strict mypy passed. Design/source review corrected the final tenant-B job/export assertions to use the new owned API instead of a separately constructed Scenario app; the acceptance predicates and deadlines did not change.

An initial full aggregate passed before that evidence-linkage correction (2336 Python passes/264 skips, 31 React, exit 0). Final-source normal and genuinely new-empty Python aggregates both completed with explicit exit 0 receipts: 2336 passes/264 service-dependent skips in 101.73s/108.23s, 31 React tests, strict mypy over 249 files, Ruff, documentation/contracts, license inventory, frontend peer/type/lint/build checks. The new Python environment was confirmed absent before synchronization at `/tmp/emailmonitor-em017f-empty-ZHjmPi/venv`; dependency caches and frontend installation were reused. Local Python was 3.12.14. Docker remains unavailable locally.

The 264 skipped service cases are not acceptance. Own-head application CI must execute all 2600 backend cases without skips; the controlled gate must preserve 41 transport cases and the normal operator case while proving owned-runtime closure and separate API/publisher pools. All seven existing workflows, packaged inventory/image proofs and independent final evidence review remain required. Final PR description will summarize verified exact-head/tree workflow receipts without rewriting the tested source tree.

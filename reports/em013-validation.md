# EM-013 validation — synthetic shared admission and administration

## Dependency and current status

EM-012's reviewed acceptance checkpoint head828fa26957560035c55f7b91bd0915ba223330f4 and merge1b4f694a39792fd765a63f7eab7a1f0063d4dbe1 share treea8a0643b3640c3409b2e587ae8720f9f26b23fc2; exact9fd9fbeb+828fa269 merge parents. Its own six gates succeeded:

- [Application38372357840](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38372357840), job115212204308:1132/no skips/one disclosed Pydantic alias warning283.34s;25 React tests/type/lint/build.
- [Keyboard UI38372357827](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38372357827), job115212204406:1/75.05s, actual authorized fixture PG/broker/export and unchanged sandbox/tenant/keyboard proof.
- [Controlled38372358059](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38372358059), job115212204958:12/57.26s.
- [Browser38372357743](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38372357743), job115212204075; [parser38372357825](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38372357825), job115212204061; [docs38372357988](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/38372357988), job115212205100:success.

PR17 and all predecessors remain Draft/unmerged. EM-WARN-01 remains open. No merge/live/production acceptance is inferred.

## Candidate and local evidence

EM-013 now has a bounded candidate migration0010, private metadata admission/configuration/reservation/settlement functions, current-authorized API and owner configuration/usage UI. Supported discovery/article/export messages route to distinct owned phase queues. Actual protected HTTP/browser hops acquire server-owned source/pool leases before DNS/TLS and recheck current permission on release. Authored fixture file reads are CPU admission, not fabricated network attempts. Once-only resolution units remain separate from admitted resource attempts. [Runbook42](../docs/42-offline-admission-runbook.md) states limits, migration impact, conservative unsupported Retry-After refusal and the required evidence.

- `bash scripts/check.sh`, `/tmp/em013-final-normal-check.log`: normal installed aggregate completed1051 Python tests with178 explicit PostgreSQL/broker/isolation skips in31.18s;28 React tests, lint/format, strict mypy173 source files, typecheck/build, docs/contracts/fixtures and inventory gates passed. The source inventory is unchanged64Python/159JavaScript; no new dependencies or license terms.
- Earlier in-flight aggregate stopped on a formatting line; a later run saw one10-second production-import subprocess timeout under concurrent collection load (1044passed/176skipped/1failed). Focused rerun52passed and the final full rerun passed with unchanged refusal assertion/deadline. These are local diagnostics, not service acceptance.
- `bash scripts/check.sh` in a source-only copy with initially absent installed environments, `/tmp/em013-fresh-check.log`:1051passed/178skipped in36.23s and the same static/docs/inventory/frontend gates passed. All candidate source files are byte-identical to that fresh copy; only this final evidence report differs.
- Collected application suite currently1229 tests. Actual no-skip PostgreSQL/broker CI remains required: configuration/role/private-helper privilege checks, concurrent claims, two-tenant fair contention, quota reduction/captured limits, recovery/cancellation reservations, once-only settlement and independent phase consumers.
- Controlled transport suite requires13 actual cases, adding held-source/other-tenant processing+private-export progress and actual source-attempt spacing to existing DNS/TLS/tenant/route/escape proof. Standalone browser/parser/docs and keyboard operator UI remain required. The keyboard case also checks literal owner branding/current usage and read-only-role refusal. No source/mock/static test establishes these execution results.

No local PostgreSQL, RabbitMQ, browser, Docker, container profile, host initializer or network topology was executed for this slice. Existing reviewed network/profile/ownership/baseline/cleanup restrictions remain unchanged. Independent exact-tree review and all six exact-head CI jobs are pending. PR17 description remains unchanged. Dependencies remain Draft/unmerged; no merge, real IdP, live provider, production, billing, paid quota contract or exceptional support access is accepted. EM-WARN-01 remains open and EM-014 remains gated.


## Independent review corrections in progress

Independent source review identified three blockers: pre-mutex grant/backoff timestamps could shorten spacing, successful resource finish accepted already-finished/waiting state, and draft parsing did not carry admission nonce/expiry into commit. The corrected candidate refreshes clocks after contention, requires current live source success completion, separates cleanup, conservatively retains a revoked source's active slot until physical completion/expiry, and binds draft fixture leases through SQL commit/release guards. Pure owned-context regressions and actual-CI contended-clock, expiry/cleanup/failure/success-replay/wrong-nonce/waiting and draft slot-reuse regressions were added. PostgreSQL lifecycle tests remain explicit local skips; no actual service proof is inferred.

The first corrected fresh-install attempt completed its Python/static checks but failed during package installation because pnpm's default home-store directory was unavailable. That incomplete run is not a completed aggregate. Source re-review then caught a malformed SQL literal in an actual-service regression; it was repaired and a pure AST check added so locally skipped SQL tests cannot hide this leading-quote artifact.

Final repaired normal aggregate (`repaired-normal.log`) passed1059/186 explicit skips in20.97s, and an empty source-only install (`empty-install.log`) passed1059/186 in23.93s. Both completed all static/docs/inventory/frontend gates, including28 React cases, using an explicitly owned pnpm home/store. Evidence is retained in `/workspace/shared/em013-20261013-validation/`. All tracked source files match the empty-install copy except this completion report. Current suite contains1245 cases; application CI must execute all without skips, alongside controlled13/browser/parser/docs/operator-UI gates. Exact-tree final re-review and actual CI remain pending. Earlier aggregates above describe historical review candidates, not corrected acceptance.

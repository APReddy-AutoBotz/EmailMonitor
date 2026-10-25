# Retained paper identity — local validation

Scope: FR-008/019 and paper-selection FR-023 within EM-009/011/012.
This is an unpublished candidate, not accepted hosted functionality or full FR-019
observation reuse. [Design and migration](../docs/71-retained-paper-identity.md).

## Completed local evidence

- Focused syntax/cursor and actual PostgreSQL tests: 30 passed in 59.05 seconds.
- Expanded actual PostgreSQL and pure regression run: 107 passed in 199.55 seconds,
  including both CSV/XLSX, independent tenants with the same DOI, simultaneous
  jobs, separate reviews, stale-worker refusal, original item intersections,
  immutable export membership and current deletion/retention/session/source fences.
- Full normal `scripts/check.sh all` succeeds: 6088 backend tests passed, 530
  explicit infrastructure skips, 108 React tests, plus static/type/contracts,
  dependency inventory and frontend build checks. Skips are not SQL proof.
- New migration applies in an owned disposable PostgreSQL 17.11 instance with
  direct non-owner runtime/authenticator fixture logins. New helpers remain
  private; no runtime function grant was added.

An independent fresh-worktree aggregate and exact-candidate SQL reconciliation
are required before handing the local candidate back for publication approval.
Their immutable candidate receipts are reported separately; this report does not
predeclare either result.

## Corrections and retained failures

The initial expression index required runtime EXECUTE on the private derivation.
The implementation instead uses an owner-maintained derived column and ordinary
index, without expanding helper permissions. Focused SQL then passed.

A development baseline run was invalidated by changing fixture bytes while it was
active; its partial successes are not acceptance. A subsequent unchanged-input
expanded regression passed. A later full run caught an out-of-order DOI fact in
the contract example; regenerating the example from the actual authored parser
corrected that mismatch without a runtime change.

A separate full run failed the unchanged 100 ms affiliation diagnostic pipe test:
expected `output_limit`, received `timeout`. Five bounded diagnostic trials then
returned `output_limit` in 21–37 ms, and all five original parameterized cases
passed. The later normal aggregate passed without changing this test, parser or
deadline. The original timing failure remains unexplained historical flakiness;
it is not claimed repaired by the paper feature.

## Pending acceptance and publication

The service-principal SQL harness refused local execution because genuine GitHub
Actions context is required. Its guard was not bypassed. Four paper-specific
service cases retain that same guard and test exact export delegation, no expanded
reads, replay, another-export refusal and deletion between claim and finish.

The authored keyboard journey now selects the observed DOI, checks an unknown
paper, validates its export preview and invalidates the preview when selection
changes. Actual installed/browser/service/broker and populated migration/restore
execution remain pending genuine CI. Existing workload inventories, budgets and
assertions are unchanged. Fresh migration is not populated-upgrade or production
restore proof. Cross-route equivalence and broad publisher DOI compatibility are
not established by the single authored HTML DOI fixture.

No public push/PR, merge, deployment, live acquisition, account grant, trust/proxy
change or held export reconciliation is included. Formal final review and
integration remain deferred. A new dependent public Draft requires its specific
publication approval; the earlier authored-PDF approval is not reused.

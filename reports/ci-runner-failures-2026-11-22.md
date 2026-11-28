# CI failures caused by the hosted runners, not by code (2026-11-22)

Four checks keep failing on the Open Access PRs ([APReddy-AutoBotz/EmailMonitor#72](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/72), [APReddy-AutoBotz/EmailMonitor#73](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/73)). The evidence below says the causes are the GitHub runners and the acceptance harnesses' timing, not the application. None of the harnesses were loosened: they are security controls, and weakening them to obtain a green check would be wrong.

## The deciding experiment

The last commit that passed `installed-operator` anywhere was `7e04c77` (branch `codex/checkpoint-recovered-focus-20261111`, 2026-11-11). It contains no Open Access code. Re-running that exact run on 2026-11-21 **failed** `installed-operator` with `installed_login_deadline`. Same code, new runners, new failure.

## Per check

| Check | Failure | Evidence it is environmental |
|---|---|---|
| `installed-operator` | `installed_login_deadline` (login callback page took about 18 s, `phase_ms` 18008) or `Owned cleanup failed: baseline_cleanup` | The 2026-11-11 green commit now fails the same way. On PR #73 all six installed tests fail during setup, before any application code runs. |
| `transport` | `Owned cleanup failed: baseline_cleanup` / "Preexisting host interfaces changed" (82 tests) | It passed on `6c94945` and `5258982` and failed on the documentation-only `8b86401`. The harness diagnostic shows leftover host interfaces and routes after Docker network teardown (`scripts/isolation/transport_topology.py`, `close()`). |
| `operator-ui` | `capture_geometry_refused` / `capture_session_refused` | It refuses at a different step on almost every run: `evidence_review`, `export_preview`, `job_deletion`, `url_worker`, `keyword_plan`. It was already failing before the Open Access work started. |
| `browser` | "Browser diagnostic deadline exceeded" (60 s) | One occurrence; it passed on re-run. |

## Root cause found for `baseline_cleanup` (2026-11-28)

In the failing runs, the cleanup check fails right after its own diagnostic reports `"status": "lifetime_only"` with `"lifetime": {"decreased": 2, ...}` and no other difference. Two IP address lifetimes on the runner's network interfaces counted down between the snapshot taken at the start of the test and the one taken at cleanup. The harness compares the snapshots exactly (`transport_topology.py` `close()`, `transport_host.py` "Preexisting host interfaces changed"), so any address with a finite lifetime makes cleanup fail on every run. The runners appear to have started carrying such addresses after 2026-11-11, which matches when the failures began.

**Rule (approved by the owner 2026-11-28, applied in `transport_host.host_unchanged` / `lifetime_countdown_only`):** treat two snapshots as unchanged when every interface, address, flag, route, rule and their order are identical, and the only differences are `valid_life_time` / `preferred_life_time` values that decreased while staying above zero. Increases, a lifetime reaching zero, and switching to or from infinite would still fail, as would any other change. The existing diagnostic already classifies exactly this case as `lifetime_only`. A first attempt was refused by the session's permission policy as weakening a safety check; it was applied only after the owner's explicit approval. If comparing fails for any reason, cleanup still refuses.

## Suggested investigation (owner or harness maintainers)

1. **`baseline_cleanup`.** Compare the host-interface baseline diagnostic between a passing run from 2026-11-11 and a current one. The runner image (Docker or kernel networking) likely now leaves veth interfaces and routes behind for a moment after network removal. The safe fix is to wait for teardown to complete, within a bound, before comparing. Do not relax the comparison.
2. **`installed_login_deadline`.** Measure the callback document phase on current runners. If they are consistently slower, raising the budget is a reviewed timing decision, not a security change. Record it in document 19.
3. **`operator-ui` capture refusals.** These need their own investigation of the pixel-redaction capture harness. The refusal family predates this work.

Local verification of the Open Access changes used a disposable PostgreSQL 17.11 container (document 26, "Local disposable container").

## Root cause found for `operator-ui` capture refusals (2026-11-28)

**This is a harness race, not the runners and not the Open Access work.** The capture harness was added in `a8be89c` ("Capture bounded synthetic operator review crops", 2026-11-02). The last green `operator-ui` run is `8d3b8f4`, the commit just before it. Every run since `a8be89c`, 24 sampled across `codex/staging-integration-pr68`, `codex/checkpoint-recovered-focus-20261111`, `feat/open-access-connectors`, `feat/oa-truthful-pipeline`, `feat/oa-persistence` and `fix/transport-lifetime-countdown`, failed inside a capture: `capture_session_refused`, `capture_geometry_refused`, `capture_mutated`, `capture_mask_values`, `capture_mask_install_refused` or `capture_state_focus`, at `keyword_plan`, `evidence_review`, `export_preview` or `job_deletion`. The check has never passed with captures enabled.

**Mechanism.** In the web app, every successful `act(...)` ends with `props.refresh()` (`apps/web/src/App.tsx`, `Workspace.act`). That bumps the revision of every `useResource`. While a refetch is in flight, `useResource` returns `{ loading: true }` with no data (`apps/web/src/ui.tsx`). So the workspace heading `<h2>Synthetic tenant 0</h2>` is replaced by "Loading current organization data…", and other `Load` sections re-render. The acceptance script waits only for the region it needs, such as "Server source plan" (set inside `act`'s work) or "Current export preview", and then captures immediately. Depending on when the refetch lands:

- **The refetch is still in flight when `capture()` starts:** the heading check fails with `capture_session_refused`.
- **It lands between the geometry samples or during the screenshot:** content above the target moves, so `before != after`, or the observer sees DOM churn. The result is `capture_geometry_refused`, or a mutation, mask or focus reason.
- **It finishes first:** that capture passes, and the run fails at a later one. That is why the failing step moves from run to run.

**Fix (harness timing only, no control changed).** `scripts/isolation/operator_ui_acceptance.py` now calls `settle_for_capture(page)` before each fixed capture. It is a bounded in-page wait, at most 10 s plus a 5 s host bound. It ends when `main#main.workspace` is not `aria-busy`, there is no "Loading current organization data" status, exactly one workspace heading exists, and the DOM has had no mutation for 500 ms. It returns only a Boolean, never moves focus or scroll, and disconnects its observer. If the page never settles, it does not raise: `capture()` runs unchanged and its own checks refuse. `operator_capture.py` (geometry, session, focus, mask and mutation checks) is untouched.

**Regression evidence (local Chromium, synthetic page, `services/backend/tests/test_operator_capture_settle.py`, 7 passed):**

- Reproduces the race: `capture()` during a simulated post-`act` refresh fails with `capture_session_refused`.
- With the settle step, the same page yields a full redacted `plan` capture.
- A page whose heading never returns is still refused by `capture()`.
- Continuous mutation is bounded and returns `False`.
- A settled page returns promptly with the DOM and focus unchanged.
- A host-side hang is refused.

Confirmation on the hosted runner comes from this PR's `operator-ui` run.

**Not addressed here.** The `installed-operator` timing failures (`installed_login_deadline`, `TimeoutError` at `export_preview`, `installed_redirect_failure_unarmed`) run in a different harness (`installed_operator_browser.py`) that does not use these captures. They remain open.

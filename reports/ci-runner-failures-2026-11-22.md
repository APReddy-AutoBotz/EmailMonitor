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

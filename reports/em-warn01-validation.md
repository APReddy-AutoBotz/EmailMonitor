# EM-WARN-01 — bounded test-assembly compatibility maintenance

## Accepted baseline and boundary

Draft PR29 head `b91794913ec20d9d623a8dff833ffa65268bd452`, local `48c759c33e67e0cf279d8b0fe2a722b9c14eee84`, tree `310a0fdead3c74d1d4ea83ac767d897403a18792` completed all seven exact-head workflows. Application passed 2196/no skips in 612.95s, 31 React; original controlled41 passed in 202.63s and separate normal-provider UI passed in 55.89s. Independent raw-log review confirmed actual final host assertions. This new maintenance slice addresses the compatibility caveat explicitly tracked in document22; it does not change product behavior or source authority.

## Causal evidence

The earlier exact-head application log for `e6df8d6c` records `UnsupportedFieldAttributeWarning` for alias `organization_id` during `test_concurrent_last_owner_removal_is_serialized`, from Pydantic `_generate_schema.py:2309`. Earlier runs showed `body` or `batch_id`. The pinned FastAPI 0.143.0 `ModelField.__post_init__` uses `warnings.catch_warnings` and a temporary filter around TypeAdapter construction. Local reproduction used Python3.12.14; historical host CI used Python3.12.3. The repository pins the Python3.12 minor, not this exact patch. Both use a process-global warning filter list. The test constructed both complete apps concurrently, unrelated to its intended SQL owner-removal race.

Independent no-database probes through actual `create_app`/`Foundation.router` deterministically interleave the first relevant adapter in two threads. Thread A exits its warning context while B remains inside; A restores the earlier filters, B emits the exact alias warning, and B's later exit restores A's stale filter. Fail-on-access database sentinels prove this needs no request, authentication or database call. Five fresh-process runs for each of the three historical aliases reproduced one matching warning; all 15 serial controls emitted zero. The category, text and source line match historical CI. Historical thread scheduling was not captured, so this is a causally reproduced mechanism consistent with the evidence, not a recovered historical stack trace.

## Narrow correction and regression boundary

Only the existing SQL test setup is changed: serially construct two independent database pools/apps/clients under ExitStack, registering disposal before subsequent assembly. Login and authenticated PATCH remain in two threads behind the unchanged barrier; the required `[200, 409]` result remains. No runtime lock, global warning filter, dependency update, request relaxation or application source change is introduced.

Seven pure cases include isolated subprocess serial/interleaved controls for all three aliases and a source-structure guard preserving concurrent requests, barrier, independent setup and cleanup. The child probes capture warnings rather than ignore them; dependency-native filters are the subject of the test. Outer warning capture and subprocess exit contain the intentional filter residue. These probes establish the mechanism but do not replace actual PostgreSQL concurrency acceptance. Initial authoring checks caught a flattened-route-count assumption (pinned FastAPI retains four top-level entries including an included-router container) and strict typing of the private compatibility module; corrected before final gates.

## Required acceptance

Independent source review, full normal and genuinely new-empty Python aggregates, and all seven exact-head workflows are required. Expected actual application inventory is 2203/no skips, plus 31 React. The unchanged actual last-owner test must run with separate DB pools and one successful/one refused removal. Original controlled41, separate actual provider1, static UI, parser/browser isolation, packaging and docs remain required. A warning-free isolated run alone cannot close all historical warning sources or the unrelated intermittent static UI exception.

## Local candidate receipts

Full normal aggregate exited 0: 1943 passed/260 explicit service-container skips in 71.58s, plus 31 React and all static/docs/contracts/inventory/build gates. A genuinely absent `/tmp/emailmonitor-warning-empty-kgaB3P/venv` was verified before locked synchronization; the same complete aggregate exited 0 with 1943/260 in 72.87s plus 31 React/all gates. Download cache and frozen frontend install were reused. Logs `/tmp/em-warn01-normal.log` and `/tmp/em-warn01-empty.log`. Neither run has a pytest warning summary; actual SQL/service/container cases remain skipped locally.

Independent review passed all seven causal/structure regressions in 5.57s and canonical root lint/format. A separate dynamic fake-resource execution of the actual corrected test verified successful completion, second-app construction failure, and worker request failure: assembly/disposal stayed on the main thread, login/PATCH used distinct worker threads, and both pools disposed exactly once after worker completion. This supports lifecycle/source review, not actual PostgreSQL evidence. The private-module type lookup was corrected before aggregates. Independent final immutable-tree review and actual own-head CI remain required.

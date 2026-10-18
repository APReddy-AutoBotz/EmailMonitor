# EM-017g owned test publisher validation

## Baseline and scope

Accepted Draft [PR35](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/35) is head `a13748ea3496e02caa17a433060ffa0bffb45f3d`, tree `42d742292520102c41f6c4545c52a6ff3cf518d0`; local equivalent `ee7f4c4504af3ca4c3961c429968ae694e3468c4`. All seven first-attempt workflows passed, including 2600 actual backend cases without skips, 31 React cases, actual owned runtime SQL checks and normal controlled operator acceptance. Independent source/evidence/final-description review passed.

This candidate adds only [finite owned test publication](../docs/57-owned-test-publisher.md). No production activation, new identity, source permission, dependency, migration, merge or deployment is included.

## Independent design

Read-only review of pinned Celery 5.6.3, Kombu 5.6.2 and py-amqp 5.4.1 approved the public send_task path with an explicit concrete producer. Metadata access is retained; no pooled transport acquisition is claimed for publication. Producer.release is a no-op, so channel and connection require separate cleanup. Explicit max_retries=0 is required for establishment. Existing mandatory/confirm and post-send marker semantics remain.

## Candidate validation

Implementation, focused tests, normal/new-empty Python aggregates, independent exact-tree review and all seven actual own-head workflows are pending at this initial checkpoint. Pure mocked cleanup cannot establish actual socket closure; local service skips cannot establish SQL/broker/operator acceptance. Failed attempts, if any, must remain recorded here.

## Preserved local attempts

- First focused run: 199 passed, four explicit disposable-service skips in 33.24s, exit 0.
- First aggregate stopped at two new-test import ordering errors. Single-file Ruff classification differed from the full aggregate targets; the exact aggregate command corrected only those imports. The original log is retained.
- Next aggregate reached pytest: 2404 passed, 268 explicit service skips, one failure in 101.27s, exit 1. Existing `test_owned_channel_admission_and_reply_share_one_deadline` saw identifier 9 rather than 8; all nine requests timed out and its cleanup assertions passed. An unchanged focused rerun passed in 0.44s. Each request establishes its own deadline, making scheduling order a plausible explanation; this does not prove the cause or fix the test. Its predicate and timeout remain unchanged. Final corrected normal/new-empty runs remain required.
- Independent source review found cached Celery routing/serializer state and optional result-backend paths could bypass the intended closed helper configuration. Corrections pin JSON/default-exchange forwarding and refuse unsafe effective routing/declarations; result-backend refusal and ignored-results regressions now pass. These findings were caught before publication.

Independent corrected focus: 85 passed and four explicit service skips in 1.41s, including 75 publisher cases and ten queue cases. Source review is clear after backend correction; full normal/new-empty and actual own-head gates remain required.

## Final local candidate checks

Corrected normal and genuinely new-empty Python aggregates each return explicit exit 0: 2411 passed, 268 explicit service skips in 100.59s and 131.63s respectively; 31 React cases, mypy over 252 files, exact full-target Ruff lint/format, docs/contracts, dependency inventory, frontend peer/type/lint/build checks pass. The fresh Python environment was absent before creation at `/tmp/emailmonitor-em017g-empty-iVmGNz/venv`; shared dependency caches and frontend installation were reused. Both aggregates exercise the unchanged channel deadline test successfully; the earlier failure remains unresolved and preserved above, not claimed fixed.

Independent review on final source bytes passes 85 focused cases with four explicit service skips in 1.58s and full-target Ruff/format over 254 files. Publisher source SHA256 is `a50a8e177bca2525fdfd0e20268429059d06087c478f427b3dcd2e103a8529fa`; pure tests `6019ed678d002ebf4fc84e1683f2e10e10472e09f09d51f8bc801ce673f25362`; actual-service tests `9d2e25b2f49c0556e21c195c926a6f267d6fdaa899ee9d03a4498500e83a1579`.

Actual local disposable SQL/RabbitMQ/Docker are unavailable. Required own-head application acceptance is 2679 backend cases without skips, including all four new actual-service cases, plus all seven existing workflows and controlled operator ownership receipt. This remains pending until published Draft CI evidence is reviewed; no local skip is counted as actual acceptance.

## First published head: retained actual failure

Draft PR36 head `130124def467baab13141beaf7ef018e0292e9ac` / tree `b639e9e823272257e7fe011e8527832ac4c34318` passed six first-attempt gates, including controlled 41 cases, normal owned-publisher operator acceptance, browser/static UI, parser, docs and packaging. The application run [39095132780](https://github.com/APReddy-AutoBotz/EmailMonitor/actions/runs/39095132780) returned 2678 passed, one failed, no skips in 498.94s. Its first three new actual publisher cases passed.

The fourth new test failed before calling the publisher: RabbitMQ 4.3.6 rejected its independent caller-survival queue declaration with 541 `transient_nonexcl_queues` disabled. This was test setup incompatibility, not the intended 404 partial-publication injection. The correction makes that uniquely named disposable caller queue exclusive to its existing connection. It changes no publisher, durable work queue, broker policy, credentials, isolation or success predicate. Original failed evidence remains retained; corrected local checks, independent exact-tree review and all seven actual own-head gates are required anew.

## Corrected fixture local checks

The exclusive caller-queue correction passes normal and a second genuinely new-empty Python aggregate, each with 2411 passed/268 explicit service skips, 31 React cases, mypy over 252 files and all static/build gates, explicit exit 0. Normal/fresh pytest took 90.89s/101.35s. Its environment `/tmp/emailmonitor-em017g-fix-empty-PyUPtJ/venv` was absent before creation; caches/frontend installation were reused. Independent corrected focus: 85 passed/four explicit service skips in 1.02s, full-target Ruff/format over 254 files and diff check pass. Corrected actual-service test SHA256: `2b8b3665736efe5e7a42d31bba36e9d774175a5974dac6b9400cda8d35f4e79e`. All actual corrected-head gates remain pending.

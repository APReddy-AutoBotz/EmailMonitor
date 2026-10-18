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

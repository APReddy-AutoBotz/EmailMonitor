# EM-006 — Offline discovery validation

## Candidate scope

Synthetic-only original-input planning, explicit spelling suggestion/confirmation, server-owned URL classification/preflight, bounded inert search parsing, durable two-page checkpoints and four-article dedup, immutable current-policy context, truthful caps/completeness and identifier-only confirmed broker scheduling. No dependencies were added; locked Python/JS versions and inventories remain unchanged. The parser Dockerfile only adds two authored fixture files; isolation configuration/security profiles/workflows are unchanged.

Migration 0004 adds tenant discovery and outbox state. The API exposes planning/status and one-page authored-fixture advancement only in explicit test mode. Celery resolves current durable authority for identifiers; discovery never substitutes persistence-probe effects for extraction. Default topic is Myocardial Infarction. Unsupported API fallback is labeled unavailable/not attempted.

## Initial pre-review validation snapshot

Initial candidate validation passed: focused discovery tests37 passed/15 explicit service skips; normal aggregate460 passed/69 explicit service skips in28.94s; fresh-empty locked installation aggregate460 passed/69 explicit service skips in33.48s. Both aggregate runs also passed docs/contracts, Ruff lint/format, strict mypy88 files, inventory63 Python/159 JavaScript, frontend type/lint/one React test/build. Runtime, migration, tests and parser-container source were byte-compared with the successful fresh copy. The command was `scripts/check.sh` with temporary uv/npm/XDG caches and `UV_LINK_MODE=copy`. No dependencies changed. The initial new-head expectation was application529/no skips, SQL/broker tests, network-none parser and existing controlled transport/browser/docs acceptance remain pending. No Docker, browser, network, privileged initialization or sysctl command has been executed locally for this slice. Full acceptance is not claimed from simulated transport, authored fixtures or local skips.

The predecessor checkpoint headc5844ecf/tree d8326ad1 passed all five required runs, including application477/no skips/no warnings and controlled12/no skips/no warnings; [PR10](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/10) remains Draft/unmerged. Historical alias warning EM-WARN-01 stays tracked because this slice does not establish a cause fix.

## Acceptance mapping

- Two fixture search pages: five observed entries, one duplicate, four unique scoped article URLs; no observed contacts
- Homepage: refinement without acquisition; unknown/source/PDF/DOI/filter/topic unsupported results without speculative crawling
- Query: preserve original and effective query; changed spelling requires explicit confirmation
- Partial: page/user/source article caps, loops/repeated fingerprints, changed selectors/totals and no-new-results are explicit; pagination exhaustion is not a fabricated unique denominator
- Durability: checkpoint and next outbox commit together; revision/generation/deletion/current-policy fences; replay/restart has one committed page effect and no usage/contact result
- Authority: actual two-tenant/viewer/current-source/cancel/deletion/expiry tests required; production modes refuse
- Isolation: actual unchanged network-none parser must execute the same parser/reducer; existing resource/OOM/network checks remain mandatory

See [runbook](../docs/35-offline-discovery-runbook.md). Independent exact-tree review and exact published-head CI are required before marking the scoped offline slice verified.

## Pre-publication review corrections

Independent snapshot review identified runtime row-lock privilege and exact-budget successor issues. A fixed-source authorized SECURITY DEFINER helper now returns only a permission/fence effect and locks current policy/head/catalog without runtime catalog UPDATE grants, including ordinary operator/source-less URL jobs. Nonexhausted exact article caps stop partial without scheduling another page; proven exhaustion at the exact cap can complete. Normal SQL/outbox and pure boundary regressions were added. Canonical lowercase UUID shape is now enforced in both event schema and runtime with negative tests. A narrowly translated dedicated SQLSTATE+exact-message policy fence preserves AuthorizationDenied after rollback; syntax/job/unknown errors propagate. Four pure classifications use the installed pg8000 driver exception shape.

## Corrected candidate validation

Focused45 passed/18 explicit unavailable-service skips. Normal aggregate468 passed/72 explicit service skips in29.46s; fresh-empty locked installation468 passed/72 explicit service skips in33.42s. Both passed all docs/contracts, Ruff lint/format, strict mypy88 files, inventory63 Python/159 JavaScript, frontend type/lint/one React test/build. All16 corrected runtime/test/migration/container files are byte-identical to the successful fresh copy. No dependencies or security/workflow settings changed. Independent corrected exact-tree review and required actual application540/no skips, actual SQL/RabbitMQ, network-none parser and existing controlled12/browser/docs CI remain pending. Acceptance is not inferred from skips.

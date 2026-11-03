# EM-015a — ScienceDirect parser prerequisite evidence

## Scope and base

October 15, 2026. New inert V2 search-request planning, DOI/PII identification, bounded JSON metadata parsing and pure pagination only. No live connector certification, extraction-service assembly, migration, credentials, new dependencies, deployment or merge.

Local starting commit `7e6a420e3d2e168fa6b6b985b960c7c59609e743` has tree `fd07d3f1bfa405699d2e6f0eee3d62022e6abb81`, identical to accepted Draft [PR21](https://github.com/APReddy-AutoBotz/EmailMonitor/pull/21) head `580967c8e09df7dcf12c592d39d2bf0330407dc4`. Publication must parent the actual remote head, not substitute local ancestry. The earlier scoped acceptance is recorded in PR21's final body; historical in-tree pending wording is not a new failure.

## Review corrections

Independent review identified the book-PII length, DOI-only alias deduplication and URL control-character normalization. Corrected to journal/book lengths 17/20, identifier-alias deduplication with explicit conflicts, and raw-text control refusal before URL parsing. A subsequent review caught cross-kind URL suffixes; DOI and ScienceDirect PII URL routes now retain their declared identifier kind. Added regression cases, nonfinite-float/provider-message refusals and per-article digest/locator preservation across pages. No source security boundary was relaxed.

## Checks

- Initial focused adapter suite after these corrections: 95 passed in 0.18s. Ruff and strict mypy for both new Python files passed.
- Private compatibility check against the public Elsevier documentation response: two parsed metadata rows with two/four ordered authors; both explicitly report contacts unavailable in search. The source sample remains outside Git. This was not a live API call, full-text read or contact extraction.
- Final focused suite: 98 passed in 0.19s; independent rerun 98 passed in 0.14s. Independent source/tests/documentation review found no remaining scoped blocker.
- Normal aggregate: `UV_CACHE_DIR=/tmp/emailmonitor-uv-cache scripts/check.sh` passed 1404 tests / 219 explicit service skips in 21.90s, plus 31 React tests, documentation/contracts, Ruff/format, strict mypy (196 files), inventory, peer checks, TypeScript/lint and frontend build.
- Fresh Python environment: locked `uv sync` into a previously absent `/tmp/emailmonitor-em015a-fresh`, then the same aggregate with `UV_PROJECT_ENVIRONMENT` set to that path passed 1404 / 219 skips in 22.52s plus 31 React/full checks. Frontend used the existing frozen-lockfile installation; this is not a fresh frontend installation claim.
- The first aggregate invocation stopped before checks because the default uv cache was not writable. Setting a task-owned temporary cache corrected this environment-only issue; no repository or security setting changed.
- Exact-head application, controlled transport, operator UI, browser, parser, documentation and packaging CI: pending; skipped local service tests do not establish these gates.

## Limits and next work

[Runbook46](../docs/46-sciencedirect-adapter-prerequisite.md) records capabilities and exclusions. Source policy and configuration continue to reject live execution. A reviewed isolated XML article/contact parser is an independent next implementation step; transport integration and actual rights/authentication/sample certification remain before any live pilot. EM-015 remains partial.

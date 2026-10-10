# EM-004a partial offline validation

Date: 2026-10-10. Base remote EM-003 head 0800137, tree 63efdc10. Earlier Draft PRs remain unmerged and unchanged. Only synthetic fixture bytes, policy records and identities are used.

Final local aggregate passed 159 Python tests without warnings/skips plus Ruff, strict mypy, docs/contracts/fixtures (13 negative contracts), unchanged 48 Python/159 JS inventory, frontend peers/type/lint/1 test/build. New tests: 67 URL/address/pinning-contract/fixture-limit/redirect/deadline/refusal cases and four actual PostgreSQL tenant/current-policy/revocation acquisition cases. Final documentation/full aggregate passed. Fresh clean-copy installation/from-empty migration and repeated upgrade also passed the complete aggregate with 159 Python tests and no warnings/skips. Fresh independent review and exact published-head CI remain pending before partial-slice acceptance. Full EM-004 acceptance remains unmet.

A single disposable bubblewrap isolation probe failed with `loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted`; that route stopped, with no escalation/retry/alternative route or host security change. Browser/live entrypoints are disabled. Actual DNS/TLS/socket connection, OS enforced egress, browser subresource interception/isolation, parser execution/resource isolation and real source authorization remain unmet. Scripted peer checks are not deployment enforcement. The task is explicitly PARTIAL, regardless of local test counts. See [runbook](../docs/28-offline-fetch-runbook.md).

No packages/license changes, new migration, production activation, contact extraction, email, AI, paid services or deployment. Normal CLI/UI retain honest metadata-only/unavailable extraction behavior.

# 33 — Shared network-free acquisition hop planner

EM-004e prepares the directly reusable planning core for the required generalized protected transport. It does not implement DNS, sockets, TLS, a firewall, browser execution or permission grants. Full EM-004 remains PARTIAL and EM-006 gated; live/default acquisition stays unavailable. The current synthetic implementation and actual evidence remain unchanged in Draft PR #8.

## Plan and stage contract

A frozen PlanScope binds organization UUID, source identifier, expected current policy version, operation, exact approved ASCII host set, one absolute monotonic deadline and platform-bounded redirect cap. A frozen HopPlan binds canonical HTTPS origin/path, the complete validated public A/AAAA snapshot, exactly one selected literal address, port 443 and bounded canonical redirect history. It rejects non-public/mixed/unsupported IPv6 snapshots, unknown selected peers, scope/field inconsistencies and private fixture exceptions. These are metadata and invariants, not signed or cached permission grants.

The future transport must use this sequence:

1. Compose scope from trusted server-authorized tenant/source context, never a browser or client-provided permission object. Supply an authorizer that checks organization/source/version/operation and URL against actual current server policy
2. Call authorize_url before actual DNS resolution; resolve the complete A/AAAA snapshot within remaining()
3. Call snapshot with the resulting records and selected literal; it validates the whole set and reauthorizes after DNS latency
4. Call before_connect immediately before an actual literal-address socket dial; read the actual socket peer and verify TLS CA/SNI/hostname in the transport. validate_peer only compares a supplied peer string with the selected address, so pure tests are not socket/certificate evidence
5. For redirects call redirect before fresh resolution, then redirected_snapshot after resolution. Preserve the old plan's history/scope/deadline; do not reuse earlier DNS answers or reconstruct a fresh deadline. Check before_release before releasing any body bytes

Each authorization stage rechecks the deadline before and after its callback. Default clock is monotonic; a fetch deadline cannot exceed the platform 60-second ceiling. Relative redirect locations are checked for ambiguity/control characters before URL joining; host, credentials, scheme, port and loop/cap restrictions remain fail-closed. Callback failure never triggers a fallback. Source credentials/tokens/response bytes are not stored in a plan. Plans and monotonic deadlines are process-local ephemeral transport metadata, not durable queue payloads or cached authorization.

The module is directly reusable by HTTP and browser mediation because both consume the same scope/URL/snapshot/selected-peer/deadline contract. No existing transport is wired to it in this preparatory slice. Callers remain responsible for the exact stage order and actual current-policy adapter; a plan itself never authorizes I/O. A future connector must stay behind the enforced transport boundary, not receive raw sockets or authority to construct its own plans.

## Evidence and limits

`test_fetch_plan.py` contains pure network-free invariants for full scope binding, immutability, public/mixed/IPv6 records, selected peer and port matching, malformed scope, shared deadline, callback freshness, tenant/source/version/operation mismatch, fresh redirect snapshots/history and URL refusal. One regression explicitly denies socket/name-service functions while exercising the planner. Scripted peer text and callbacks are deliberately labelled invariants, not actual DNS/TLS/current-tenant or security enforcement acceptance. See [validation](../reports/em004e-validation.md).

No dependencies, locks, migrations, runtime/API routes, workflow, guest/profile/container/network settings or source approvals change. Rollback removes the unused planner module/tests/docs. The next required step is actual protected transport plus a separately reviewed controlled synthetic acceptance network, with real literal IPv4/IPv6 peer/TLS and non-bypassable HTTP/browser evidence. That environment is not executed or enabled here. Real-source onboarding, PDF/contact extraction, deployment, release image certification and benchmarks retain their later roadmap gates; none is invented as a new EM-004 prerequisite.


## Verified checkpoint

Exact reviewed tree 536ec48e / Draft PR #9 head 5ee5712d passed application CI 38202490798 with 333 tests/no skips/no pytest warnings, docs 38202490797 and unchanged actual browser 38202490683/parser 38202490718 workflows. Exact merge tree and expected parents were verified. This accepts planning-only invariants; the new planner is unused by transport and actual generalized network acceptance remains unmet. See [full evidence](../reports/em004e-validation.md#verified-planning-only-checkpoint). Full EM-004 remains PARTIAL and EM-006 gated. No network configuration was performed, and no additional release/source/deployment prerequisites are inferred.

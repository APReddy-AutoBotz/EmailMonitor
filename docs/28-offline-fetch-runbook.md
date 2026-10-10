# 28 — EM-004a partial offline fetch boundary

Date: 2026-10-10. Stacked on reviewed/CI-verified Draft EM-003 head 0800137. EM-004a is a smaller offline slice of EM-004, not full protected network/sandbox delivery. No real source is approved, and no source networking or production activation occurs.

## Actual implementation

Strict HTTPS fixture URL classification rejects controls/whitespace/backslashes, credentials, query/fragment, nonstandard ports, unregistered host boundaries, numeric/address literals and ambiguous numeric hosts, trailing dots, Unicode/punycode source manifests, percent-encoded/dot-segment paths and excessive lengths. Only exact ASCII fixture hosts and declared paths are supported; this is not full internationalized-source/query canonicalization. Python's URL parser explicitly does not validate URLs, so application checks run before bytes are acquired. References: [Python URL security](https://docs.python.org/3.12/library/urllib.parse.html#url-parsing-security), [Python address classification](https://docs.python.org/3.12/library/ipaddress.html).

Public-address primitives validate every supplied record, reject empty/oversized sets and nonpublic/reserved/multicast/scoped/mapped/tunneled representations. ConnectionPlan describes validated address pinning and requires an approved peer and certificate-verification evidence. Its tests supply scripted records/peer values; there is no actual DNS resolver, TLS/socket transport or firewall. These primitives cannot certify rebinding resistance in deployment.

FixtureByteTransport is an explicitly test-only immutable response-map composition with no HTTP client, socket, DNS, environment proxy or fallback. The gateway classifies every redirect hop, checks current tenant policy, denies loops/more than five redirects, enforces at most 5 MiB HTML and one monotonic 60s observed deadline across hops/chunks, rejects unsupported media/compression and source denial statuses, and checks permission again before releasing bytes. No retries, credentials, cookie forwarding, browser script execution or fallback route exist. Query-bearing signed URLs, PDF responses and compressed payloads are unavailable rather than handled speculatively.

Tenant authorization uses the same current policy decision as the API and a server-derived source-acquire capability for owner/admin/steward/operator, matching the documented job-role matrix. Viewer/reviewer cannot acquire. Cross-tenant, stale current versions, pending/suspended/expired/revoked policy, disabled platform source and mismatched operation/path fail closed. A normal fixture fetch returns committed synthetic HTML bytes only; no contact extraction/result is inferred. There is no public fetch endpoint or new UI fake data.

Live and browser entrypoints always reject with safe unavailability reasons. Browser document/script/iframe/CSS/image/fetch/WebSocket/service-worker/popup/download cases are tested as unavailable. This is disabled functionality, not verified browser interception or isolation.

## Isolation probe and unmet gate

Read-only environment checks found bubblewrap 0.12.0 and Chromium 154.0.8037.57 with zero effective Linux capabilities. A single disposable probe was attempted:

`bwrap --unshare-user --unshare-net --die-with-parent --ro-bind / / --proc /proc --dev /dev -- /bin/true`

It failed: `bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted`. That route stopped, with no retry/escalation/alternate isolation route, host firewall/security change or capability grant. Chromium was not launched for source execution. No browser/network configuration was enabled.

Full EM-004 acceptance still needs an allowed environment with demonstrable network-level HTTP/browser denial, real connection-time enforcement/TLS tests, controlled DNS/rebinding/redirect/subresource/credential-forwarding evidence, and unprivileged resource-limited parser isolation. Browser interception alone cannot meet it. A loopback disposable PostgreSQL test database is separate identity/policy evidence, not proof of browser/egress restrictions.

Observed stream deadlines do not preempt a blocked trusted Python fixture iterator. Untrusted network/process deadlines, decompression/PDF limits, parser memory/CPU/PID isolation and provider/global throttles require later full controls. No live connector or parser is attached to this service. Bytes are unparsed: media-header checks are not complete MIME/signature validation or malware scanning. Future workers must reauthorize at actual execution and use generation/lease fencing; this current point-in-time fixture check is not an at-least-once job/quota implementation.

## Verification and next safe work

Run existing `scripts/check_tenant_foundation.sh` with three disposable PostgreSQL URLs. All previous migrations/checks remain included. New tests are test_fetch_safety.py (pure/scripted/fixture-only) and test_fixture_gateway_tenant.py (real synthetic PostgreSQL authorization). No new dependencies, migrations or production deployment. [Evidence](../reports/em004a-validation.md) lists actual results and remaining review/CI.

The task ledger remains PARTIAL for EM-004 irrespective of this slice's green CI. EM-005 can independently implement offline durable jobs on EM-002/003; it cannot execute source network work until full EM-004 and explicit source permissions exist. Network-dependent EM-006 and browser extraction remain gated. Never use a broader private-URL switch or another sandbox route to evade the denied operation.

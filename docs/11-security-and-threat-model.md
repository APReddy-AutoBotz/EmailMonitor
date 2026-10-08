# 11 — Security requirements and threat model

**Baseline:** 2026-10-08. This is an engineering threat model, not a security certification. Release requires tested controls and independent review appropriate to the deployment.

## Assets and boundaries

Assets: tenant identities, researcher/contact data, source credentials, evidence, exports, job state, billing units, signing/encryption keys, infrastructure and logs. Untrusted boundaries include user-supplied URLs, publisher content, PDFs/XML/HTML, browser scripts, queue payloads, exported spreadsheet cells and future model output.

Principal adversaries: a malicious tenant/user, a compromised source, hostile downloaded document, source impersonator/redirector, compromised worker/dependency, and overprivileged operator. Source HTML can contain instructions aimed at an AI; it never becomes application authority.

## Threat/control matrix

| Threat | Required control | Mandatory test |
|---|---|---|
| Cross-tenant IDOR/RLS bypass | Server membership, composite FKs, runtime non-owner roles, transaction-local RLS | Change tenant/resource IDs across all interfaces |
| SSRF into metadata/internal services | Central fetch policy plus enforced network egress | Loopback/private/link-local/IPv6/metadata/redirect/rebinding cases |
| Browser subrequest escape | Egress proxy/firewall, validated requests, no unrestricted WebSocket/service worker | JS fetch/popups/iframe/CSS/resource requests to denied networks |
| Credential theft via redirect | Do not forward Authorization/cookies across unapproved origins; scoped tokens | Cross-origin redirect with source token |
| Hostile PDF/XML/HTML | Sandboxed parsing, XXE disabled, resource caps, safe content display | Zip/decompression bomb, huge PDF, entities, script tags |
| Prompt injection / forged email | Extraction data cannot change policy or execute tools; evidence-bound output | Page tells model to ignore rules/send data elsewhere |
| SQL injection / malicious filtering | Parameterized queries, allowlisted fields/sorts, typed inputs | Filter and search payloads |
| XSS and unsafe evidence display | Escape text, safe external links, no inline raw-source rendering, CSP | Malicious author/title/excerpt/URL |
| CSV/XLSX formula injection | Serialize untrusted cells as text; neutralize formula prefixes incl. whitespace/control variants | =, +, -, @, tab/CR and HYPERLINK/DDE payloads |
| Resource exhaustion | Byte/page/time/concurrency/job caps and quotas | Slow streams, endless pagination, browser loops |
| Replay/duplicate effects | Outbox, idempotency keys, leases and unique effect keys | Duplicate deliveries and concurrent workers |
| Deleted data resurrection | Generation fences, tombstones, export invalidation, restore replay | Delete during fetch/parse/export and restore |
| Credential/log leakage | Secret references, redaction, least privilege, no PII payload telemetry | Structured log and error scanning |
| Malicious tenant connector code | Server-maintained registry; no arbitrary user code | Attempt code/selector-script injection through config |
| Dependency compromise | Lockfiles, SBOM, license/vulnerability checks, signed artifacts | Tampered artifact and unsupported dependency gate |

## Protected URL and egress boundary

Allow approved HTTP(S) source routes only; default HTTPS with HTTP only if explicitly reviewed. Reject userinfo, unusual schemes, unsafe ports, malformed IDNA, excessive URL lengths and ambiguous IP representations. Resolve all A/AAAA records and reject non-public destinations, including loopback, RFC1918, link-local, unique-local IPv6, multicast, reserved and cloud metadata endpoints. Do not trust DNS validation alone; enforce destination restrictions at connection/egress time to prevent rebinding. Revalidate every redirect and resource hop; cap redirects (default 5). OWASP describes SSRF defenses and allowlist pitfalls [S03].

An allowlisted public hostname resolving to a forbidden IP still fails. TLS certificate validation remains on. No proxy environment inheritance that permits a bypass. Browser workers have network-level denial of service networks and only approved external egress; application request interception is defense-in-depth, not the only control. Isolated parser workers have no outbound internet.

Development fixture traffic uses an explicit test-only transport or isolated fixture network. Do not introduce `ALLOW_PRIVATE_URLS=true` as a production environment switch. Production must refuse fixture-mode network exceptions at startup. Tests verify this refusal.

## Identity and sessions

OIDC authorization code flow, PKCE as applicable, state/nonce, exact registered redirect URIs, issuer/audience/expiry validation, secure HttpOnly cookies and CSRF. Session/member revocation must terminate API and stream access promptly. API tokens are hashed, scoped, expiring and revocable; display plaintext once. Never expose platform administration through a tenant role.

## Document and browser isolation

Unprivileged containers/processes; no Docker socket, host mounts or root; read-only filesystem except bounded temporary workspace; CPU/memory/PID/time restrictions; per-task cleanup. Disable external entity resolution and document scripting. Do not open documents in privileged interactive applications. Inspect MIME/signature and reject executables. Malware scanning for future manuscript attachments is separate from claiming an academic PDF is inherently safe.

## Data protection

Transport encryption, storage encryption and controlled key rotation. Evidence/contact PII is accessible only through tenant-authorized endpoints. Logs include IDs and safe reason codes, not emails, full names, raw pages, tokens or entire request bodies. Redact query parameters that may contain secrets. Export audit does not embed the contact list. Use narrow storage tokens and regional residency controls.

## Export safeguards

Neutralize formula cells before CSV/XLSX output; write string cell types, validate file names/headers, quote values correctly and sanitize archive paths. Recheck tenant, role, source export policy, suppression/deletion and artifact revision at generation and download. Do not bypass revocation with permanent signed URLs. Default exports are short-lived; remote deletion of downloaded copies is not promised.

## Supply chain and repository hygiene

The repository is public. Only synthetic examples and docs; no real contacts or customer credentials. Exact dependency versions, package/browser/container licenses, SBOM and vulnerability scans are release gates. Do not add an open-source license or change visibility without owner approval. Configure security reporting privately before customers use the product; do not invent a security email address.

## Release-blocking tests

All tenant-boundary tests, forbidden-destination tests, secret redaction, unsafe export strings, revoked-source behavior, queue replay, hostile PDF limits, deletion races and backup restore gates must pass. A successful extraction demo cannot waive them. Record severity, evidence, owner and expiry for any accepted residual risk.

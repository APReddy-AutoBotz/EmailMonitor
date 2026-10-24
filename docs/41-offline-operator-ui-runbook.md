# 41 — Synthetic operator UI runbook

## Bounded worker failure evidence (2026-10-15)

The default-off `ui_diagnostics` option now retains `last_failure` in every later cumulative snapshot. Only the exact registered execute task, application, owned routing key and pinned empty AMQP exchange can update it. Phase is `claim`, `process` or `other`, derived from the immediately preceding scoped stage; a later task resets that stage without erasing the last failure. The failure receiver maps the actual Celery signal exception by exact type identity to `FetchDenied`, `IsolationUnavailable`, seven common built-in classes or `other`. Celery may replace non-pickleable exceptions; wrappers remain `other`, without inspecting their stored original name or arguments.

Only an exact `FetchDenied` with one exact-string argument can emit one of six fixed reasons: `source_entitlement_denied`, `source_policy_denied`, `source_resource_scope_denied`, `source_admission_deadline`, `source_response_denied`, `total_deadline_exceeded`. All other reasons are `other`. No raw names, exception text, traceback, arguments, IDs, URLs, payloads or worker logs are published. Classification/writer errors cannot change task behavior.

The existing 512-snapshot, 1024-byte record and 65536-byte owned-tail limits remain. The strict parser requires the closed metadata field, rejects extra/unknown/inconsistent fields and rejects metadata changing on nonfailure records. Old records lacking the field are invalid evidence, never zero failures. Saturation, absent evidence and truncated tails remain explicit; a retained failure is not proof of a broker ACK, job identity or root cause. No timer, resource, queue, ACK, source policy, SQL fence or completion deadline changes are made. Actual own-head UI and all seven gates remain required; a later successful UI run without recurrence does not identify the earlier cause. [Failure history and verification](../reports/em015f-validation.md).

## Synthetic solo-worker callback wake candidate (2026-10-15)

The existing fixture worker now registers a consumer bootstep for its exact solo pool with an asynchronous hub, independently of diagnostic logging. Pinned Celery 5.6.3/Kombu 5.6.2/amqp 5.4.1 can run a buffered transport-reader callback from the hub's ready snapshot, execute a synchronous task, enqueue its original late-acknowledgement promise, then enter a poll of up to 10 seconds before revisiting the new ready queue. A real-worker/no-broker regression reproduces this mechanism; task postrun and `Request.acknowledged` become true while the actual `Message` remains unacknowledged and the synthetic channel has received zero `basic_ack` calls. It does not establish that a historical CI failure took this exact branch.

`jobs/callback_wake.py` observes only whether the pinned hub's private `_ready` set is nonempty under its `_ready_lock`, on the same event-loop thread after the snapshot. It coalesces one byte in a nonblocking close-on-exec pipe so the existing poll returns; the normal next iteration executes the original callbacks. It never executes, copies, replaces or reorders ACK promises, changes the poll timeout, adds a timer/thread/socket, or inspects task content. Exactly two owned descriptors fit within existing resource limits; no limits or system settings change. This is not a cross-thread scheduling guarantee. Dependency upgrades must revalidate the pinned private-field and actual worker regression.

Installation is idempotent per hub. Consumer stop/shutdown/terminate removes the reader/hooks and closes both descriptors; hub close/reset closes them without touching its already-closed poller or mutating the set of close callbacks during iteration. One inert close hook remains only until explicit cleanup or next installation. Reconnect installs a fresh pair after safely removing that hook. Registration/I/O errors clean up and propagate rather than silently pretending to wake; an uncertain descriptor close is never retried. Missing-hub and other-pool paths remain untouched.

The existing 8-second UI completion gate, readiness, AMQP heartbeat 120/checkrate 3, timer max interval 10, late ACK/reject settings, prefetch 1, queue/routing/source/tenant controls and all isolation profiles remain unchanged. Pure tests cover actual factory/Worker/handler/strategy/registered task/solo execution with diagnostics off/on, success/empty/claim-error/process-error, the original 10-second failed progress mechanism, corrected real poll wake, lifecycle/reconnect/partial installation/error paths and descriptor bounds. Actual RabbitMQ/UI and all seven own-head gates are still required. [Validation and preserved failure history](../reports/worker-callback-wake-validation.md).

## Scope and dependency

EM-012 connects the actual React application to existing tenant-authorized APIs for document-03 screens: dashboard, keyword/URL wizard, jobs, contacts, review queue/evidence, exports, source policies, usage, audit and organization settings. Its declared synthetic/offline foundation is VERIFIED IN DRAFT after independent source/evidence review and all six actual exact-head CI gates at head6a3c607c/treea513d96c. No deployed or live-source product is claimed.

The EM-011 documentation checkpoint passed its own five gates at head9fd9fbeb/treeee54a2b3 and mergeed535748 (parentsfe66f7a7/9fd9fbeb). Its application1035/no-skip and controlled12 plus browser/parser/docs evidence is recorded in the [EM-012 report](../reports/em012-validation.md). All dependencies remain Draft/unmerged.

## Session and tenant authority

The UI loads `/api/v1/auth/session` with the fixed `X-EmailMonitor-UI: session` header and same-origin cookies. The synthetic callback sets an additional Secure, HttpOnly, host-scoped, SameSite=Strict CSRF cookie. Session reload returns the nonce only after checking its hash against the existing current session. Logout clears both cookies. No authentication grant, provider, identity credential or token storage is added. The diagnostic uses actual preauthenticated synthetic cookies; it does not prove a real IdP/browser callback integration.

Role/capability metadata controls visibility only. Every read, mutation, review, job control and download retains current server authority and forced RLS. A changed organization destroys the old request scope, cancels in-flight reads/SSE, unmounts drawers and clears filters/cursors/plans/preview/notices. Late responses and replay frames cannot repopulate the new tenant. Session state is memory-only; there is no shared client result cache or persistent contact store.

API paths, payloads, response sizes, safe identifiers and SSE frames are bounded. Fetch uses same-origin credentials, no-store and redirect refusal; a closed scope refuses late headers/body and event callbacks. Stale retained views after network failure are visibly labeled; denied/unknown resources clear prior content. Mutations use current nonce, server revisions and stable per-payload idempotency keys where supported. Native dialogs identify the active organization and destructive impact.

## Supported screens and truthful limits

- Wizard supports the documented synthetic keyword and six reviewed HTML fixture routes. The server classifies/authorizes before launch. Infraction→Infarction correction is explicit. PDF/DOI input acquisition, unsupported filters, arbitrary websites and static browser-unavailable work remain visibly unavailable.
- Jobs show durable server snapshots and separate discovered/terminal/outcome counts. Progress percentages concern already discovered work; unknown enumeration and partial processing do not imply completeness. Pause/resume/cancel/continuation remain current revision/generation fenced. Real SSE invalidates snapshots rather than incrementing counters in the browser. Each validated current-scope frame checkpoints its opaque cursor immediately, so a later timeout/disconnect reconnects after the last received frame; invalid/late frames never advance it.
- Contacts and outcomes are separate bounded paginated datasets. Accepted associations are the default. First/corresponding roles, unresolved identity, syntax, mailbox status and outreach eligibility remain separate. Publication date is explicitly unobserved when unavailable; observed timestamps are not substituted for it.
- Evidence shows actual retained excerpts, digest, parser/route, ordered authors, candidates and HTML or coarse PDF locators. Reviews require observed authors/citations/reason/current revision. Conflicts remain visible with an inside-drawer refresh. Attaching arbitrary sources, suppression/deletion and obsolete-data workflows are not implemented here.
- Exports use a server-authorized preview, not page-derived totals. Accepted-only defaults, current source/purpose and immutable private async artifacts remain. Only affiliations/article_title may be omitted; mandatory observed roles, address, evidence/source and independent use states remain. Preview counts may change, and denied/suppressed counts are never disclosed. CSV refusal and literal XLSX rules remain unchanged.
- Source screens expose actual catalog/version history and existing owner/steward synthetic review/approve/suspend/reactivate/revoke actions. A permission reference is fixture-only metadata, never a real approval or credential.
- Usage separates current retained extraction effects from the existing fixture-probe quota ledger. An uninitialized ledger is labeled; cost/billing/worker-time and commercial entitlements remain unknown.
- Audit is owner/admin-only under existing authority; steward/own-event support is visibly unavailable. Settings reuse owner-only profile UPDATE and existing registered membership/owner-transfer rules. No invitations, new identity accounts, region/security settings, billing, provider configuration or lifecycle purge are added.

## Migration and development

Migration0009 follows0008 and adds bounded export-preview/optional-field validation while preserving existing export fences, private snapshots, rendering/outbox and legacy default field selection. Its validator has no PUBLIC/runtime/authenticator execute grant; the preview helper checks existing export capability/current policy. No table ownership, RLS role or authentication connection expansion is added. Downgrade is refused; use the repository forward-migration/recovery policy.

Run `UV_CACHE_DIR=/tmp/em-uv-cache PNPM_HOME=/tmp/em-pnpm bash scripts/check.sh` for locked install, docs/contracts, lint/format, strict types, safe tests, license inventory and frontend build. Service skips are not acceptance. The operator requires an already configured same-origin synthetic backend/session; no manual local service, browser or production setup is claimed by this candidate.

## Actual keyboard CI boundary

`operator-ui.yml` uses the same pinned disposable PostgreSQL/RabbitMQ tools and immutable official Playwright image. It builds actual locked frontend assets, starts a real unique broker worker and exercises the real FastAPI application with tenant runtime/authentication connections. The guest has the unchanged approved browser profile, nonroot UID1000, zero added capabilities, read-only root, bounded tmpfs/resources, network-none, no host mounts/published ports/secrets and Chromium's own sandbox enabled. No listener, bridge, forwarding initialization or host security setting is introduced by this workflow.

Only bounded fixed same-origin API requests travel over owned multiplexed pipes to the actual ASGI application. Actual cookies enter ephemeral bootstrap, not image/environment/repository. Asset hashes and a strict built-file allowlist are checked before build and again in the guest. External requests/websockets/workers are denied. Unique labels/immutable image IDs constrain cleanup; unknown ownership refuses removal. Responses/logging/output/concurrency/deadlines are bounded. Fixed allowlisted stage labels and exception-class/numeric-status failure frames reveal an interrupted guest before owned stdin executor cleanup; they cannot carry arbitrary request/cookie/body text or relax the unchanged180-second conversation/acceptance gates.

The diagnostic uses keyboard Tab/Enter/typing/select navigation, actual source approval and keyword/URL plans, real outbox publication/worker completion, partial/no-contact/empty/error states, evidence review, optional-field preview invalidation and actual export bytes. Pause/resume plus dismissed cancellation are checked against durable events; an Escape-closed drawer restores focus. Usage/audit/settings are actual reads. One controlled network-abort is an explicit test fault, not fabricated backend data. Held actual contact responses and old SSE replay bodies are released after organization switch and must remain absent.

Playwright route fulfillment buffers genuine ASGI SSE frames with a bounded diagnostic disconnect; this proves real replay/reconnect and tenant cancellation, not native stream latency or an uninterrupted sixty-second browser connection. A real Blob download is observed and cancelled under `accept_downloads=False`; the trusted host verifies actual authorized artifact bytes/digest. A saved filesystem download is not claimed. Preexisting service-level tests remain required for optimistic conflicts and lifecycle races.

Acceptance requires application tests with no service skips, controlled transport12, standalone browser, parser, documentation and the new actual operator-UI job at the exact reviewed published tree. Source/pure checks or a passing smoke screen cannot replace these six gates. EM-013 remains gated on this reviewed acceptance documentation checkpoint passing its own six exact-head gates.


Independent authoritative reconciliation confirmed application1132/no skips/one alias-body warning284.57s, keyboard UI1/64.12s and controlled12/56.92s plus actual browser/parser/docs. The keyboard result includes the unchanged affirmative Chromium sandbox/lo-only/IPv4+IPv6 errno101 controls, native Escape focus restoration, real current-authorized4471-byte export and delayed old-tenant response/replay refusal. [Validation](../reports/em012-validation.md) records exact IDs, review corrections and scope limits. All branches remain Draft/unmerged; EM-WARN-01 cause remains open.

The owned operator fixture can temporarily instrument the exact reviewed
`network_entitlement_allowed` body with fixed client notices distinguishing
ordinary denial from caught lock refusal. All predicates, locks and return values
remain unchanged. Installation verifies the original body, function configuration
and server notice-logging threshold; teardown verifies restoration of the exact
definition, ownership and privileges and refuses to overwrite unexpected changes.
Only the existing opt-in synthetic worker observes these notices. It consumes no
query results, executes no additional SQL, and emits bounded allowlisted reason
codes only. Missing, ambiguous, malformed or truncated observations cannot be
complete diagnostic evidence. No migration or production activation is added.

The actual observation-dialog content and initial Close-button focus assertions
have separate fixed outcome checkpoints. Their assertions, selectors and timeouts
are unchanged; the labels identify which existing condition failed without
printing dialog contents or identifiers.

The held-response organization-switch journey separates Next-page navigation,
switch-away, switch-back and job-reopen checkpoints. On keyboard traversal
exhaustion only, a closed diagnostic reports target/document focus, whether a
dialog is open, and a fixed active-element category. It never emits DOM text,
values or identifiers. Missing, invalid or over-100ms snapshots report unavailable. The
original 100-Tab failure, assertions and overall deadline remain unchanged,
including when the final Tab reaches the target.

Controlled browser evidence review records fixed action checkpoints for opening
Contacts, opening evidence, waiting for citation content, entering a reason,
saving, waiting for closure and returning to Contacts. Failure snapshots also
report fixed control kinds, disabled/inert/tab-stop flags, and whether the target
and active control belong to the same open dialog. These observations do not
change focus or prove the preceding event history; no labels or values are emitted.

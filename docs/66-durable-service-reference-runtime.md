# 66 — Durable service reference runtime

Status: code-only EM-017 candidate; acceptance in progress. See
[ADR 0006](adr/0006-durable-service-authority.md). No deployment or live service
identity is created by this change.

## Packaged process boundary

The deterministic service artifact contains the full application, built static
web client, migration inputs, locked backend dependencies and an explicit authored
HTML corpus. `scripts/packaging/service_artifacts.py` collects it and verifies the
archive against a separately retained canonical manifest. Backend source paths and
bytes must match the reported Git tree, including rejection of ignored additions.
The manifest is a build
receipt, not a signature or an independent source of trust. The service Dockerfile
runs as UID 65532 and never mounts a Docker socket or runs migrations at startup.

Installed commands use `python -m emailmonitor.runtime.entrypoint`:

- `api --config FILE`: owns the human runtime/authenticator pools and the loopback
  HTTPS listener, serves static web and `/auth/complete`, and requires explicit
  existing tenant worker/publisher bindings. Its test-only PKCE exchange accepts
  fixed loopback TLS endpoints and pinned RSA public verification keys. Supplied
  certificates are verified; redirects, proxies and automatic retries are absent.
- `worker --config FILE`: owns a separate service-login pool and a solo, concurrency
  one Celery application. Fatal worker termination returns failure to its supervisor, and shutdown quiesces
  the owned controller before disposing the pool. The tenant queue is exactly `em-fixture-<tenant UUID hex>`.
  Identifier-only execution/export events resolve fresh SQL authority. An owned
  five-second timer reconciles current work and is cancelled on consumer shutdown.
- `publish-once --config FILE`: one finite confirmed-publish pass with a separate
  publisher login. It holds exact publication fences through broker confirmation
  and receipt commit. Crash between those operations can duplicate delivery; it
  cannot guarantee exactly-once publication.
- `reconcile-once --config FILE`: one bounded worker reconciliation pass.
- `check --config FILE`: verifies service database identity, tenant and schema. It
  does not prove broker availability or complete operator readiness.

Configuration is explicit and size-bounded. It is never embedded in the package
or printed by the CLI. Only the closed `test` environment and existing loopback
reference database/broker profile are supported. Production configuration fails
closed. API `/readyz` checks both SQL roles, exact schema and active registered
bindings; it does not assert that a publisher or worker process is alive.
`/api/v1/runtime-profile` describes the authored HTML-only service profile. XML,
PDF, dynamic browser and live-source dispatch are unavailable in this profile;
existing independently isolated implementations are not silently substituted.

## Authority and operational bounds

A current human start or separate export request issues exact worker and publisher
resource grants in the same transaction. Existing idempotent/terminal requests do
not acquire new grants. Resume follows the new generation under the original wall
deadline. Historical work is never enrolled automatically. The default ceiling
21,600 seconds is a conservative configurable implementation value, not an SLA.

Natural browser-session expiry does not revoke already bounded machine work.
Explicit logout, missing/revoked origin session, principal or membership changes,
source-policy changes and expiry still fail closed before consequential work or
commit. Service principals cannot mint sessions, use copied human session hashes,
review evidence, approve policies, perform lifecycle deletion or download exports.
Export authority does not grant direct access to unrelated contact tables.

Worker leases are at most 120 seconds. SQL transactions have five-second statement
and two-second lock limits; service export claim additionally enforces its own
maximum two-second contention wait even for direct RPC calls. Human NOWAIT behavior
is unchanged. Reconciler/publisher enumeration is capped at 100 identifiers with a
two-second statement limit. Passes stop *between* resources after ten seconds and
retain a cursor where applicable; this is not a hard ten-second whole-pass SLA.
Individual database/socket/broker operations have their own finite limits.

## Installation, upgrade and restore

Migration 0014 follows populated 0013 and creates empty authority tables and
NOLOGIN group roles. A separate migration identity applies it explicitly. Actual
service LOGIN roles, secrets, registration, tenant bindings and source approvals
are external activation work requiring their own authorization. The reference
acceptance harness uses only uniquely owned disposable synthetic roles and data.
Neither API nor worker startup creates or expands access.

The runtime accepts exactly schema version `0014_service_authority`; a future
migration requires an explicitly reviewed compatible runtime change. Role ACLs
must preserve non-owner/non-BYPASSRLS separation, deny opposite service roles and
authenticator/session-minting access, and retain forced RLS. Do not weaken these
checks to accommodate a deployment shortcut.

Legacy restore refuses any service principal, delegation or service audit state
with `restore_service_authority_unsupported`. A new revocation-aware restore seal
is required before this state can be backed up/restored through that profile.
Do not restore an older database as a way to revive revoked work. Downgrade is
intentionally refused; stop admission and apply a compatible forward repair.

## Evidence and remaining acceptance

The focused local gate currently passes installed artifact import/CLI/fixture
closure, authority models and actual local TLS exchange boundary tests. SQL,
broker, migration and packaged keyboard operator tests must execute against the
explicit disposable CI services; a local skip is not acceptance. Full normal,
fresh-environment and exact-head independent review/CI remain release gates.

The container acceptance keeps the 128 MiB network-none profile. Its integrity
probe and actual CLI checks execute sequentially rather than retaining two full
application interpreters concurrently. The five production-command refusals keep
their five-second bounds and share the former probe's 45-second budget. Receipt
claims require exact output, stopped/non-OOM state and verified owned cleanup.

The installed browser acceptance uses a constrained relay because the guest has
no network access. Pinned Playwright does not route redirected requests through
its request handler. The harness therefore observes each real server 303 and its
browser refusal at the approved target, then permits one explicit navigation to
that same target. Exactly two ordered hops per login and two logins are allowed;
real response cookies, PKCE exchange, state validation and callback UI remain in
use. A successful receipt covers the installed flow through that relay, not native
Chromium redirect completion or a production IdP integration. Dynamic authorization codes,
state and cookies are never included in the fixed acceptance receipt.

Traceability: FR-001/021/022/024/025/029/030, NFR-001/003/006/008/013/015/016/018.
This reference milestone does not establish production deployment, real IdP or
source certification, private storage activation, measured RPO/RTO or extraction
accuracy/completeness.

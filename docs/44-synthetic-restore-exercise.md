# 44 — EM-017a disposable synthetic backup/restore exercise

## Boundary and dependency

This is a partial EM-017 slice under documents13/16/21, after independently verified EM-013/014. It tests a real same-version PostgreSQL custom dump and restore using the existing pinned disposable PostgreSQL17.11 CI service and its bundled tools. It does not deploy hosted/dedicated infrastructure, configure a real identity provider, create persistent external access, collect publisher data or claim production recovery targets. EM-015/016 still require concrete source permissions and authorized samples.

The exercise is trusted test support in `tests/restore_exercise.py`, not an application endpoint, customer restore script or upload interface. Only the exact synthetic CI URLs/marker and64-hex service container are allowed. The configured image must equal the existing immutable digest. Server, pg_dump and pg_restore must all be17.11. PostgreSQL's [dump documentation](https://www.postgresql.org/docs/17/app-pgdump.html) explains consistent single-database archives and excludes global roles; this exercise deliberately reuses the same already-created synthetic role set. [Restore documentation](https://www.postgresql.org/docs/17/app-pgrestore.html) supports the custom archive and single-transaction/exit-on-error mode. Existing object ownership, ACLs, triggers and forced RLS are preserved. No no-owner/no-acl/disable-trigger option is used. PostgreSQL's bundled tools have its existing permissive [PostgreSQL license](https://www.postgresql.org/about/licence/); there is no new package dependency.

## Supported stale-backup window

Two authored fixture tenants and every protected job/policy/accounting anchor exist before the backup. No fixture worker, parser/export lease or source admission remains active. A consistent private capture records the baseline. Post-backup changes in this supported profile are existing-job privacy tombstones/purge/suppression, recorded retention deadlines and a guarded revocation of an already-backed-up policy version.

The coordinator refuses an unrepresented job, new policy version, changed identity/session/membership/support/configuration/catalog/shared control or changed settled accounting. Bounded per-job row digests also refuse unsupported discovery/execution/association-review history for jobs without current tombstones. Organization-wide content tombstones are explicitly unsupported and refuse before replay; this profile does not merge their generated child marker histories. These refusals deliberately quarantine an unsupported restore instead of lowering current authority or inventing missing FK anchors. This is not general point-in-time recovery or a merger of arbitrary post-backup business transactions. The authority capture is limited to the two designated synthetic tenants; the test database may contain other authored test fixtures, but no serving deployment or generic tenant onboarding is enabled.

## Ordering and readiness

1. Capture baseline state and a private mode0600 custom archive, with database/archive64MiB caps and a90s per-tool bound. Keep it within the owned disposable directory; record only a digest, never private keys, session digests, content or raw tool errors.
2. Capture current authority after the supported privacy changes in one repeatable-read transaction. Stored tenant keys and suppression digests stay paired; missing markers and later deadlines refuse. No raw suppressed address is recovered from a digest.
3. Create a uniquely named, ownership-marked target database from template0 with CONNECTION LIMIT0, atomically denying the non-superuser fixture roles. Revoke its PUBLIC/runtime/authenticator CONNECT before restoring. Start no application or worker. Restore only the digest-verified owned archive with preserved schema/RLS/ACLs.
4. Replay current privacy keys/suppressions and recorded deadlines while closed. Replay deletion intents through the existing lifecycle stage/purge functions against stale content before treating markers as purged. Copying a purged marker onto stale bytes would incorrectly make purge return early and is not done.
5. Apply same-version source revocation through its existing guarded transition. Compare protected jobs, export metadata, accounting and current policy/privacy state with the captured authority. Unsupported drift fails the transaction. Recheck the source authority and target seal before granting the two existing synthetic logins CONNECT and removing the temporary connection limit.
6. Repeat only the identical validated replay while closed as a no-op after checking the target seal. A changed replay/target or premature application URL refuses. Runtime access starts only after validation; all usual current-session/RLS/policy/lease/privacy predicates remain authoritative.
7. Reconstruct identifier-only fixture work from the restored durable ledger into a new owned RabbitMQ queue. No broker snapshot is imported. Require one business usage effect after at least two actual receipts of the same published event.
8. Stop owned workers/connections, drop only the exact ownership-marked disposable target and delete the private archive. Unknown ownership refuses cleanup; no broad database deletion/pruning or host setting change occurs.

## Required actual evidence

`test_restore_tenant.py` must execute in application CI with EM_REQUIRE_SYNTHETIC_RESTORE=true and the already-owned PostgreSQL container ID. It requires actual dump/restore, closed CONNECT checks, coherent current suppression/tombstone/source replay, physical stale-content removal, direct restored-runtime contextless/forged-scope/cross-tenant SQL refusal with forced-RLS/ownership checks, denied old artifact download, exact unaffected artifact hash, conserved job/usage state and actual broker work reconstruction. Pure `test_restore_contracts.py` tests refusal/state/grammar and archive integrity; they do not supply database or recovery evidence. Other controlled/browser/parser/UI gates remain mandatory and unchanged.

Record `exercise_seconds` for this disposable exercise only. `production_rpo_rto_measured` remains false. Actual encrypted backup/object manifests, independent regional infrastructure, real OIDC/secrets, operating access, staging deployments, backup expiry and measured production/staging RPO/RTO are remaining EM-017 work. Restoration of newer policy/authentication/business histories is outside this partial profile. Production/live execution remains unavailable.

## Separate populated-service candidate

This legacy profile continues to refuse populated service authority. The separate
[closed service seal](67-closed-service-authority-restore.md) tests monotonic service
revocation and current audit/role/schema/export state in a target that never opens.
It does not relax this profile or provide a general service restore command.

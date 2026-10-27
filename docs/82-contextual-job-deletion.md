# Selected-job deletion staging

FR-029 / EM-014 / EM-012: connect the existing owner-only staged deletion API to
the current extraction-job workspace. This is a selected-job operation, not an
organization-wide deletion or physical-purge interface. No migration, grant,
retention policy, source permission or backend lifecycle transition changes.

The owner chooses privacy request or owner request, reviews a confirmation naming
the exact job, and explicitly confirms. The confirmation discloses the existing
organization-wide export invalidation effect. It distinguishes staging from
cancellation, physical purge and backup tombstone replay. Automated retention
expiry is not offered as a user-selected reason.

Before submission, reread the exact job and require unchanged revision,
generation, state and kind plus current scope/capability. The API remains the
authority at commit. Send only the selected non-null job UUID and explicit reason;
never broaden to the API's organization-wide null target. After submission, accept
only a receipt bound to the current organization and job. Preserve the server's
existing receipt reason/stage on replay. Unknown receipts or transport failures
must not cause automatic retries. Receipt, reason and attempted-request state are
owned by the current scope and job and cannot survive a scope switch.

The existing server fences work and retained reads, invalidates current exports
throughout the organization, clears the job request and retains a durable
tombstone. Physical purge and backup replay remain separate supported operations;
this screen invokes neither. A verified fenced receipt remains visible when the
job read becomes unavailable. No claim that all stored content or backups have
already been erased is made.

Acceptance: frontend confirmation/cancel, stale state, role/capability refusal,
receipt binding, duplicate submission, scope closure and uncertain outcomes;
actual SQL API replay and retained-content-without-purge proof; existing lifecycle
tenant/CSRF/fence tests; a genuine hosted keyboard journey stages the existing
no-contact job after prior retained/export/suppression proof, cancels first, then
confirms. Host SQL requires its exact tombstone, fenced reads and retained source
content. Prior assertions remain mandatory. Authored/skipped tests are not
executed acceptance. Local and hosted results must be reported separately.

This dependent Draft preserves PR60 and its historical XML/assembly failure
uncertainty. No live acquisition, new credentials, purge, merge or deployment is
part of this implementation.

The first hosted run passed the selected-job keyboard and SQL assertions but
failed the separate installed XML journey during export preview. Future failure
metadata includes the existing validated export subphase and CSV/XLSX category,
retaining the first failed case. It includes no arbitrary text or payloads and
does not change execution, deadlines or exit propagation. A phase identifies
where evidence is needed; it does not establish a root cause.

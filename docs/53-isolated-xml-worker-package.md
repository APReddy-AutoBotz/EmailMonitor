# 53 — EM-017c isolated XML worker packaging

## Boundary

This partial EM-017 slice packages the existing `emailmonitor.parsing.xml_worker` command independently of the fixture-rich parser diagnostic image. It prepares a worker artifact under [deployment requirements](13-deployment-and-operations.md) and [packaging prerequisites](45-offline-packaging-prerequisite.md). It does not assemble or activate a production extraction service. The worker remains synthetic-test-only, with its existing XML protocol, kernel checks and refusal behavior unchanged.

The explicit source closure includes shared observation, retention and authorization helper code, including synthetic helper modules. “Fixture assets absent” means no embedded repository HTML/XML/PDF fixtures, repository test files, customer samples or credentials; it does not mean all fixture-related Python helpers are absent. No runtime-model refactor is needed solely to obtain a smaller artifact. Existing third-party wheels remain intact and may contain their own testing/support modules; absence of every test-related file throughout all dependency layers is not claimed.

## Build and evidence boundary

The separate allowlisted context uses the existing immutable Python base, locked no-dev dependencies and notices. Source file hashes and the exact Git tree identify the candidate. The final image contains the explicit reviewed import closure and runtime dependencies, rather than the whole repository. No fixture assets enter either build stage. The existing metadata image and its acceptance remain unchanged.

The existing read-only-token packaging workflow additionally builds the XML image twice without cache, compares defined application/dependency content digests, and runs disposable network-none probes. Image IDs are recorded separately; OCI timestamp/config bit reproducibility is not claimed. No registry upload, deployment, persistent service, credentials or migration is involved.

Actual acceptance requires host-supplied synthetic input through stdin to the unchanged worker command, verified observation/digest/identifier/profile output, bounded malformed/hostile-input refusal and missing activation-marker refusal. Inputs do not become image layers. Read-only probes verify the explicit source/dependency inventory and actual kernel/network restrictions. The owned containers use the existing XML channel profile: uid/gid65532, no capabilities, no-new-privileges, default seccomp, read-only root, network none, bounded memory/CPU/pids/files/tmpfs and no host mounts or ports. Unknown ownership or cleanup failures refuse acceptance.

## Verification and remaining gates

Pure package/protocol tests, normal and genuinely new-empty-Python aggregates, independent immutable-tree review and all seven actual own-head workflows are required. Local Docker absence or explicit service skips cannot establish packaged-worker execution. [Validation](../reports/em017c-validation.md) records observed results and limitations.

The existing application still selects its diagnostic parser image. This slice does not reconfigure application execution or replace accepted parser/browser/topology controls. Future runtime integration must separately validate immutable artifact selection and current tenant/source boundaries. Real IdP/runtime configuration, broker and HTTP/browser/export worker packaging, private regional storage/secrets, staging, signed release provenance, source rights/samples and measured production recovery remain unmet. The real-source EM-015/016 gate is unchanged. Rollback removes this additive package and acceptance step; no durable data or deployed service changes.

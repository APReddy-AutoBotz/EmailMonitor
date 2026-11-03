# 55 — EM-017e observed packaged-base inventory

## Scope

This partial [deployment prerequisite](13-deployment-and-operations.md) records observed base-system metadata for the existing metadata and curated XML images. It advances the system-attribution evidence explicitly left open by [packaging](45-offline-packaging-prerequisite.md) and [ADR-0005](adr/0005-ai-and-dependency-licensing.md). It does not change the immutable base, runtime source, dependencies, Dockerfiles, tenant/source policy or isolation. Playwright, PostgreSQL and RabbitMQ images are outside this slice.

The inventory is not a complete SPDX/CycloneDX SBOM, whole-filesystem attribution, signed attestation, license clearance or vulnerability clearance. No scanner, advisory service, package update, registry publication or deployment is introduced. Missing attribution remains missing; an installed package name does not establish its license or commercial suitability.

## Observed facts and declared provenance

A shared standard-library collector reads only bounded fixed image paths: distro identity, the installed Debian package database, package-derived copyright references, upstream Python identity and explicitly bounded bundled-distribution metadata outside the active application virtual environment. It emits sorted versioned records and hashes, never file contents. Missing legal metadata is explicit. Unsafe paths/symlinks, nonregular files, duplicate or malformed records, unsupported platforms and input/output overflow refuse the entire report rather than silently truncate it.

The host independently validates the complete report schema and recomputes its canonical hash. The deterministic inventory excludes variable image IDs and Git trees. Host receipts bind it to the inspected image ID, declared pinned base/platform, exact source tree and existing application-content digest. The base reference is declared build provenance, not a cryptographic signature or independent supply-chain attestation. Untracked libraries and other filesystem content remain outside this bounded inventory.

## Same-container acceptance

Trusted host composition prefixes the fixed collector source to the fixed metadata/XML probe. No downloaded code, plugin selector or arbitrary source path is accepted. The collector is not copied into either build context or image layer. Each existing probe collects inventory after its current source/kernel/network checks and emits one strict JSON result within the existing output ceiling. The XML integration wrapper uses the same composition and validation path.

Both independently uncached builds of each artifact must yield equal full canonical inventories and hashes. Existing archive/application-content comparisons, actual metadata refusals, all fourteen XML worker cases, immutable-ID/profile checks, owned cleanup, tenant boundaries and operator/export proofs remain required. No additional container or lifecycle path is created.

## Evidence and remaining work

[Validation](../reports/em017e-validation.md) distinguishes fixture-based parser tests from actual installed-image observations. Normal and genuinely new-empty Python aggregates, independent exact-tree review and all seven actual own-head workflows are required. Cross-check the integration consumers' inventory against the same-head XML packaging results, alongside existing artifact hashes and actual parser IDs.

Full runtime/identity/storage assembly, source rights and authorized samples, staging, measured operational recovery, whole-image security/attribution review and release decisions remain open. This engineering evidence does not activate production. Rollback removes only the additional CI inventory evidence; no migration or deployed state is changed.

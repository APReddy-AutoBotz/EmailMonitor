# 54 — EM-017d curated XML artifact integration

## Bounded purpose

This partial EM-017 slice connects the [reviewed synthetic XML package](53-isolated-xml-worker-package.md) to the existing controlled application and operator acceptance. It replaces fixture-rich diagnostic-image preparation in those two CI jobs, without changing application source, XML protocol, tenant/source authorization, queue execution or isolation. The separate parser diagnostic workflow retains its HTML/PDF/XML fixtures and hostile/OOM checks. No PDF worker interface is introduced.

## Trusted preparation and consumption

A CI-only wrapper accepts only fixed application or transport modes. It verifies the clean source tree, locked runtime closure and canonical curated artifact, builds one owned image and runs the existing read-only source/kernel/network probe. The separate packaging gate still requires two independently uncached builds and all fourteen worker cases; one consumer build does not replace that reproducibility proof.

The existing parser image alias is bound only after verification. A pre-existing alias refuses integration rather than being overwritten. The application keeps its existing command and resolves the alias to an immutable image ID, verifies every container uses that ID and applies the unchanged network-none profile. Host-only expected identity and unique owner values are checked against actual container metadata by existing application, controlled provider and normal-operator acceptance callbacks. These proof variables never enter worker environments. Existing profile counts, success predicates and deadlines remain unchanged.

The wrapper retains ownership while the fixed acceptance command runs, signals its owned process group and reaps the direct consumer before cleanup on failure, and verifies alias identity before and after consumption. Cleanup reconciles only the unique owned image/container resources with matching immutable identity. Image deletion targets the verified immutable ID after owned containers, not a mutable alias. Unexpected tags refuse removal. Foreign resources remain untouched; ambiguous ownership, changed aliases, failed gates and unresolved cleanup refuse success. This trusted disposable CI composition assumes no concurrent unauthorized Docker tag writer; Docker offers no atomic compare-and-delete alias operation. No registry push, deployment or host network change occurs.

## Required evidence

Pure tests must cover malformed/missing identity, foreign alias or ownership, ambiguous tagging, invalid probes, gate failure/timeout/interruption and cleanup failure. Normal and genuinely new-empty Python aggregates, independent exact-tree review and all seven actual workflows remain required. Actual application tests must have no service skips; controlled transport and the normal authenticated operator journey must prove the curated image identity alongside existing durable outbox/RabbitMQ/Celery, protected HTTPS, isolated parsing, tenant review and CSV/XLSX export evidence.

[Validation](../reports/em017d-validation.md) distinguishes local skips from actual controlled execution. All inputs remain authored synthetic fixtures. This closes only the controlled packaged-worker consumption gap; it does not establish live publisher rights, real-source extraction quality, production identity/storage assembly, staging, release signing or deployment readiness. Rollback restores the prior CI image preparation; there is no migration or deployed-state change.

# EM-017 closed synthetic service-authority restore — candidate evidence

## Baseline and scope

Dependent on accepted Draft PR47 head `217110b3ebbdbdd2dc2c2594cc17c3d98cb040e2`,
tree `70900725a271cd469c7e5018acf1d4a597fc927e`. That head remains unchanged.
Independent design review approved the bounded closed test profile before edits.
[Control contract](../docs/67-closed-service-authority-restore.md) maps the ADR 0006
restore requirement to service, audit, schema, role, export and privacy seals.

No production code or migration change, dependency change, live acquisition,
credential/persistent-access activation, deployment, merge or release is included.
The legacy profile retains its unconditional populated-service-state refusal.
The new target never opens to runtime/service logins.

## Verification status

Implementation and independent source review passed. Normal and separate fresh
empty-checkout gates ran serially against tree
`121d865e0c0a487908a9f113a74abec9ce3ab43d` before this evidence-only update:

- 4,754 backend tests passed in each; 389 infrastructure-dependent tests explicitly
  skipped in each. The new actual restore test is one of these skips.
- 77 React tests passed in each; Ruff checked/formatted 358 files and strict mypy
  checked 356 source files; docs/contracts, dependency inventory, frontend typing,
  lint and production build all passed.
- 357 new pure service-restore contracts plus 45 inherited legacy contracts passed
  in a focused 402-test run. They include final-capture race injection, exact
  revocation/audit grammar, export seals and recorded tombstone-history checks.
- Independent review identified and verified fixes for target database-owner drift
  and final-state seal completeness. The actual test closes fixture pools and uses
  real prebackup service scopes in both tenants; positive SQL probes roll back.

The test runs beside legacy restore, before later persistent service fixtures, to
preserve the inherited 64 MiB database cap. That cap is not raised. Local Docker
and PostgreSQL tools are unavailable; no actual dump/restore or service SQL result
is claimed locally. Frozen-tree and full hosted SQL/dump/restore/service/operator/
packaging/security acceptance remain pending. Exact draft-head workflow receipts
and the final acceptance decision are recorded in the pull request; infrastructure
skips never substitute for those actual proofs.

## Required final evidence

- Exact authored tree, dependent draft head and tested merge-tree provenance.
- Full normal and separate fresh local results, including explicit skip counts.
- Actual same-version dump/restore and closed target checks; immutable deadlines,
  exact revoked service/audit state, privacy replay and no revived work.
- Source/target drift refusal, two-tenant/current-scope SQL role-behavior checks,
  and verified exact owned target/archive cleanup.
- All inherited actual-login, broker, installed HTML/XML operator/recovery,
  parser/browser/transport, packaging and cleanup workflows.
- Independent exact-tree source and final hosted evidence decision.

This milestone does not establish a production restore procedure, real login
activation into a restored database, business-history merge, staging deployment or
measured production RPO/RTO.

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

## First hosted candidate and representation correction

Draft PR48 candidate `e3d7e5559f6e4b0133426a6f6146d5ea5948da45`, tree
`e676fde3b80079f565ea8210015d4e049e8848a8`, ran the complete hosted matrix.
Seven required workflows passed, including all four installed controlled XML
scenarios and verified owned cleanup. Application acceptance reported 5,142 passed
and one failure during baseline capture in the new service-restore test, before
any dump or restore. It did
not complete the actual restore proof and is not an accepted candidate.

The failure exposed PostgreSQL's JSON representation of the `oid` type as a
string. A shared bounded service-row reader now projects only the trusted SQL
`login_oid` field to `bigint` for principal capture and reconciliation. It retains
all other fields, exact role/OID checks, the row cap and strict snapshot integer
validation; arbitrary snapshot strings are not coerced or accepted. PostgreSQL's
full unsigned 32-bit OID range fits bigint. Native driver role OID values and
existing delegation bigint fields need no conversion. Pure query-contract tests
and an actual SQL representation assertion cover this boundary. Repeated normal,
fresh and full hosted acceptance of the corrected candidate remain required.


The corrected source tree `1395acbb014da99d53a75abf5323ca51c71e0162` passed
independent source review and repeated normal/fresh serial local gates: 4,765
backend tests passed with 389 explicit infrastructure skips, and 77 React tests
passed in each. All static, documentation/contracts, inventory and frontend gates
passed. Focused service plus legacy contracts passed 413 tests. This paragraph is
an evidence-only update after those gates; corrected actual hosted acceptance is
still pending and recorded separately in PR48.


## Second hosted candidate and effective-ACL correction

Candidate `d2502712b980862e32a8663fb4d23b875e143809` passed seven required
workflows and 5,153 backend tests. The new actual test verified PostgreSQL OID
serialization and full-range numeric preservation, captured the baseline, and
completed the actual dump and closed restore. The exact restored-baseline seal
then refused a mismatch before replay. This candidate is not accepted.

Independent PostgreSQL source review established a nonportable catalog
representation: a no-op REVOKE on the three service tables stores an explicit
owner-only default ACL, whereas pg_dump omits commands equal to the default and
restore leaves NULL. The relation catalog now expands only NULL ACLs to the exact
PostgreSQL effective default for table-like relations and sequences. Explicit
empty ACLs, all entries, grantors, privileges and grant options remain intact;
non-ACL-bearing relations retain their raw representation. The sequence acldefault
code is lowercase `s`, distinct from uppercase `S` relkind. Existing migration
compatibility and restore comparisons share the same strict projection.

The actual restore test asserts the source/restored raw representation distinction
and complete effective-ACL equality for the three service tables. Fixed,
allowlisted section diagnostics can identify any further seal mismatch without
printing row values, identifiers, tokens or digests. The full fingerprint comparison
remains mandatory. Corrected normal/fresh and hosted acceptance remain required.

ACL-corrected source tree `59429c6f7f271dbe1b421eaa6a7e9051594b9c53` passed
independent review and complete normal/fresh serial gates: 4,810 backend tests
passed with 389 explicit infrastructure skips and 77 React tests passed in each.
All static, documentation/contracts, inventory and frontend gates passed. Focused
service plus legacy contracts passed 458 tests. This paragraph alone records the
post-gate evidence; full corrected hosted acceptance remains pending in PR48.


## Third hosted candidate and void-return assertion

Candidate `f8b8e8e7540b79ec5c7231a7fa312f682ad0179e` passed seven required
workflows and 5,198 backend tests. The new actual test passed raw/effective ACL
assertions, the exact restored-baseline seal, revocation/privacy replay, repeated
replay and the early revoked/disabled/expired denial probes. A later publisher
probe failed only because its assertion expected Python None from the SQL void
`service_end` function; pinned pg8000 returns PostgreSQL's empty text void value.
The assertion now expects that exact value while retaining the function call and
its authority fence. No SQL behavior or restore constraint is changed. The full
remaining actual probe sequence and complete hosted matrix remain required.

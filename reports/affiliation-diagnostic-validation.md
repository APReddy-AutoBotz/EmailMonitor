# Affiliation diagnostic candidate validation

Scope: [design and reviewed boundaries](../docs/63-affiliation-diagnostic-design.md).
This unpublished candidate contains authored synthetic evidence only. It neither
reacquires nor re-parses the previously evaluated article. The hypothesis about
that real sample remains unproven.

## Synthetic mechanism

Six controlled counterfactuals compare two authors, two reserved example-domain
candidates and one affiliation. No references/unlabelled textfn yields affiliations
for both authors; correspondence-only or footnote-only reference suppresses both;
labels also suppress; explicit affiliation edges restore selection; absent selected
textfn produces the same partial reason by a different mechanism. Candidate
positions and needs_review states are preserved. The initial malformed fixture
omitted required correspondence text, returned unsupported_structure, and was
corrected before the six counterfactual assertions passed.

## Independent review

Design review required full existing parser and XmlExpectation validation inside
the guest, explicit node-versus-selection-edge units, a separate rights purpose,
and isolated command/marker/output boundaries. These requirements were adopted.
Implementation review found the direct-textfn counter initially counted exactly
one child instead of presence; corrected to presence with regression coverage for
unselected duplicate textfn and refusal when that duplicate becomes selected.
Final boundary source review passed; the frozen-tree identity is recorded by the handoff.

## Executed local checks so far

- Reproduction plus unchanged article-parser suite: 112 passed.
- Core/canonical output/resource/guest mock suite after review correction: 38 passed.
- Earlier focused core/reproduction/parser/private admission/one-shot/packaging/
  integration/pipeline suite: 445 passed in 9.61s (before the added duplicate case).
- Documentation/contracts/traceability/fixture validation: passed.
- Core and reproduction strict mypy: four files passed before latest added case.

These are local pure/mock checks, not actual network-none Docker evidence. No
Docker executable is installed in this cloud workspace. Actual synthetic isolated
acceptance remains pending; final local aggregates are recorded below. Existing one-shot workflow,
one-shot runner, normal parser, ordinary worker/channel/protocol are unchanged.
No real input, source data, excerpts or contact values are published or retained by
this work. No migration, merge, deployment, production activation or live API use.

## Final review and later checks

Independent final source review found no blocking findings. It independently ran
230 focused tests successfully; the actual-Docker node correctly skipped once.
The actual gate now covers both authored synthetic cases through the full new
admission-to-container composition, rather than testing the channel alone.
The old parser/private admission/worker/channel/protocol and PR42 one-shot files
remain unchanged. Packaging adds only the two guest modules and leaves the default
worker command intact.

The first broad aggregate reported 2707 passed/303 skipped/1 failed: a guard test
expected three shell test invocations before the additive diagnostic gate. The
assertion now requires four invocations and the new gate/sentinel while preserving
all original 41-test, one-test and four-operator predicates. Its focused suite
passed all 47 tests after correction. This failure is retained here as evidence.

Whole Ruff lint/format passed (279 files); whole mypy passed (277 files). Frontend
typecheck/lint/build and all 48 React tests passed. Inventory covers 64 Python and
159 JavaScript locked packages. Documentation and shell syntax checks passed.

A genuinely absent fresh environment was verified before setup. The first setup
attempt failed because uv's default cache was read-only; no tests ran in that
attempt. Setup then used the existing writable package cache with --offline and a
new /tmp environment. Reusing that cache is not a fresh-download claim.


## Final local aggregate receipts

- Normal environment: 2751 passed, 303 explicit service-dependent skips, 122.69s, exit 0.
- Verified new-empty Python environment: 2751 passed, 303 explicit service-dependent
  skips, 130.37s, exit 0. Offline locked installation reused the existing uv cache.
- Actual diagnostic Docker acceptance: not executed; local node skipped once.

This is a reviewed unpublished candidate, not actual isolation certification.
Required next evidence is the new synthetic actual gate plus all existing exact-head
CI gates, with PR42's one-shot acquisition left untouched. No real-sample run is
part of this continuation. No production/migration effect is introduced.

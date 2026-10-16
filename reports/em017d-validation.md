# EM-017d curated XML integration validation

## Accepted starting point

Draft PR32 head `ba2bc151ff9fb45bfc38453685c42bc2e49eb451`, tree `f2e87c0a8d0cac9ef8d91a54ba5b1108686b4027`, passed all seven corrected-head workflows. Actual application: 2325 backend tests without skips and 31 React tests. Actual packaging: two metadata builds plus two uncached XML builds, equal defined contents, two XML probes and fourteen worker cases with owned cleanup. Initial PR32 import-path failure and its correction remain recorded in PR32 and the prior report.

## Initial candidate checkpoint

The new slice consumes that curated artifact through the unchanged synthetic XML channel in existing application and controlled operator acceptance. No runtime/protocol/dependency/migration/source-policy change is intended. At this initial checkpoint, pure image-identity tests and source inspection were in progress. The local and review stages below supersede this initial pending checkpoint; all seven actual own-head workflows remain pending. Local mocked orchestration or service skips cannot establish actual image consumption.

## Preserved local contract failures

Initial normal and new-empty aggregates returned exit 1: 9 failed, 2115 passed, 260 explicit inherited service skips (76.74s/81.01s). All nine failures were static contracts expecting command text inline in workflow YAML or the prior step title; the fixed commands had moved into the CI wrapper's shell. Frontend stages were not reached. The original application step title is restored, and three contract readers now assert the explicit workflow-to-wrapper-to-fixed-shell chain before testing the unchanged exact count/no-skip predicates. A preliminary incorrect literal mapping assertion was caught in focused tests and corrected to the actual fixed mapping and selector structure. All 63 affected existing contract tests then passed in 0.76s; no runtime or success predicate changed.

Independent preliminary review passed the 59 new focused cases (44 orchestration plus 15 identity checks). Source, protocol, isolation profile and separate reproducibility gate are unchanged. Corrected full normal/new-empty and actual CI acceptance remain pending.

The corrected normal run reached 2124 backend passes/260 explicit skips in 74.66s and locked frontend installation, then its polling session became unavailable following an approval-check interruption. No aggregate exit receipt or completed frontend stages exist for that run; it remains incomplete. A separately recorded clean normal/new-empty validation is required. Existing public dependency manifests and lockfiles are unchanged; the check script invokes pnpm install and peers checks, not an npm/pnpm audit command.

## Final local evidence

Clean normal and genuinely new-empty Python aggregates both completed with process exit 0 and explicit exit receipts: 2124 passed/260 inherited explicit service skips in 76.49s/75.56s, 31 React tests, strict mypy 240 files, Ruff, inventory, frontend build and all aggregate gates. The fresh environment did not exist before creation and installed 63 locked packages; dependency caches and frozen frontend dependencies were reused. Documentation checks cover 72 documents/317 links/56 JSON files/24 schemas/27 examples. Independent review separately passed all 59 new cases plus 63 affected existing contract cases (122 total).

Local Docker is unavailable; these runs do not prove actual image consumption. New-head acceptance requires 2384 actual backend tests without skips, controlled 41 plus provider operator 1, original static UI/browser/parser, unchanged two-build metadata/XML packaging and docs. Reconcile each prepared application/transport artifact hash against the same-head packaging receipts, and each observed parser image ID against that job's prepared identity. No production readiness or live-source claim is made.

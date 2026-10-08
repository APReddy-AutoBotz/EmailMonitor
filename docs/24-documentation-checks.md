# 24 — Documentation validation and CI

**Baseline:** 2026-10-08. The repository includes a documentation-only GitHub Actions workflow and an offline validation script. Application CI and runtime implementation remain EM-001 and later tasks.

## What the check executes

`python -m py_compile scripts/validate_docs.py` verifies that the validator compiles. `python scripts/validate_docs.py` checks local Markdown link targets, JSON syntax and duplicate keys, four JSON Schema definitions, five example payloads, twelve negative contract cases, business/functional/non-functional requirement traceability, the eighteen-task ledger, synthetic HTML links and expected result counts, reserved email domains, and the exact synthetic evidence digest.

The script does not execute an application extractor. Its four expected author-email pairs are a synthetic fixture specification, not measured extraction results. It does not verify external links or source licenses, execute browser/PDF parsing, certify tenant isolation or security enforcement, measure accuracy/latency, send email, or deploy anything.

## Execution and evidence

The `Documentation checks` workflow runs on main pushes and pull requests, with read-only repository permission, no customer secrets, an isolated Python environment and immutable action revisions. It uploads the actual validation log and a Git archive of the checked revision as a short-lived artifact. Check the workflow conclusion and log for the exact commit before calling validation successful.

Installation downloads the documentation validation dependency from the package index; validation itself uses only committed synthetic/local data. This is not live publisher crawling. Runtime/dependency lockfiles and expanded application/security CI remain implementation tasks.

A failing workflow must be repaired or explicitly reported before handing the relevant contract to implementation. Do not convert a missing run, unavailable runner, dependency failure or skipped check into a pass. Later changes to schemas, fixture bytes or links should rerun the same checks.

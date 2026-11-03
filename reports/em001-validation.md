# EM-001 local validation evidence

Date: 2026-10-10. Baseline: `cb5f4603fc8ac70a3f0d92df8bc81d645a28a174`; all 61 baseline files materialized through the GitHub connector, with matching Git tree `53684caa42a21b37368ae3001f7d485afe4800f0`. A local snapshot commit is not the upstream commit; publication uses the upstream baseline as parent.

Environment: Linux x86_64, Python 3.12.14, Node 24.19.0, uv 0.12.23, pnpm 11.25.0. No application secrets, source credentials, customer data, mail or external AI. Dependency installation/metadata checks used official package registries; no publisher crawling.

## Executed local gates

- `scripts/check.sh`: exit 0 after frozen installs; Ruff lint/format pass; strict mypy pass (7 source/test files); 30 Python API/configuration/contract/fixture tests pass; inventory parity pass (34 Python and 159 JavaScript locked packages); strict frontend peer check has no issues; frontend typecheck/lint pass; 1 real React component render test passes; Vite production build passes
- Same script in a fresh directory with no virtualenv/node_modules/build artifacts: exit 0, fresh frozen installation and the same 30 Python/1 frontend tests and build pass
- `python scripts/validate_docs.py`: local docs/contract/examples/fixture/traceability pass, including 4 schemas, 5 examples, 12 negative contract cases, 36 FR and 18 NFR mappings, 6 HTML fixtures, 4 unique article expectations and 4 manually specified contact-pair expectations
- Actual Uvicorn loopback HTTP smoke: `/healthz` returns `{"status":"ok"}`; `/api/v1/capabilities` reports scaffold and false extraction/live-source/email/AI/tenant-data availability; process stopped after smoke
- Actual production import subprocess tests reject both fixture and identity-stub flags; tests do not just validate an unused configuration class

Initial compatibility failures were repaired before these passing runs: TypeScript 7 was incompatible with typescript-eslint and replaced with 6.0.3; Vite CSS type declarations were added; deprecated Starlette TestClient was replaced by ASGITransport. They are not reported as successful trial runs.

## Pending and excluded

Independent read-only review, draft PR and exact published-head GitHub CI verification are pending. No extraction, tooltip/browser execution, real-source certification, tenant authentication/RLS, persistence/replay, benchmark, deployment, vulnerability certification or core UAT pass is claimed. The fixture harness serves bytes; expected observations are specifications, never measured extractor output. UI test is a component render smoke, not browser accessibility certification.

Migration/deployment impact: none. Next task after acceptance: EM-002. No merge or release is performed by this slice.

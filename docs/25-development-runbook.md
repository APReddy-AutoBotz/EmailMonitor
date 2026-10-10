# 25 — EM-001 development and dependency runbook

Verified 2026-10-10 on Linux x86_64. This runs a scaffold, not an extraction demonstration or production service.

## Version matrix

| Component | Selected/tested version | Boundary |
|---|---|---|
| Python | 3.12.14 | Project metadata allows 3.12–3.13; only 3.12 tested here |
| uv | 0.12.23 | Frozen Python lock installation; MIT/Apache-2.0 tooling |
| FastAPI / Pydantic / Starlette | 0.143.0 / 2.14.0 / 1.7.0 | Resolver-compatible, actual ASGI tests; MIT/MIT/BSD-3-Clause |
| Uvicorn | 0.54.0 | Actual loopback HTTP smoke; BSD-3-Clause |
| Node | 24.19.0 | Node 24.x is the selected frontend runtime |
| pnpm | 11.25.0 | Frozen lock, strict peers; MIT tooling |
| React / React DOM | 19.3.0 / 19.3.0 | MIT; actual component render smoke |
| TypeScript | 6.0.3 | Apache-2.0; selected within typescript-eslint's >=4.8.4 <6.1 peer range |
| Vite / React plugin | 8.3.4 / 6.1.2 | MIT; Node 24 satisfies engine requirements |
| Vitest / ESLint / typescript-eslint | 5.0.3 / 10.12.0 / 8.71.1 | MIT; tests/lint actually executed |

Do not substitute floating “latest” versions. The TypeScript 7 trial was rejected because the installed linter did not support it. The first API test trial produced Starlette's deprecated HTTPX TestClient warning; tests now use HTTPX ASGITransport without that deprecated path. Lockfiles and package manifests are the exact version authority.

Primary compatibility references: [Vite guide](https://vite.dev/guide/), [React versions](https://react.dev/versions), [FastAPI dependency guidance](https://fastapi.tiangolo.com/deployment/versions/). The installed engine/peer metadata and executed checks establish this matrix; official docs alone do not prove compatibility.

## Setup and checks

Install Python 3.12, Node 24.19.0, uv 0.12.23 and pnpm 11.25.0 from their official distributions. No application credentials are needed. From the repository root:

```sh
uv sync --project services/backend --locked
pnpm --dir apps/web install --frozen-lockfile --strict-peer-dependencies
scripts/check.sh
```

`check.sh` executes docs/schema/example/fixture consistency, Python lint/format/type tests, API/configuration/fixture/contract tests, inventory parity, strict frontend peer validation, type/lint/component tests and production build. Installation needs official registry access; tests are local and do not crawl publishers. Runtime-only Python installation uses `--no-dev`.

Separate terminals:

```sh
uv run --project services/backend uvicorn emailmonitor.api:app --app-dir services/backend/src --host 127.0.0.1 --port 8000
pnpm --dir apps/web dev
```

Use the Vite loopback URL. `/healthz` means only that the API process responds. `/api/v1/capabilities` reports scaffold/unimplemented state. There are no login, job, contact or export endpoints. Inputs are disabled in the web UI. Do not expose development servers publicly. Production CSP is inserted during Vite build; development does not apply it because Vite hot reload needs development scripts/styles. HTTP deployment headers are future work.

## Fixture and configuration safety

All `EMAILMONITOR_` keys are strictly parsed. Default environment is production; all outbound features are unavailable. Fixture/identity-stub flags are allowed only in explicitly selected test configuration and rejected by actual production startup. The fixture transport resides in `tests/`, maps six fixed HTTPS paths at `synthetic.publisher.example` to committed bytes, and cannot fall back to a socket. It does not extract contacts or execute tooltip JavaScript. Expected results are manually authored future-test specifications.

No application network client, SQL persistence, OIDC, broker, worker or parser has been added. Denying unavailable capabilities is not a claim of a complete production egress sandbox or tenant isolation. Those are EM-002–004 gates.

## Dependency/license review

[Machine-readable inventory](../reports/dependency-inventory.json) covers every locked Python package (including Windows-only Colorama) and JavaScript package (including optional platform binaries). It records exact versions, registry/source links, declared licenses and lock digests. `scripts/check_inventory.py` fails offline when locks/inventory drift, a new declared license is unreviewed, or a default MuPDF dependency appears. The installed package metadata and official registry metadata were inspected on 2026-10-10. Colorama's missing registry license field was resolved against its [official BSD-3-Clause license](https://github.com/tartley/colorama/blob/0.4.6/LICENSE.txt); Pathspec's MPL declaration came from distribution classifiers.

Declared license families in this lock are MIT, Apache-2.0, BSD-2/3-Clause, ISC, BlueOak-1.0.0, PSF-2.0 and MPL-2.0 (plus the Apache/BSD dual choice). Certifi and development-only Pathspec use MPL-2.0; no third-party source was modified. Retain their bundled license/notices and source-availability obligations when distributing covered files. Permissive dependencies also require preservation of applicable copyright/license/notices. Tooling/runtime distributions have their own bundled notices. This inventory is a development review, not legal clearance, a full bundled-code attribution package or vulnerability certification. Full artifact SBOM, attribution, security scans and commercial distribution clearance remain EM-018 release gates.

No PDF/OCR/browser binary/database/broker dependency is installed by this slice. MuPDF/PyMuPDF remains separately gated. No project license or repository visibility change is made.

When changing dependencies: update exact direct pins, regenerate locks through official registries, inspect all new/transitive/optional declared licenses and bundled notices, regenerate inventory and lock digests, run a clean `scripts/check.sh`, and obtain review. Do not merely expand the allowed-license set to silence a gate.

## Migration and rollback

No database migration or deployment. Stop local servers with Ctrl-C. Remove local virtualenv/node_modules/dist directories if resetting installation; these contain reproducible development artifacts, not customer data. Revert the scaffold commit to roll back the application changes while preserving baseline documentation. Next task is EM-002 after EM-001 review/CI acceptance.

EM-005 pins Celery 5.6.3 (BSD-3-Clause) and official RabbitMQ 4.3.6 (MPL-2.0 software, immutable CI image). Exact lock inventory is 60 Python / 159 JavaScript packages. Full image attribution/vulnerability review remains a release gate; see [durability runbook](29-durable-offline-jobs-runbook.md).

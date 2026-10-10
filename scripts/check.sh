#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --project services/backend --locked
uv run --project services/backend python -m py_compile scripts/validate_docs.py
uv run --project services/backend python scripts/validate_docs.py
uv run --project services/backend ruff check --config services/backend/pyproject.toml services/backend/src services/backend/tests tests scripts/check_inventory.py
uv run --project services/backend ruff format --check --config services/backend/pyproject.toml services/backend/src services/backend/tests tests scripts/check_inventory.py
uv run --project services/backend mypy --config-file services/backend/pyproject.toml services/backend/src services/backend/tests tests
uv run --project services/backend pytest services/backend/tests tests
uv run --project services/backend python scripts/check_inventory.py
pnpm --dir apps/web install --frozen-lockfile --strict-peer-dependencies
pnpm --dir apps/web peers check
pnpm --dir apps/web typecheck
pnpm --dir apps/web lint
pnpm --dir apps/web test
pnpm --dir apps/web build

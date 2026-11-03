#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
phase="${1-all}"
if (( $# > 1 )); then
  exit 2
fi
case "$phase" in
  all|static|backend|frontend|ci-backend|ci-outcome-sql|ci-capacity-sql) ;;
  *) exit 2 ;;
esac
if [[ "$phase" != frontend ]]; then
  uv sync --project services/backend --locked
fi
if [[ "$phase" == all || "$phase" == static ]]; then
  uv run --project services/backend python -m py_compile scripts/validate_docs.py
  uv run --project services/backend python scripts/validate_docs.py
  uv run --project services/backend ruff check --config services/backend/pyproject.toml services/backend/src services/backend/tests services/backend/migrations tests scripts/check_inventory.py scripts/create_ci_runtime.py scripts/isolation scripts/packaging
  uv run --project services/backend ruff format --check --config services/backend/pyproject.toml services/backend/src services/backend/tests services/backend/migrations tests scripts/check_inventory.py scripts/create_ci_runtime.py scripts/isolation scripts/packaging
  uv run --project services/backend mypy --config-file services/backend/pyproject.toml services/backend/src services/backend/tests services/backend/migrations tests scripts/create_ci_runtime.py scripts/isolation scripts/packaging
fi
if [[ "$phase" == all || "$phase" == backend ]]; then
  uv run --project services/backend pytest services/backend/tests tests
  uv run --project services/backend python scripts/check_inventory.py
fi
if [[ "$phase" == ci-backend || "$phase" == ci-outcome-sql || "$phase" == ci-capacity-sql ]]; then
  profile=backend
  if [[ "$phase" == ci-outcome-sql ]]; then
    profile=outcome_sql
  elif [[ "$phase" == ci-capacity-sql ]]; then
    profile=capacity_sql
  fi
  uv run --project services/backend python scripts/packaging/application_test_partition.py "$profile"
  if [[ "$phase" == ci-backend ]]; then
    uv run --project services/backend python scripts/check_inventory.py
  fi
fi
if [[ "$phase" == all || "$phase" == frontend ]]; then
  pnpm --dir apps/web install --frozen-lockfile --strict-peer-dependencies
  pnpm --dir apps/web peers check
  pnpm --dir apps/web typecheck
  pnpm --dir apps/web lint
  pnpm --dir apps/web test
  pnpm --dir apps/web build
fi

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${EM_TEST_DATABASE_URL:?A disposable non-owner PostgreSQL test URL is required}"
: "${EM_TEST_AUTH_DATABASE_URL:?A separate disposable authentication test URL is required}"
: "${EM_TEST_ADMIN_DATABASE_URL:?A separate disposable migration/admin test URL is required}"
# This must point to synthetic/disposable state, never an existing customer database.
EM_MIGRATION_DATABASE_URL="$EM_TEST_ADMIN_DATABASE_URL" uv run --project services/backend alembic -c services/backend/alembic.ini upgrade head
EM_MIGRATION_DATABASE_URL="$EM_TEST_ADMIN_DATABASE_URL" uv run --project services/backend alembic -c services/backend/alembic.ini upgrade head
scripts/check.sh

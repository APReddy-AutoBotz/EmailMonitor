#!/usr/bin/env bash
# Focused synthetic diagnostics only; the genuine hosted browser gate remains required.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="services/backend/src:services/backend/tests:tests:scripts/isolation:scripts/packaging"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/emailmonitor-uv-cache}"
uv run --no-sync --project services/backend pytest -q \
  services/backend/tests/test_operator_lifecycle_contract.py \
  services/backend/tests/test_browser_failure_diagnostic.py \
  services/backend/tests/test_operator_deletion_diagnostic.py \
  services/backend/tests/test_guest_outcome_metadata.py \
  services/backend/tests/test_operator_focus_diagnostic.py \
  services/backend/tests/test_operator_ui_protocol.py \
  services/backend/tests/test_operator_keyboard_attempt_trace.py \
  services/backend/tests/test_installed_operator_harness.py \
  services/backend/tests/test_installed_host_relay_diagnostics.py \
  services/backend/tests/test_browser_marker_diagnostic.py \
  services/backend/tests/test_operator_browser_acceptance_contract.py

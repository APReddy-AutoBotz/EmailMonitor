#!/usr/bin/env bash
# Fixed existing controlled/provider checks; the wrapper verifies the alias around each gate.
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${RUNNER_TEMP:?Disposable CI runner temporary directory is required}"
case "${1-}" in
  transport)
    uv run --project services/backend pytest -c services/backend/pyproject.toml scripts/isolation/test_transport_acceptance.py scripts/isolation/test_provider_transport_acceptance.py scripts/isolation/test_provider_journey_acceptance.py -ra -s | tee "$RUNNER_TEMP/transport-acceptance.log"
    grep -Eq '(^|[=[:space:]])41 passed([ ,]|$)' "$RUNNER_TEMP/transport-acceptance.log"
    ! grep -Eq '[0-9]+ skipped|[0-9]+ warnings?' "$RUNNER_TEMP/transport-acceptance.log"
    uv run --project services/backend pytest -c services/backend/pyproject.toml scripts/isolation/test_private_sample_acceptance.py -ra -s | tee "$RUNNER_TEMP/private-sample-acceptance.log"
    grep -F 'PRIVATE_OFFLINE_SYNTHETIC_NETWORK_NONE_REDACTED_COUNTS' "$RUNNER_TEMP/private-sample-acceptance.log"
    grep -Eq '(^|[=[:space:]])1 passed([ ,]|$)' "$RUNNER_TEMP/private-sample-acceptance.log"
    ! grep -Eq '[0-9]+ skipped|[0-9]+ warnings?' "$RUNNER_TEMP/private-sample-acceptance.log"
    uv run --project services/backend pytest -c services/backend/pyproject.toml scripts/isolation/test_affiliation_diagnostic_acceptance.py -ra -s | tee "$RUNNER_TEMP/affiliation-diagnostic-acceptance.log"
    grep -F 'AFFILIATION_DIAGNOSTIC_SYNTHETIC_NETWORK_NONE_COUNTERS' "$RUNNER_TEMP/affiliation-diagnostic-acceptance.log"
    grep -Eq '(^|[=[:space:]])1 passed([ ,]|$)' "$RUNNER_TEMP/affiliation-diagnostic-acceptance.log"
    ! grep -Eq '[0-9]+ skipped|[0-9]+ warnings?' "$RUNNER_TEMP/affiliation-diagnostic-acceptance.log"
    ;;
  operator)
    uv run --project services/backend pytest -c services/backend/pyproject.toml scripts/isolation/test_operator_provider_acceptance.py scripts/isolation/test_operator_browser_acceptance.py scripts/isolation/test_operator_keyword_browser_acceptance.py -v -s | tee "$RUNNER_TEMP/provider-operator.log"
    grep -F 'NORMAL_OPERATOR_RABBITMQ_PROVIDER_ISOLATED_REVIEW_EXPORT' "$RUNNER_TEMP/provider-operator.log"
    grep -F 'NORMAL_OPERATOR_DIRECT_XML_URL_ISOLATED_REVIEW_EXPORT' "$RUNNER_TEMP/provider-operator.log"
    grep -F 'NORMAL_OPERATOR_TOOLTIP_BROWSER_ISOLATED_REVIEW_EXPORT' "$RUNNER_TEMP/provider-operator.log"
    grep -F 'NORMAL_OPERATOR_KEYWORD_BROWSER_ISOLATED_REVIEW_EXPORT' "$RUNNER_TEMP/provider-operator.log"
    grep -Eq '(^|[=[:space:]])4 passed([ ,]|$)' "$RUNNER_TEMP/provider-operator.log"
    ! grep -Eq '[0-9]+ skipped' "$RUNNER_TEMP/provider-operator.log"
    ;;
  *) printf '%s\n' 'XML_INTEGRATION_GATE_REFUSED' >&2; exit 1 ;;
esac

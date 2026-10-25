#!/usr/bin/env bash
# Fixed installed controlled-XML acceptance; the wrapper owns the curated parser image.
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${RUNNER_TEMP:?Disposable CI runner temporary directory is required}"
[[ $# -eq 0 ]] || { printf '%s\n' 'XML_INSTALLED_GATE_REFUSED' >&2; exit 1; }
uv run --project services/backend pytest -c services/backend/pyproject.toml scripts/isolation/test_installed_xml_acceptance.py -v -s | tee "$RUNNER_TEMP/installed-xml-acceptance.log"
grep -F 'INSTALLED_CONTROLLED_XML_KEYWORD_REVIEW_EXPORT' "$RUNNER_TEMP/installed-xml-acceptance.log"
grep -F 'INSTALLED_CONTROLLED_XML_DIRECT_URL_REVIEW_EXPORT' "$RUNNER_TEMP/installed-xml-acceptance.log"
! grep -Eq '[0-9]+ skipped|[0-9]+ warnings?' "$RUNNER_TEMP/installed-xml-acceptance.log"
grep -F 'INSTALLED_CONTROLLED_XML_POST_OBSERVATION_CRASH_RECOVERY' "$RUNNER_TEMP/installed-xml-acceptance.log"
grep -F 'INSTALLED_CONTROLLED_XML_DELEGATION_REVOKED_DURING_RESPONSE' "$RUNNER_TEMP/installed-xml-acceptance.log"

grep -F 'INSTALLED_AUTHORED_PDF_DIRECT_URL_REVIEW_EXPORT' "$RUNNER_TEMP/installed-xml-acceptance.log"
grep -F 'INSTALLED_AUTHORED_PDF_POST_OBSERVATION_CRASH_RECOVERY' "$RUNNER_TEMP/installed-xml-acceptance.log"

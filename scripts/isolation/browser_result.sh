#!/usr/bin/env bash
# Preserve the exact child exit status; emit only a fixed, value-free category.
set +e
"$@"
status=$?
if (( status == 0 )); then
  category=exit_zero
elif (( status < 128 )); then
  category=exit_1_to_127
else
  # Shell status alone cannot distinguish a signal from a high exit code.
  category=exit_128_to_255
fi
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  { printf 'browser_outcome=%s\n' "$category" >> "$GITHUB_OUTPUT"; } 2>/dev/null || true
fi
exit "$status"

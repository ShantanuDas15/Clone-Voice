#!/usr/bin/env bash
# Wait until every required status check of a commit has finished, and succeed only if all passed.
#
#   scripts/ci/wait-for-checks.sh <sha> <timeout-seconds> <check> [<check> ...]
#
# Needs `gh` (authenticated through GH_TOKEN) and GITHUB_REPOSITORY. A check that has not started yet
# counts as "still waiting", so the script cannot pass before CI has actually run. When a check was
# run more than once for the commit (a re-run), the latest run decides. Exit 0: all passed; 1: one
# failed, was cancelled or timed out; 2: the wait itself timed out.
set -euo pipefail

sha=${1:?usage: wait-for-checks.sh <sha> <timeout-seconds> <check>...}
timeout=${2:?usage: wait-for-checks.sh <sha> <timeout-seconds> <check>...}
shift 2
required=("$@")
[ "${#required[@]}" -gt 0 ] || { echo "no checks named" >&2; exit 64; }

deadline=$((SECONDS + timeout))
while true; do
  runs=$(gh api "repos/${GITHUB_REPOSITORY}/commits/${sha}/check-runs?per_page=100" \
    --jq '[.check_runs[] | {name, status, conclusion, started_at}]')
  pending=0
  for name in "${required[@]}"; do
    row=$(jq -c --arg n "$name" '[.[] | select(.name == $n)] | sort_by(.started_at) | last // empty' <<<"$runs")
    if [ -z "$row" ]; then
      echo "waiting: ${name} (not started)"
      pending=1
      continue
    fi
    status=$(jq -r '.status' <<<"$row")
    conclusion=$(jq -r '.conclusion // ""' <<<"$row")
    if [ "$status" != "completed" ]; then
      echo "waiting: ${name} (${status})"
      pending=1
    elif [ "$conclusion" != "success" ]; then
      echo "FAILED: ${name} concluded '${conclusion}'" >&2
      exit 1
    else
      echo "passed:  ${name}"
    fi
  done
  if [ "$pending" -eq 0 ]; then
    echo "all required checks passed for ${sha}"
    exit 0
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "gave up after ${timeout}s waiting for the checks above" >&2
    exit 2
  fi
  sleep 30
done

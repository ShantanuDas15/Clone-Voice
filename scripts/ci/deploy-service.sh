#!/usr/bin/env bash
# Upload one commit to one Railway service and wait until that deployment is live.
#
#   scripts/ci/deploy-service.sh <api|web> <sha>
#
# Needs the Railway CLI and RAILWAY_TOKEN (a project token for the environment). The deployment is
# tagged "ci:<sha>", which is how it is found again; `railway up --ci` returns when the build ends, and
# the wait that follows is for the health check, so a build that cannot start fails here. Railway keeps
# the previous deployment serving while a new one is unhealthy, so a failure is a red run, not an outage.
set -euo pipefail

service=${1:?usage: deploy-service.sh <api|web> <sha>}
sha=${2:?usage: deploy-service.sh <api|web> <sha>}
: "${RAILWAY_TOKEN:?RAILWAY_TOKEN is not set: see RAILWAY_DEPLOYMENT.md, Automatic deploys}"
environment=${RAILWAY_ENVIRONMENT_NAME:-production}
message="ci:${sha}"

on_failure() {
  cat >&2 <<MSG

The ${service} deployment for ${sha} did not go live. Railway keeps the previous version serving.
To go back to a known good commit: Actions > deploy > Run workflow, give that commit as "ref"
(tick "skip_ci_gate" if it predates a required check). Or use Redeploy on an earlier deployment in the
Railway dashboard. To stop merges deploying at all, set the repository variable AUTO_DEPLOY to "false".
MSG
}
trap 'rc=$?; [ $rc -ne 0 ] && on_failure; exit $rc' EXIT

echo "Uploading ${sha} to ${service} (${environment})"
railway up --ci --service "$service" --environment "$environment" --message "$message"

deadline=$((SECONDS + ${DEPLOY_TIMEOUT:-1500}))
while true; do
  status=$(railway deployment list --service "$service" --environment "$environment" --json |
    jq -r --arg m "$message" '[.[] | select((.meta.cliMessage // "") == $m)] | first | .status // "NOT-LISTED"')
  echo "$(date +%T) ${service}: ${status}"
  case "$status" in
    SUCCESS)
      echo "${service} is live on ${sha}" | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
      exit 0
      ;;
    FAILED | CRASHED | REMOVED | SKIPPED)
      echo "deployment ended as ${status}" >&2
      exit 1
      ;;
  esac
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "timed out waiting for the deployment" >&2
    exit 2
  fi
  sleep 15
done

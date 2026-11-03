#!/usr/bin/env bash
# Which Railway services does a change affect? Prints two lines, `api=true|false` and `web=true|false`.
#
#   scripts/ci/changed-services.sh <before-sha> <after-sha>
#
# The API owns backend/ (the schema migrations that run before it takes traffic live there too) and the
# repo-root railway.toml. The web app owns frontend/ (its Dockerfile and railway.toml are inside it).
# Anything else (docs, CI files, scripts) deploys nothing. With no usable <before-sha> (an empty or
# all-zero value, or a commit this clone does not have) every file counts, so nothing is missed.
set -euo pipefail

before=${1:?usage: changed-services.sh <before-sha> <after-sha>}
after=${2:?usage: changed-services.sh <before-sha> <after-sha>}
zeros=0000000000000000000000000000000000000000

if [ "$before" = "$zeros" ] || ! git cat-file -e "${before}^{commit}" 2>/dev/null; then
  files=$(git ls-tree -r --name-only "$after")
else
  files=$(git diff --name-only "$before" "$after")
fi

api=false
web=false
if echo "$files" | grep -qE '^(backend/|railway\.toml$)'; then api=true; fi
if echo "$files" | grep -qE '^frontend/'; then web=true; fi

echo "api=$api"
echo "web=$web"

#!/usr/bin/env bash
# Smoke-test a live service after a deploy. Exits non-zero, naming what failed, if anything is wrong.
#
#   scripts/ci/smoke.sh web|api
#
# Addresses come from WEB_URL / API_URL (no trailing slash). Each request is retried for a while,
# because a freshly deployed service can need a few seconds before it answers.
set -uo pipefail

WEB_URL=${WEB_URL:-https://voice.shantanudas.dev}
API_URL=${API_URL:-https://voice-api.shantanudas.dev}
failures=0

ok() { echo "ok    $1"; }
bad() { echo "FAIL  $1" >&2; failures=$((failures + 1)); }

# fetch <url> <headers-file> <body-file>: GET with up to SMOKE_TRIES tries (default 12), SMOKE_DELAY
# seconds apart (default 10); prints the HTTP code.
fetch() {
  local code="000" try
  for try in $(seq 1 "${SMOKE_TRIES:-12}"); do
    code=$(curl -sS -m 20 -D "$2" -o "$3" -w '%{http_code}' "$1" 2>/dev/null || echo 000)
    [ "$code" = "200" ] && break
    [ "$try" -lt "${SMOKE_TRIES:-12}" ] && sleep "${SMOKE_DELAY:-10}"
  done
  echo "$code"
}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

case "${1:-}" in
  web)
    code=$(fetch "$WEB_URL/login" "$tmp/h" "$tmp/b")
    [ "$code" = "200" ] && ok "/login answers 200" || bad "/login answered $code"
    grep -qi '^strict-transport-security:' "$tmp/h" && ok "HSTS header present" || bad "HSTS header missing"
    grep -qi '^x-content-type-options: nosniff' "$tmp/h" && ok "nosniff header present" || bad "nosniff header missing"
    grep -qi '^content-security-policy' "$tmp/h" && ok "CSP header present" || bad "CSP header missing"

    code=$(fetch "$WEB_URL/" "$tmp/h" "$tmp/b")
    if [ "$code" = "200" ] && grep -q 'Clone a voice' "$tmp/b" && grep -q 'Hear a sample' "$tmp/b"; then
      ok "home page renders its hero and sample card"
    else
      bad "home page: status $code or hero content missing"
    fi

    code=$(fetch "$WEB_URL/samples/home-sample.wav" "$tmp/h" "$tmp/b")
    if [ "$code" = "200" ] && grep -qi '^content-type: audio/' "$tmp/h"; then
      ok "sample clip served as audio"
    else
      bad "sample clip: status $code or not audio"
    fi
    ;;
  api)
    code=$(fetch "$API_URL/health/ready" "$tmp/h" "$tmp/b")
    [ "$code" = "200" ] && ok "/health/ready answers 200" || bad "/health/ready answered $code"
    grep -q '"status":"ok"' "$tmp/b" && ok "readiness status is ok" || bad "readiness status is not ok"
    grep -q '"database":{"ok":true}' "$tmp/b" && ok "database reachable" || bad "database not reachable"
    ;;
  *)
    echo "usage: smoke.sh web|api" >&2
    exit 64
    ;;
esac

if [ "$failures" -gt 0 ]; then
  echo "$failures smoke check(s) failed" >&2
  exit 1
fi
echo "smoke checks passed"

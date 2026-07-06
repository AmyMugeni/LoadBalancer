#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:5000}"

fail() {
  echo "[FAIL] $1"
  exit 1
}

pass() {
  echo "[PASS] $1"
}

request() {
  local method="$1"
  local url="$2"
  local data="${3:-}"

  local body_file
  body_file="$(mktemp)"

  local code
  if [[ -n "$data" ]]; then
    code="$(curl -sS -o "$body_file" -w "%{http_code}" -X "$method" "$url" -H "Content-Type: application/json" -d "$data")"
  else
    code="$(curl -sS -o "$body_file" -w "%{http_code}" -X "$method" "$url")"
  fi

  cat "$body_file"
  rm -f "$body_file"
  printf "\nHTTP_STATUS=%s\n" "$code"
}

extract_status() {
  sed -n 's/^HTTP_STATUS=//p' | tail -n1
}

extract_body() {
  sed '/^HTTP_STATUS=/d'
}

echo "Waiting for load balancer at ${BASE_URL} ..."
for _ in {1..40}; do
  if curl -sS "${BASE_URL}/rep" >/dev/null 2>&1; then
    pass "Load balancer is reachable"
    break
  fi
  sleep 1
done

resp="$(request GET "${BASE_URL}/rep")"
status="$(printf "%s" "$resp" | extract_status)"
body="$(printf "%s" "$resp" | extract_body)"
[[ "$status" == "200" ]] || fail "/rep expected 200, got $status"
printf "%s" "$body" | grep -q '"status":"successful"' || fail "/rep did not return successful status"
pass "GET /rep"

resp="$(request GET "${BASE_URL}/home?request_id=123")"
status="$(printf "%s" "$resp" | extract_status)"
body="$(printf "%s" "$resp" | extract_body)"
[[ "$status" == "200" ]] || fail "/home expected 200, got $status"
printf "%s" "$body" | grep -q 'Hello from Server' || fail "/home did not route to backend"
pass "GET /home routes through LB"

resp="$(request GET "${BASE_URL}/not-registered?request_id=123")"
status="$(printf "%s" "$resp" | extract_status)"
[[ "$status" == "404" ]] || fail "unknown backend path expected 404, got $status"
pass "GET /<unknown-path> returns backend 404"

resp="$(request POST "${BASE_URL}/add" '{"n":1,"hostnames":[]}')"
status="$(printf "%s" "$resp" | extract_status)"
body="$(printf "%s" "$resp" | extract_body)"
[[ "$status" == "200" ]] || fail "/add expected 200, got $status"
printf "%s" "$body" | grep -q '"created"' || fail "/add response missing created list"
pass "POST /add"

resp="$(request DELETE "${BASE_URL}/rm" '{"n":1,"hostnames":[]}')"
status="$(printf "%s" "$resp" | extract_status)"
body="$(printf "%s" "$resp" | extract_body)"
[[ "$status" == "200" ]] || fail "/rm expected 200, got $status"
printf "%s" "$body" | grep -q '"removed"' || fail "/rm response missing removed list"
pass "DELETE /rm"

resp="$(request DELETE "${BASE_URL}/rm" '{"n":1,"hostnames":["a","b"]}')"
status="$(printf "%s" "$resp" | extract_status)"
[[ "$status" == "400" ]] || fail "invalid /rm payload expected 400, got $status"
pass "DELETE /rm sanity check (hostnames length > n)"

echo "All integration checks passed."

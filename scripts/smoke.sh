#!/usr/bin/env bash
# End-to-end smoke test THROUGH THE GATEWAY. Needs the stack running: make up
# It also follows one request id across gateway -> wallet-service -> notification-service logs.
#
# It creates two users and an ADMIN account (smoke-*@example.com) with a random password that exists
# only for this run, and DEACTIVATES all of them when it finishes (also when it fails). Still: prefer
# staging over production, and never reuse a fixed password for an admin.
set -euo pipefail
cd "$(dirname "$0")/.."

GATEWAY="${GATEWAY_URL:-http://localhost:8080}"
PROMETHEUS="${PROMETHEUS_URL:-http://localhost:9090}"
STAMP="$(date +%s)"
PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"   # random per run
TRACE="smoke-trace-${STAMP}"

cleanup() {
  # Deactivate every smoke account: they can no longer log in or use /auth/me.
  # (A token already issued stays valid in wallet-service until it expires, 30 minutes by default.)
  local pg_user
  pg_user="${POSTGRES_USER:-$(grep -E '^POSTGRES_USER=' .env 2>/dev/null | cut -d= -f2- || true)}"
  [ -n "$pg_user" ] && docker compose exec -T postgres psql -U "$pg_user" -d auth_db -q \
    -c "UPDATE users SET is_active = FALSE WHERE email LIKE 'smoke-%@example.com'" >/dev/null 2>&1 \
    && printf '  cleanup: smoke accounts deactivated\n' || printf '  cleanup: could not deactivate smoke accounts, do it by hand\n'
}
trap cleanup EXIT

ok()   { printf '  \033[32mOK\033[0m    %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; exit 1; }
field() { python3 -c "import sys, json; print(json.load(sys.stdin)$1)"; }   # field '["access_token"]'
header() { tr -d '\r' | grep -i "^$1:" | head -1 | cut -d' ' -f2-; }          # read one response header
post_json() { curl -fsS -X POST "$1" -H 'Content-Type: application/json' "${@:3}" -d "$2"; }
login() { post_json "$GATEWAY/auth/login" "{\"email\":\"$1\",\"password\":\"$PASSWORD\"}" | field '["access_token"]'; }

echo "Gateway"
curl -fsS "$GATEWAY/health" | grep -q '"gateway"' || fail "gateway /health"
ok "gateway is up"

echoed="$(curl -si -H "X-Request-ID: smoke-echo-${STAMP}" "$GATEWAY/health" | header x-request-id)"
[ "$echoed" = "smoke-echo-${STAMP}" ] || fail "a valid X-Request-ID should be echoed (got '$echoed')"
ok "a valid X-Request-ID is kept and echoed"

generated="$(curl -si "$GATEWAY/health" | header x-request-id)"
[ "${#generated}" -eq 32 ] || fail "a request id should be generated when missing (got '$generated')"
ok "a missing X-Request-ID is generated ($generated)"

replaced="$(curl -si -H 'X-Request-ID: not valid!' "$GATEWAY/health" | header x-request-id)"
[ "$replaced" != "not valid!" ] && [ "${#replaced}" -eq 32 ] || fail "an unsafe X-Request-ID should be replaced"
ok "an unsafe X-Request-ID is replaced"

[ "$(curl -s -o /dev/null -w '%{http_code}' "$GATEWAY/metrics")" = "404" ] || fail "/metrics must not be reachable through the gateway"
ok "/metrics is not exposed publicly"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$GATEWAY/nope")" = "404" ] || fail "unknown routes should 404"
ok "unknown routes return 404"

echo "Flow through the gateway (request id: $TRACE)"
ALICE="smoke-alice-${STAMP}@example.com"; BOB="smoke-bob-${STAMP}@example.com"; ADMIN="smoke-admin-${STAMP}@example.com"
post_json "$GATEWAY/auth/register" "{\"email\":\"$ALICE\",\"password\":\"$PASSWORD\"}" >/dev/null
post_json "$GATEWAY/auth/register" "{\"email\":\"$BOB\",\"password\":\"$PASSWORD\"}" >/dev/null
docker compose exec -T -e ADMIN_PASSWORD="$PASSWORD" auth-service python -m app.create_admin --email "$ADMIN" >/dev/null
ALICE_TOKEN="$(login "$ALICE")"; BOB_TOKEN="$(login "$BOB")"; ADMIN_TOKEN="$(login "$ADMIN")"
ok "registered two users and an admin, logged in via /auth"

ALICE_WALLET="$(post_json "$GATEWAY/wallets" '{}' -H "Authorization: Bearer $ALICE_TOKEN" | field '["id"]')"
BOB_WALLET="$(post_json "$GATEWAY/wallets" '{}' -H "Authorization: Bearer $BOB_TOKEN" | field '["id"]')"
post_json "$GATEWAY/wallets/$ALICE_WALLET/deposit" '{"amount":100000}' -H "Authorization: Bearer $ADMIN_TOKEN" >/dev/null
ok "wallets created through /wallets, admin deposit made"

response_id="$(curl -si -X POST "$GATEWAY/transfers" \
  -H "Authorization: Bearer $ALICE_TOKEN" -H "Idempotency-Key: smoke-key-${STAMP}" \
  -H "X-Request-ID: $TRACE" -H 'Content-Type: application/json' \
  -d "{\"to_wallet_id\":\"$BOB_WALLET\",\"amount\":12000}" | header x-request-id)"
[ "$response_id" = "$TRACE" ] || fail "transfer response should echo the request id (got '$response_id')"
ok "transfer accepted; the response carries $TRACE"

echo "Event pipeline: outbox -> RabbitMQ -> notification-service"
for _ in $(seq 1 20); do
  if curl -fsS "$GATEWAY/notifications" -H "Authorization: Bearer $BOB_TOKEN" | grep -q 'You received INR 120.00'; then found=1; break; fi
  sleep 1
done
[ "${found:-0}" = "1" ] || fail "Bob never got his notification (check: docker compose logs wallet-service notification-service)"
ok "Bob received 'You received INR 120.00' via /notifications"

echo "Request id $TRACE in each service's logs"
for service in gateway wallet-service notification-service; do
  docker compose logs --no-color "$service" 2>/dev/null | grep -q "$TRACE" || fail "$TRACE not found in $service logs"
  ok "found in $service"
done

echo "Prometheus"
for _ in $(seq 1 12); do
  up="$(curl -fsS "$PROMETHEUS/api/v1/query" --data-urlencode 'query=sum(up{job=~".+-service"})' | field '["data"]["result"][0]["value"][1]' 2>/dev/null || echo 0)"
  [ "$up" = "3" ] && break
  sleep 2
done
[ "$up" = "3" ] || fail "expected 3 scrape targets up, got $up"
ok "all 3 services are being scraped"

echo "Gateway rate limit on /auth (this uses up the burst: wait a minute before re-running)"
limited=0
for _ in $(seq 1 25); do
  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$GATEWAY/auth/login" -H 'Content-Type: application/json' -d '{"email":"nobody@example.com","password":"wrong-password"}')"
  [ "$code" = "429" ] && limited=1 && break
done
[ "$limited" = "1" ] || fail "expected a 429 from the gateway after rapid /auth requests"
ok "rapid /auth requests are answered with 429"

echo "All checks passed."

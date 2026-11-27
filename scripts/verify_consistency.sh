#!/usr/bin/env bash
# Verifies data consistency (run it after a load test, or any time): make verify
#  1. scripts/verify_consistency.sql against wallet_db (ledger sums to zero, no negative balances, ...)
#  2. end to end: every committed transfer reached RabbitMQ exactly once and produced exactly the
#     expected notifications in notification_db; nothing is parked in a dead-letter queue.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="${COMPOSE:-docker compose}"
PG_USER="${POSTGRES_USER:-$(grep -E '^POSTGRES_USER=' .env 2>/dev/null | cut -d= -f2- || true)}"
[ -n "$PG_USER" ] || { echo "POSTGRES_USER not found: set it or run from the repo root with a .env"; exit 2; }
WAIT_SECONDS="${WAIT_SECONDS:-60}"

psql_db() { $COMPOSE exec -T postgres psql -U "$PG_USER" -d "$1" -v ON_ERROR_STOP=1 -At -F '|' "${@:2}"; }
scalar()  { psql_db "$1" -c "$2" | tr -d '[:space:]'; }
expected_notifications() {
  scalar wallet_db "SELECT count(*) FILTER (WHERE type = 'transfer') * 2 + count(*) FILTER (WHERE type = 'deposit') FROM transfers"
}

failures=0
report() {  # name violations detail
  case "$1" in
    info_*) printf '  \033[36mINFO\033[0m  %-40s %s\n' "$1" "$3" ;;
    *) if [ "$2" = "0" ]; then
         printf '  \033[32mPASS\033[0m  %-40s %s\n' "$1" "$3"
       else
         printf '  \033[31mFAIL\033[0m  %-40s %s  [violations: %s]\n' "$1" "$3" "$2"
         failures=$((failures + 1))
       fi ;;
  esac
}

echo "Waiting up to ${WAIT_SECONDS}s for the event pipeline to drain (outbox -> RabbitMQ -> notifications)..."
deadline=$((SECONDS + WAIT_SECONDS))
while true; do
  backlog="$(scalar wallet_db 'SELECT count(*) FROM outbox_events WHERE published_at IS NULL')"
  expected="$(expected_notifications)"
  actual="$(scalar notification_db 'SELECT count(*) FROM notifications')"
  if [ "$backlog" = "0" ] && [ "$expected" = "$actual" ]; then break; fi
  [ "$SECONDS" -ge "$deadline" ] && break
  sleep 2
done

echo
echo "wallet_db: ledger and balance invariants"
rows="$(psql_db wallet_db < scripts/verify_consistency.sql)"
while IFS='|' read -r name violations detail; do
  report "$name" "$violations" "$detail"
done <<< "$rows"

echo
echo "End to end: wallet-service -> RabbitMQ -> notification-service"
published="$(scalar wallet_db 'SELECT count(*) FROM outbox_events WHERE published_at IS NOT NULL')"
processed="$(scalar notification_db 'SELECT count(*) FROM processed_events')"
dlq="$($COMPOSE exec -T rabbitmq rabbitmqctl -q list_queues name messages | awk '$1 ~ /\.dlq$/ {sum += $2} END {print sum + 0}')"
report outbox_drained "$([ "$backlog" = "0" ] && echo 0 || echo 1)" "$backlog events still unpublished"
report events_processed_exactly_once "$([ "$published" = "$processed" ] && echo 0 || echo 1)" "published=$published, processed by the consumer=$processed"
report notifications_match_ledger "$([ "$expected" = "$actual" ] && echo 0 || echo 1)" "expected=$expected (2 per transfer + 1 per deposit), found=$actual"
report dead_letter_queues_empty "$([ "$dlq" = "0" ] && echo 0 || echo 1)" "$dlq messages parked in dead-letter queues"

echo
if [ "$failures" -eq 0 ]; then
  printf '\033[32mAll consistency checks passed.\033[0m\n'
else
  printf '\033[31m%s consistency check(s) FAILED.\033[0m\n' "$failures"
  exit 1
fi

from prometheus_client import Counter, Gauge, Histogram

# ---- HTTP (identical in every service; Prometheus adds the `job` label = service name) ----------
# `route` is the route TEMPLATE ("/wallets/{wallet_id}/deposit"), never the raw path, so the number
# of time series stays small no matter how many different ids clients send.
HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests handled.", ["method", "route", "status"]
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds", "HTTP request latency in seconds.", ["method", "route"]
)
HTTP_IN_PROGRESS = Gauge("http_requests_in_progress", "HTTP requests currently being handled.")
APP_ERRORS = Counter(
    "app_errors_total", "Business errors returned to clients, by error code.", ["code", "status"]
)

# ---- money ---------------------------------------------------------------------------------------
# Incremented AFTER the transaction commits, so a rolled-back transfer is never counted.
TRANSFERS = Counter("wallet_transfers_total", "Committed money movements.", ["type"])
TRANSFER_AMOUNT = Counter(
    "wallet_transfer_amount_paise_total", "Paise moved by committed transfers.", ["type"]
)
IDEMPOTENT_REPLAYS = Counter(
    "wallet_idempotent_replays_total", "Transfer requests answered from a stored response."
)
FRAUD_FLAGS = Counter("wallet_fraud_flags_total", "Transfer-velocity fraud flags raised.")

# ---- Redis features ------------------------------------------------------------------------------
RATE_LIMITED = Counter(
    "wallet_rate_limited_total", "Requests rejected by the rate limiter.", ["scope"]
)
BALANCE_CACHE = Counter(
    "wallet_balance_cache_total",
    "Balance reads by cache result (unavailable = Redis down or disabled).",
    ["result"],
)
REDIS_FAILURES = Counter(
    "wallet_redis_failures_total", "Redis operations that failed (and fell back).", ["operation"]
)

# ---- outbox --------------------------------------------------------------------------------------
OUTBOX_PUBLISHED = Counter("wallet_outbox_published_total", "Events published to RabbitMQ.")
OUTBOX_PUBLISH_FAILURES = Counter(
    "wallet_outbox_publish_failures_total", "Publish attempts that failed (events stay queued)."
)
OUTBOX_BACKLOG = Gauge("wallet_outbox_backlog", "Outbox events not yet published to RabbitMQ.")
OUTBOX_OLDEST_AGE = Gauge(
    "wallet_outbox_oldest_unpublished_age_seconds", "Age of the oldest unpublished outbox event."
)

for _type in ("transfer", "deposit"):
    TRANSFERS.labels(type=_type)
    TRANSFER_AMOUNT.labels(type=_type)
for _scope in ("transfers", "reads"):
    RATE_LIMITED.labels(scope=_scope)
for _result in ("hit", "miss", "unavailable"):
    BALANCE_CACHE.labels(result=_result)

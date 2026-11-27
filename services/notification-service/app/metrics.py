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

# ---- consumer ------------------------------------------------------------------------------------
EVENTS = Counter(
    "notification_events_total",
    "Events handled by the consumer. outcome: processed, duplicate, retried, dead_lettered.",
    ["outcome"],
)
QUEUE_DEPTH = Gauge(
    "notification_queue_depth",
    "Messages waiting (ready, not yet delivered) per queue: main, retry (all retry queues), dlq.",
    ["queue"],
)
CONSUMER_CONNECTED = Gauge(
    "notification_consumer_connected", "1 while the consumer is attached to RabbitMQ."
)
for _outcome in ("processed", "duplicate", "retried", "dead_lettered"):
    EVENTS.labels(outcome=_outcome)
for _queue in ("main", "retry", "dlq"):
    QUEUE_DEPTH.labels(queue=_queue)

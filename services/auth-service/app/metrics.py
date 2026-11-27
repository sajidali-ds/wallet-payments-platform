from prometheus_client import Counter, Gauge, Histogram

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

REGISTRATIONS = Counter("auth_registrations_total", "Accounts created.")
LOGINS = Counter("auth_logins_total", "Login attempts, by result.", ["result"])
for _result in ("success", "failed", "disabled"):
    LOGINS.labels(result=_result)  # create the series at 0 so rate() works from the start

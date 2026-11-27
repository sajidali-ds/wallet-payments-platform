import time

from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.metrics import HTTP_DURATION, HTTP_IN_PROGRESS, HTTP_REQUESTS

# Probes and scrapes are not user traffic: counting them would drown the real numbers.
EXCLUDED_PATHS = {"/metrics", "/health"}


def route_template(scope: Scope) -> str:
    route = scope.get("route")
    if route is not None and hasattr(route, "path"):
        return route.path
    app = scope.get("app")
    if app is not None:
        for candidate in app.router.routes:
            match, _ = candidate.matches(scope)
            if match == Match.FULL:
                return getattr(candidate, "path", "unmatched")
    return "unmatched"


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in EXCLUDED_PATHS:
            await self.app(scope, receive, send)
            return

        status_code = 500  # what the client gets if the app raises before responding

        async def send_and_capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        HTTP_IN_PROGRESS.inc()
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_and_capture_status)
        finally:
            elapsed = time.perf_counter() - start
            HTTP_IN_PROGRESS.dec()
            method, route = scope["method"], route_template(scope)
            HTTP_REQUESTS.labels(method=method, route=route, status=str(status_code)).inc()
            HTTP_DURATION.labels(method=method, route=route).observe(elapsed)

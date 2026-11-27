import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = structlog.get_logger()

# Only accept a sane incoming ID, so a client cannot stuff junk into our logs.
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get("x-request-id", "")
        request_id = incoming if _VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id, method=scope["method"], path=scope["path"]
        )

        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            log.exception("request_unhandled_error")
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            emit = log.debug if scope["path"] == "/health" else log.info  # keep probes quiet
            emit("request_completed", status=status_code, duration_ms=duration_ms)
            structlog.contextvars.clear_contextvars()

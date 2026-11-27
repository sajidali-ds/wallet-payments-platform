import structlog
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.middleware.request_id import RequestIdMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        # Proves the ID is bound into the logging context while the endpoint runs.
        return {"bound_id": structlog.contextvars.get_contextvars()["request_id"]}

    return app


async def _get(headers: dict[str, str] | None = None):
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as client:
        return await client.get("/ping", headers=headers)


async def test_generates_request_id_when_missing():
    response = await _get()
    request_id = response.headers["x-request-id"]
    assert len(request_id) == 32
    assert response.json()["bound_id"] == request_id


async def test_keeps_valid_incoming_request_id():
    response = await _get({"X-Request-ID": "trace-abc.123"})
    assert response.headers["x-request-id"] == "trace-abc.123"
    assert response.json()["bound_id"] == "trace-abc.123"


async def test_replaces_unsafe_incoming_request_id():
    response = await _get({"X-Request-ID": "bad id with spaces!"})
    assert response.headers["x-request-id"] != "bad id with spaces!"

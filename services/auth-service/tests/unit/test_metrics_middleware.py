from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY

from app.middleware.metrics import MetricsMiddleware


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/items/{item_id}")
    async def item(item_id: int) -> dict[str, int]:
        return {"id": item_id}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("a bug")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics() -> dict[str, str]:
        return {}

    return app


async def _get(path: str):
    # raise_app_exceptions=False: an unhandled error becomes the 500 response a client would see.
    transport = ASGITransport(app=_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_requests_are_counted_by_route_template_not_raw_path():
    labels = {"method": "GET", "route": "/items/{item_id}", "status": "200"}
    before = sample("http_requests_total", **labels)

    for item_id in (1, 2, 3):
        await _get(f"/items/{item_id}")

    assert sample("http_requests_total", **labels) - before == 3
    # One series for the template; no series per id (that would grow without bound).
    assert REGISTRY.get_sample_value(
        "http_requests_total", {"method": "GET", "route": "/items/1", "status": "200"}
    ) is None


async def test_latency_is_recorded_in_a_histogram():
    labels = {"method": "GET", "route": "/items/{item_id}"}
    before = sample("http_request_duration_seconds_count", **labels)
    await _get("/items/7")
    assert sample("http_request_duration_seconds_count", **labels) - before == 1
    assert sample("http_request_duration_seconds_bucket", le="+Inf", **labels) >= 1


async def test_unhandled_exceptions_are_counted_as_500():
    labels = {"method": "GET", "route": "/boom", "status": "500"}
    before = sample("http_requests_total", **labels)
    response = await _get("/boom")
    assert response.status_code == 500
    assert sample("http_requests_total", **labels) - before == 1


async def test_unknown_paths_share_a_single_unmatched_series():
    labels = {"method": "GET", "route": "unmatched", "status": "404"}
    before = sample("http_requests_total", **labels)
    await _get("/scanner-probe-1")
    await _get("/scanner-probe-2")
    assert sample("http_requests_total", **labels) - before == 2


async def test_health_and_metrics_requests_are_not_counted():
    for path in ("/health", "/metrics"):
        await _get(path)
        assert REGISTRY.get_sample_value(
            "http_requests_total", {"method": "GET", "route": path, "status": "200"}
        ) is None


async def test_in_progress_gauge_returns_to_zero():
    await _get("/items/1")
    assert sample("http_requests_in_progress") == 0

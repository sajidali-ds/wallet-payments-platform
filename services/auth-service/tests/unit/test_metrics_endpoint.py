from httpx import ASGITransport, AsyncClient

from app.main import create_app


async def test_metrics_endpoint_exposes_prometheus_text():
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        response = await c.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    for name in ("http_request_duration_seconds", "auth_logins_total", "app_errors_total"):
        assert name in response.text

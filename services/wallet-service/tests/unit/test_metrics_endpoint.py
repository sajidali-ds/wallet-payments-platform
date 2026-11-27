from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY

from app.main import create_app


class FakePool:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def fetchrow(self, query: str, *args, timeout: float | None = None):  # noqa: ASYNC109
        if self.error:
            raise self.error
        return {"backlog": 7, "oldest_age": 12.5}


async def _scrape(pool: FakePool):
    app = create_app()
    app.state.pool = pool
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/metrics")


async def test_scrape_refreshes_the_outbox_gauges_from_the_database():
    response = await _scrape(FakePool())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert REGISTRY.get_sample_value("wallet_outbox_backlog") == 7
    assert REGISTRY.get_sample_value("wallet_outbox_oldest_unpublished_age_seconds") == 12.5
    for name in ("wallet_transfers_total", "wallet_balance_cache_total", "http_requests_total"):
        assert name in response.text


async def test_scrape_still_works_when_the_database_is_down():
    response = await _scrape(FakePool(error=ConnectionError("db down")))
    assert response.status_code == 200  # Prometheus must still get every other metric
    assert "wallet_outbox_backlog" in response.text

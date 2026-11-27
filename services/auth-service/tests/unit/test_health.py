from httpx import ASGITransport, AsyncClient

from app.main import create_app


class FakePool:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def fetchval(self, query: str, timeout: float | None = None) -> int:  # noqa: ASYNC109
        if self.error:
            raise self.error
        return 1


async def _health(pool: FakePool):
    app = create_app()
    app.state.pool = pool  # no lifespan in this test, so we plug in the fake pool ourselves
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/health")


async def test_health_ok_when_database_answers():
    response = await _health(FakePool())
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "auth-service",
        "checks": {"postgres": "ok"},
    }


async def test_health_503_when_database_is_down():
    response = await _health(FakePool(error=ConnectionError("db down")))
    assert response.status_code == 503
    assert response.json()["checks"]["postgres"] == "unavailable"

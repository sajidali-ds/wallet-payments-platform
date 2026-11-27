from httpx import ASGITransport, AsyncClient

from app.main import create_app


class FakePool:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def fetchval(self, query: str, timeout: float | None = None) -> int: # noqa: ASYNC109
        if self.error:
            raise self.error
        return 1


class FakeConsumer:
    is_running = True


async def _health(pool: FakePool, consumer=None):
    app = create_app()
    app.state.pool = pool
    if consumer is not None:
        app.state.consumer = consumer
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/health")


async def test_health_ok_and_reports_consumer_state():
    response = await _health(FakePool(), FakeConsumer())
    assert response.status_code == 200
    assert response.json()["checks"] == {"postgres": "ok", "rabbitmq": "consuming"}


async def test_health_stays_200_when_only_rabbitmq_is_disconnected():
    response = await _health(FakePool())  # no consumer attached
    assert response.status_code == 200
    assert response.json()["checks"]["rabbitmq"] == "disconnected"


async def test_health_503_when_database_is_down():
    response = await _health(FakePool(error=ConnectionError("db down")), FakeConsumer())
    assert response.status_code == 503
    assert response.json()["checks"]["postgres"] == "unavailable"

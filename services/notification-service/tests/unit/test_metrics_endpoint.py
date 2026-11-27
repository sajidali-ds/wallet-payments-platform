from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY

from app.main import create_app


class StubConsumer:
    is_running = True

    async def queue_depths(self):
        return {"main": 4, "retry": 2, "dlq": 1}


async def _scrape(consumer=None):
    app = create_app()
    if consumer is not None:
        app.state.consumer = consumer
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get("/metrics")


async def test_scrape_reports_queue_depth_and_connection_state():
    response = await _scrape(StubConsumer())

    assert response.status_code == 200
    assert REGISTRY.get_sample_value("notification_queue_depth", {"queue": "main"}) == 4
    assert REGISTRY.get_sample_value("notification_queue_depth", {"queue": "retry"}) == 2
    assert REGISTRY.get_sample_value("notification_queue_depth", {"queue": "dlq"}) == 1
    assert REGISTRY.get_sample_value("notification_consumer_connected") == 1


async def test_scrape_works_without_a_consumer():
    response = await _scrape()
    assert response.status_code == 200
    assert REGISTRY.get_sample_value("notification_consumer_connected") == 0

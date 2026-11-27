from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.consumers.transfer_consumer import TransferEventConsumer
from app.metrics import CONSUMER_CONNECTED, QUEUE_DEPTH

router = APIRouter()


async def refresh_queue_gauges(consumer: TransferEventConsumer | None) -> None:
    """Queue depth lives in RabbitMQ, so the gauges are refreshed when Prometheus scrapes."""
    CONSUMER_CONNECTED.set(1 if consumer is not None and consumer.is_running else 0)
    if consumer is None:
        return
    depths = await consumer.queue_depths()
    if depths is not None:  # None = RabbitMQ unreachable: keep the last known values
        for queue, count in depths.items():
            QUEUE_DEPTH.labels(queue=queue).set(count)


# Not routed by the gateway, so it is reachable only inside the Docker network (Prometheus).
@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    await refresh_queue_gauges(getattr(request.app.state, "consumer", None))
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

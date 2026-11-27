import structlog
from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.metrics import OUTBOX_BACKLOG, OUTBOX_OLDEST_AGE
from app.repositories import outbox_repository

router = APIRouter()
log = structlog.get_logger()


async def refresh_outbox_gauges(pool) -> None:
    """The backlog lives in Postgres, so the gauges are refreshed when Prometheus scrapes."""
    try:
        stats = await outbox_repository.backlog_stats(pool)
    except Exception as exc:
        log.warning("metrics_outbox_query_failed", error=repr(exc))
        return  # keep serving the other metrics; the gauges keep their last values
    OUTBOX_BACKLOG.set(stats["backlog"])
    OUTBOX_OLDEST_AGE.set(stats["oldest_age"])


# Not routed by the gateway, so it is reachable only inside the Docker network (Prometheus).
@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    await refresh_outbox_gauges(request.app.state.pool)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

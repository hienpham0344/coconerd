"""Database availability and worker freshness policy."""

import logging
from datetime import UTC, datetime, timedelta

from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import HealthResult

logger = logging.getLogger(__name__)


async def get_health(uow: UnitOfWork, worker_poll_seconds: float) -> HealthResult:
    try:
        await uow.health.probe()
        # The availability probe finishes its read transaction before the heartbeat read.
        await uow.rollback()
    except Exception as exc:
        logger.exception("Database health check failed", extra={"error_type": type(exc).__name__})
        return HealthResult("degraded", "unavailable", "unknown")
    cutoff = datetime.now(UTC) - timedelta(seconds=max(10, worker_poll_seconds * 5))
    heartbeat = await uow.health.has_recent_worker(cutoff)
    return HealthResult(
        "ok" if heartbeat else "degraded", "ok", "ok" if heartbeat else "unavailable"
    )


async def record_heartbeat(uow: UnitOfWork, worker_id: str, status: str) -> None:
    await uow.health.record_heartbeat(worker_id, status, datetime.now(UTC))
    await uow.commit()

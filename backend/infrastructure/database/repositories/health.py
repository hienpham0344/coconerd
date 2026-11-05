"""Database availability and heartbeat queries."""

from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.infrastructure.database.models import WorkerHeartbeatRecord
from backend.infrastructure.database.statements import conflict_insert


class HealthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_heartbeat(self, worker_id: str, status: str, seen_at: datetime) -> None:
        await self.session.execute(
            conflict_insert(self.session, WorkerHeartbeatRecord)
            .values(worker_id=worker_id, status=status, last_seen_at=seen_at)
            .on_conflict_do_update(
                index_elements=["worker_id"], set_={"status": status, "last_seen_at": seen_at}
            )
        )

    async def probe(self) -> None:
        await self.session.execute(text("SELECT 1"))

    async def has_recent_worker(self, cutoff: datetime) -> bool:
        return (
            await self.session.scalar(
                select(WorkerHeartbeatRecord.worker_id)
                .where(
                    WorkerHeartbeatRecord.status.in_(["running", "idle"]),
                    WorkerHeartbeatRecord.last_seen_at >= cutoff,
                )
                .order_by(WorkerHeartbeatRecord.last_seen_at.desc())
                .limit(1)
            )
            is not None
        )

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.infrastructure.database.models import DeliveryReceiptRecord
from backend.infrastructure.database.statements import conflict_insert


class DeliveryReceiptRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str) -> str | None:
        return await self.session.scalar(
            select(DeliveryReceiptRecord.discord_id).where(DeliveryReceiptRecord.key == key)
        )

    async def put(self, key: str, discord_id: str) -> None:
        now = datetime.now(UTC)
        await self.session.execute(
            conflict_insert(self.session, DeliveryReceiptRecord)
            .values(key=key, discord_id=discord_id, updated_at=now)
            .on_conflict_do_update(
                index_elements=["key"], set_={"discord_id": discord_id, "updated_at": now}
            )
        )

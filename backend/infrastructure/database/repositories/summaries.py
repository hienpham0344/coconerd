from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.read_models import SummaryReadModel
from backend.infrastructure.database.models import TopicRecord, TopicSummaryRecord
from backend.infrastructure.database.topic_index import index_topic


class SummaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest_read_model(self, guild_id: str, topic_id: str) -> SummaryReadModel | None:
        record = await self.latest(guild_id, topic_id)
        return _summary_read_model(record) if record is not None else None

    async def latest(self, guild_id: str, topic_id: str) -> TopicSummaryRecord | None:
        return await self.session.scalar(
            select(TopicSummaryRecord)
            .where(TopicSummaryRecord.guild_id == guild_id, TopicSummaryRecord.topic_id == topic_id)
            .order_by(TopicSummaryRecord.version.desc())
            .limit(1)
        )

    async def add_read_model(
        self,
        guild_id: str,
        topic_id: str,
        version: int,
        data: dict[str, object],
        source_message_ids: list[str],
    ) -> SummaryReadModel:
        record = await self.add(guild_id, topic_id, version, data, source_message_ids)
        return _summary_read_model(record)

    async def add(
        self,
        guild_id: str,
        topic_id: str,
        version: int,
        data: dict[str, object],
        source_message_ids: list[str],
    ) -> TopicSummaryRecord:
        record = TopicSummaryRecord(
            id=str(uuid4()),
            guild_id=guild_id,
            topic_id=topic_id,
            version=version,
            data=data,
            source_message_ids=source_message_ids,
        )
        self.session.add(record)
        topic = await self.session.scalar(
            select(TopicRecord).where(TopicRecord.id == topic_id, TopicRecord.guild_id == guild_id)
        )
        if topic is None:
            raise LookupError("Summary topic is missing or belongs to another guild")
        await index_topic(self.session, topic, data)
        return record


def _summary_read_model(record: TopicSummaryRecord) -> SummaryReadModel:
    return SummaryReadModel(
        id=record.id,
        guild_id=record.guild_id,
        topic_id=record.topic_id,
        version=record.version,
        data=record.data,
        source_message_ids=record.source_message_ids,
    )

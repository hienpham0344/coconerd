from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.read_models import TopicReadModel
from backend.application.topic_terms import search_terms
from backend.domain.entities import ConversationTopic
from backend.domain.enums import TopicStatus
from backend.infrastructure.database.models import (
    AIDecisionRecord,
    DiscordActionRecord,
    EpisodeRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    ProcessingJobRecord,
    ReviewEventRecord,
    TopicRecord,
    TopicSearchTermRecord,
    TopicSummaryRecord,
)
from backend.infrastructure.database.topic_index import index_topic


class TopicRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(self, guild_id: str, query: str, limit: int = 30) -> list[TopicReadModel]:
        terms = search_terms(query)
        if not terms or limit <= 0:
            return []
        records = await self.session.scalars(
            select(TopicRecord)
            .join(TopicSearchTermRecord)
            .where(
                TopicRecord.guild_id == guild_id,
                TopicSearchTermRecord.guild_id == guild_id,
                TopicRecord.status.in_(["ACTIVE", "DORMANT", "RESUMED"]),
                TopicSearchTermRecord.term.in_(terms),
            )
            .group_by(TopicRecord.id)
            .order_by(
                func.sum(TopicSearchTermRecord.weight).desc(),
                TopicRecord.last_activity_at.desc(),
                TopicRecord.id,
            )
            .limit(min(limit, 30))
        )
        return [_topic_read_model(record) for record in records]

    async def candidates_read_models(self, guild_id: str, limit: int = 30) -> list[TopicReadModel]:
        records = await self.candidates(guild_id, limit)
        return [_topic_read_model(record) for record in records]

    async def candidates(self, guild_id: str, limit: int = 30) -> list[TopicRecord]:
        result = await self.session.scalars(
            select(TopicRecord)
            .where(
                TopicRecord.guild_id == guild_id,
                TopicRecord.status.in_(
                    [TopicStatus.ACTIVE, TopicStatus.DORMANT, TopicStatus.RESUMED]
                ),
            )
            .order_by(TopicRecord.last_activity_at.desc())
            .limit(limit)
        )
        return list(result)

    async def get_read_model(self, guild_id: str, topic_id: str) -> TopicReadModel | None:
        record = await self.get(guild_id, topic_id)
        return _topic_read_model(record) if record is not None else None

    async def get(self, guild_id: str, topic_id: str) -> TopicRecord | None:
        return await self.session.scalar(
            select(TopicRecord).where(TopicRecord.guild_id == guild_id, TopicRecord.id == topic_id)
        )

    async def create_read_model(self, topic: ConversationTopic) -> TopicReadModel:
        record = await self.create(topic)
        return _topic_read_model(record)

    async def create(self, topic: ConversationTopic) -> TopicRecord:
        record = TopicRecord(
            id=topic.id,
            guild_id=topic.guild_id,
            title=topic.title,
            description=topic.description,
            status=topic.status.value,
            last_activity_at=topic.last_activity_at,
        )
        self.session.add(record)
        # Child rows are staged later in the same transaction; persist the parent first.
        await self.session.flush([record])
        await index_topic(self.session, record, {})
        return record

    async def set_status(self, guild_id: str, topic_id: str, status: str) -> None:
        result = await self.session.execute(
            update(TopicRecord)
            .where(TopicRecord.guild_id == guild_id, TopicRecord.id == topic_id)
            .values(status=status)
        )
        if result.rowcount != 1:
            raise RuntimeError("Topic changed concurrently; processing will be retried")

    async def add_episode(self, guild_id: str, topic_id: str, started_at: datetime) -> None:
        self.session.add(
            EpisodeRecord(
                id=str(uuid4()), guild_id=guild_id, topic_id=topic_id, started_at=started_at
            )
        )

    async def touch(
        self, guild_id: str, topic_id: str, expected_version: int, activity_at: datetime
    ) -> None:
        result = await self.session.execute(
            update(TopicRecord)
            .where(
                TopicRecord.guild_id == guild_id,
                TopicRecord.id == topic_id,
                TopicRecord.version == expected_version,
                TopicRecord.status.in_(["ACTIVE", "DORMANT", "RESUMED"]),
            )
            .values(version=expected_version + 1, last_activity_at=activity_at)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise RuntimeError("Topic changed concurrently; processing will be retried")

    async def list_for_guild_read_models(
        self, guild_id: str, limit: int, offset: int, status: str | None
    ) -> list[TopicReadModel]:
        records = await self.list_for_guild(guild_id, limit, offset, status)
        return [_topic_read_model(record) for record in records]

    async def list_for_guild(
        self, guild_id: str, limit: int, offset: int, status: str | None
    ) -> list[TopicRecord]:
        query = select(TopicRecord).where(TopicRecord.guild_id == guild_id)
        if status:
            query = query.where(TopicRecord.status == status)
        result = await self.session.scalars(
            query.order_by(TopicRecord.last_activity_at.desc()).limit(limit).offset(offset)
        )
        return list(result)

    async def inactive(self, cutoff: datetime) -> list[TopicReadModel]:
        records = await self.session.scalars(
            select(TopicRecord).where(
                TopicRecord.status == "ACTIVE", TopicRecord.last_activity_at < cutoff
            )
        )
        return [_topic_read_model(record) for record in records]

    async def close_latest_episode(self, guild_id: str, topic_id: str, ended_at: datetime) -> None:
        episode = await self.session.scalar(
            select(EpisodeRecord)
            .where(
                EpisodeRecord.guild_id == guild_id,
                EpisodeRecord.topic_id == topic_id,
                EpisodeRecord.ended_at.is_(None),
            )
            .order_by(EpisodeRecord.started_at.desc())
            .limit(1)
        )
        if episode is not None:
            episode.ended_at = ended_at

    async def set_thread(self, guild_id: str, topic_id: str, thread_id: str) -> None:
        await self.session.execute(
            update(TopicRecord)
            .where(TopicRecord.guild_id == guild_id, TopicRecord.id == topic_id)
            .values(discord_thread_id=thread_id)
        )

    async def delete_data(self, guild_id: str, topic_id: str) -> None:
        message_record_ids = select(MessageTopicAssociationRecord.message_record_id).where(
            MessageTopicAssociationRecord.guild_id == guild_id,
            MessageTopicAssociationRecord.topic_id == topic_id,
        )
        await self.session.execute(
            delete(ReviewEventRecord).where(
                ReviewEventRecord.guild_id == guild_id,
                (ReviewEventRecord.topic_id == topic_id)
                | ReviewEventRecord.message_record_id.in_(message_record_ids),
            )
        )
        await self.session.execute(
            delete(DiscordActionRecord).where(
                DiscordActionRecord.guild_id == guild_id, DiscordActionRecord.topic_id == topic_id
            )
        )
        await self.session.execute(
            delete(ProcessingJobRecord).where(
                ProcessingJobRecord.message_record_id.in_(message_record_ids)
            )
        )
        await self.session.execute(
            delete(AIDecisionRecord).where(
                AIDecisionRecord.message_record_id.in_(message_record_ids)
            )
        )
        await self.session.execute(
            delete(MessageRecord).where(MessageRecord.id.in_(message_record_ids))
        )
        await self.session.execute(
            delete(TopicSummaryRecord).where(
                TopicSummaryRecord.guild_id == guild_id, TopicSummaryRecord.topic_id == topic_id
            )
        )
        await self.session.execute(
            delete(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.guild_id == guild_id,
                MessageTopicAssociationRecord.topic_id == topic_id,
            )
        )
        await self.session.execute(
            delete(EpisodeRecord).where(
                EpisodeRecord.guild_id == guild_id, EpisodeRecord.topic_id == topic_id
            )
        )
        await self.session.execute(
            delete(TopicSearchTermRecord).where(
                TopicSearchTermRecord.guild_id == guild_id,
                TopicSearchTermRecord.topic_id == topic_id,
            )
        )
        await self.session.execute(
            delete(TopicRecord).where(TopicRecord.id == topic_id, TopicRecord.guild_id == guild_id)
        )


def _topic_read_model(record: TopicRecord) -> TopicReadModel:
    return TopicReadModel(
        id=record.id,
        guild_id=record.guild_id,
        title=record.title,
        description=record.description,
        status=record.status,
        last_activity_at=record.last_activity_at,
        version=record.version if record.version is not None else 1,
        discord_thread_id=record.discord_thread_id,
        sync_paused=record.sync_paused,
    )

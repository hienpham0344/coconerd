from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.entities import ConversationMessage, ConversationTopic
from backend.domain.enums import ActionStatus, ActionType, JobStatus, TopicStatus
from backend.infrastructure.database.models import (
    DiscordActionRecord,
    GuildSettingsRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    ProcessingJobRecord,
    TopicRecord,
    TopicSummaryRecord,
)


class GuildRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def channel_is_enabled(self, guild_id: str, channel_id: str) -> bool:
        setting = await self.session.get(GuildSettingsRecord, guild_id)
        return bool(setting and setting.enabled and channel_id in setting.allowed_channel_ids)


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ingest(
        self, message: ConversationMessage, max_attempts: int
    ) -> tuple[MessageRecord, bool]:
        record_id = message.id
        statement = (
            sqlite_insert(MessageRecord)
            .values(
                id=record_id,
                guild_id=message.guild_id,
                channel_id=message.channel_id,
                discord_message_id=message.message_id,
                author_id=message.author_id,
                author_name=message.author_name,
                content=message.content,
                created_at=message.created_at,
                reply_to_message_id=message.reply_to_message_id,
            )
            .on_conflict_do_nothing(index_elements=["guild_id", "discord_message_id"])
        )
        result = await self.session.execute(statement)
        inserted = result.rowcount == 1
        record = await self.session.scalar(
            select(MessageRecord).where(
                MessageRecord.guild_id == message.guild_id,
                MessageRecord.discord_message_id == message.message_id,
            )
        )
        if record is None:
            raise RuntimeError("Ingested message could not be reloaded")
        if inserted:
            await self.session.execute(
                sqlite_insert(ProcessingJobRecord)
                .values(
                    id=str(uuid4()),
                    guild_id=message.guild_id,
                    message_record_id=record.id,
                    max_attempts=max_attempts,
                )
                .on_conflict_do_nothing(index_elements=["message_record_id"])
            )
        return record, inserted

    async def get_by_discord_id(self, guild_id: str, message_id: str) -> MessageRecord | None:
        return await self.session.scalar(
            select(MessageRecord).where(
                MessageRecord.guild_id == guild_id,
                MessageRecord.discord_message_id == message_id,
            )
        )

    async def list_for_topic(
        self, guild_id: str, topic_id: str, limit: int, before: datetime | None
    ) -> list[MessageRecord]:
        query = (
            select(MessageRecord)
            .join(MessageTopicAssociationRecord)
            .where(
                MessageTopicAssociationRecord.guild_id == guild_id,
                MessageTopicAssociationRecord.topic_id == topic_id,
                MessageRecord.guild_id == guild_id,
            )
            .order_by(MessageRecord.created_at.desc(), MessageRecord.discord_message_id.desc())
            .limit(limit)
        )
        if before is not None:
            query = query.where(MessageRecord.created_at < before)
        result = await self.session.scalars(query)
        return list(result)


class TopicRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def candidates(
        self, guild_id: str, channel_id: str | None = None, limit: int = 30
    ) -> list[TopicRecord]:
        query = select(TopicRecord).where(
            TopicRecord.guild_id == guild_id,
            TopicRecord.status.in_(
                [TopicStatus.ACTIVE, TopicStatus.DORMANT, TopicStatus.RESUMED]
            ),
        )
        if channel_id:
            query = query.where(TopicRecord.channel_id == channel_id)
        query = query.order_by(TopicRecord.last_activity_at.desc()).limit(limit)
        result = await self.session.scalars(query)
        return list(result)

    async def get(self, guild_id: str, topic_id: str) -> TopicRecord | None:
        return await self.session.scalar(
            select(TopicRecord).where(TopicRecord.guild_id == guild_id, TopicRecord.id == topic_id)
        )

    async def create(self, topic: ConversationTopic) -> TopicRecord:
        record = TopicRecord(
            id=topic.id,
            guild_id=topic.guild_id,
            channel_id=topic.channel_id,
            title=topic.title,
            description=topic.description,
            status=topic.status.value,
            discord_thread_id=topic.discord_thread_id,
            last_activity_at=topic.last_activity_at,
            version=1,
        )
        self.session.add(record)
        await self.session.flush()
        return record

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


class ActionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        guild_id: str,
        channel_id: str,
        topic_id: str,
        action_type: ActionType,
        payload: dict[str, object],
        dependency_id: str | None = None,
        max_attempts: int = 5,
    ) -> DiscordActionRecord:
        record = DiscordActionRecord(
            id=str(uuid4()),
            guild_id=guild_id,
            channel_id=channel_id,
            topic_id=topic_id,
            action_type=action_type.value,
            payload=payload,
            dependency_id=dependency_id,
            max_attempts=max_attempts,
        )
        self.session.add(record)
        return record

    async def claim(self, owner: str, limit: int, lease_seconds: int) -> list[DiscordActionRecord]:
        now = datetime.now(UTC)
        expired = or_(
            DiscordActionRecord.status == ActionStatus.PENDING,
            and_(
                DiscordActionRecord.status == ActionStatus.CLAIMED,
                DiscordActionRecord.lease_expires_at < now,
            ),
        )
        eligible = (
            select(DiscordActionRecord.id)
            .where(
                expired,
                DiscordActionRecord.available_at <= now,
                DiscordActionRecord.attempt_count < DiscordActionRecord.max_attempts,
                or_(
                    DiscordActionRecord.dependency_id.is_(None),
                    DiscordActionRecord.dependency_id.in_(
                        select(DiscordActionRecord.id).where(
                            DiscordActionRecord.status == ActionStatus.SUCCEEDED
                        )
                    ),
                ),
            )
            .order_by(DiscordActionRecord.created_at)
            .limit(limit)
        )
        ids = list((await self.session.scalars(eligible)).all())
        if not ids:
            return []
        await self.session.execute(
            update(DiscordActionRecord)
            .where(DiscordActionRecord.id.in_(ids), expired)
            .values(
                status=ActionStatus.CLAIMED,
                lease_owner=owner,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                attempt_count=DiscordActionRecord.attempt_count + 1,
            )
        )
        result = await self.session.scalars(
            select(DiscordActionRecord).where(
                DiscordActionRecord.id.in_(ids),
                DiscordActionRecord.status == ActionStatus.CLAIMED,
                DiscordActionRecord.lease_owner == owner,
            )
        )
        return list(result)


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim_one(self, owner: str, lease_seconds: int) -> ProcessingJobRecord | None:
        now = datetime.now(UTC)
        available = or_(
            ProcessingJobRecord.status == JobStatus.PENDING,
            and_(
                ProcessingJobRecord.status == JobStatus.CLAIMED,
                ProcessingJobRecord.lease_expires_at < now,
            ),
        )
        job_id = await self.session.scalar(
            select(ProcessingJobRecord.id)
            .where(
                available,
                ProcessingJobRecord.available_at <= now,
                ProcessingJobRecord.attempt_count < ProcessingJobRecord.max_attempts,
            )
            .order_by(ProcessingJobRecord.created_at)
            .limit(1)
        )
        if job_id is None:
            await self.session.execute(
                update(ProcessingJobRecord)
                .where(
                    ProcessingJobRecord.status.in_([JobStatus.PENDING, JobStatus.CLAIMED]),
                    ProcessingJobRecord.attempt_count >= ProcessingJobRecord.max_attempts,
                )
                .values(status=JobStatus.DEAD)
            )
            return None
        claim_result = await self.session.execute(
            update(ProcessingJobRecord)
            .where(ProcessingJobRecord.id == job_id, available)
            .values(
                status=JobStatus.CLAIMED,
                lease_owner=owner,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                attempt_count=ProcessingJobRecord.attempt_count + 1,
            )
        )
        if claim_result.rowcount != 1:
            return None
        return await self.session.get(ProcessingJobRecord, job_id)


class SummaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def latest(self, guild_id: str, topic_id: str) -> TopicSummaryRecord | None:
        return await self.session.scalar(
            select(TopicSummaryRecord)
            .where(TopicSummaryRecord.guild_id == guild_id, TopicSummaryRecord.topic_id == topic_id)
            .order_by(TopicSummaryRecord.version.desc())
            .limit(1)
        )

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
        return record

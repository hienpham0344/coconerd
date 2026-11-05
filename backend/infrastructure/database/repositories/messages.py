from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.read_models import MessageReadModel
from backend.domain.entities import ConversationMessage
from backend.infrastructure.database.models import (
    AIDecisionRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    ProcessingJobRecord,
)
from backend.infrastructure.database.notifications import JOBS_CHANNEL, notify_transaction
from backend.infrastructure.database.statements import conflict_insert


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def evidence_for_topic(
        self, guild_id: str, channel_id: str, topic_id: str, before: datetime, limit: int = 2
    ) -> list[MessageReadModel]:
        records = await self.session.scalars(
            select(MessageRecord)
            .join(MessageTopicAssociationRecord)
            .where(
                MessageRecord.guild_id == guild_id,
                MessageRecord.channel_id == channel_id,
                MessageRecord.created_at < before,
                MessageTopicAssociationRecord.guild_id == guild_id,
                MessageTopicAssociationRecord.topic_id == topic_id,
            )
            .order_by(MessageRecord.created_at.desc(), MessageRecord.discord_message_id)
            .limit(min(limit, 2))
        )
        return [_message_read_model(record) for record in records]

    async def ingest(
        self, message: ConversationMessage, max_attempts: int
    ) -> tuple[MessageRecord, bool]:
        record_id = message.id
        statement = (
            conflict_insert(self.session, MessageRecord)
            .values(
                id=record_id,
                guild_id=message.guild_id,
                channel_id=message.channel_id,
                discord_message_id=message.message_id,
                author_id=message.author_id,
                author_name=message.author_name,
                content=message.content,
                attachments=message.attachments,
                created_at=message.created_at.astimezone(UTC),
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
                conflict_insert(self.session, ProcessingJobRecord)
                .values(
                    id=str(uuid4()),
                    guild_id=message.guild_id,
                    message_record_id=record.id,
                    max_attempts=max_attempts,
                )
                .on_conflict_do_nothing(index_elements=["message_record_id"])
            )
            await notify_transaction(self.session, JOBS_CHANNEL)
        return record, inserted

    async def ingest_read_model(
        self, message: ConversationMessage, max_attempts: int
    ) -> tuple[MessageReadModel, bool]:
        record, inserted = await self.ingest(message, max_attempts)
        return _message_read_model(record), inserted

    async def get_by_discord_id_read_model(
        self, guild_id: str, message_id: str
    ) -> MessageReadModel | None:
        record = await self.get_by_discord_id(guild_id, message_id)
        return _message_read_model(record) if record is not None else None

    async def get_by_discord_id(self, guild_id: str, message_id: str) -> MessageRecord | None:
        return await self.session.scalar(
            select(MessageRecord).where(
                MessageRecord.guild_id == guild_id,
                MessageRecord.discord_message_id == message_id,
            )
        )

    async def get_read_model(self, message_record_id: str) -> MessageReadModel | None:
        record = await self.session.get(MessageRecord, message_record_id)
        return _message_read_model(record) if record is not None else None

    async def recent_before_read_models(
        self, guild_id: str, channel_id: str, created_at: datetime, limit: int, after: datetime
    ) -> list[MessageReadModel]:
        # SQLite drops timezone metadata; persisted message timestamps are UTC.
        before_utc = (
            created_at.replace(tzinfo=UTC)
            if created_at.tzinfo is None
            else created_at.astimezone(UTC)
        )
        after_utc = after.replace(tzinfo=UTC) if after.tzinfo is None else after.astimezone(UTC)
        records = await self.session.scalars(
            select(MessageRecord)
            .where(
                MessageRecord.guild_id == guild_id,
                MessageRecord.channel_id == channel_id,
                MessageRecord.created_at < before_utc,
                MessageRecord.created_at >= after_utc,
            )
            .order_by(MessageRecord.created_at.desc(), MessageRecord.discord_message_id.desc())
            .limit(limit)
        )
        return [_message_read_model(record) for record in records]

    async def reply_topic_id(self, guild_id: str, discord_message_id: str) -> str | None:
        return await self.session.scalar(
            select(MessageTopicAssociationRecord.topic_id)
            .join(
                MessageRecord,
                MessageRecord.id == MessageTopicAssociationRecord.message_record_id,
            )
            .where(
                MessageRecord.guild_id == guild_id,
                MessageRecord.discord_message_id == discord_message_id,
                MessageTopicAssociationRecord.guild_id == guild_id,
                MessageTopicAssociationRecord.topic_id.is_not(None),
            )
        )

    async def add_association(
        self,
        guild_id: str,
        message_record_id: str,
        topic_id: str | None,
        kind: str,
        confidence: float,
        reason: str,
    ) -> None:
        statement = conflict_insert(self.session, MessageTopicAssociationRecord).values(
            id=str(uuid4()),
            guild_id=guild_id,
            message_record_id=message_record_id,
            topic_id=topic_id,
            kind=kind,
            confidence=confidence,
            reason=reason,
        )
        result = await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=["guild_id", "message_record_id"],
                set_={
                    "topic_id": topic_id,
                    "kind": kind,
                    "confidence": confidence,
                    "reason": reason,
                    "revision": MessageTopicAssociationRecord.revision + 1,
                },
                where=MessageTopicAssociationRecord.kind == "DEFERRED",
            )
        )
        if result.rowcount != 1:
            raise RuntimeError(
                "Message already has a final association; automatic reassignment is forbidden"
            )

    async def add_decision(
        self,
        guild_id: str,
        message_record_id: str,
        outcome: str,
        model_id: str,
        payload: dict[str, object],
    ) -> None:
        self.session.add(
            AIDecisionRecord(
                id=str(uuid4()),
                guild_id=guild_id,
                message_record_id=message_record_id,
                decision_type=outcome,
                model_id=model_id,
                payload=payload,
            )
        )

    async def list_for_topic_read_models(
        self, guild_id: str, topic_id: str, limit: int, before: datetime | None
    ) -> list[MessageReadModel]:
        records = await self.list_for_topic(guild_id, topic_id, limit, before)
        return [_message_read_model(record) for record in records]

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


def _message_read_model(record: MessageRecord) -> MessageReadModel:
    return MessageReadModel(
        id=record.id,
        guild_id=record.guild_id,
        channel_id=record.channel_id,
        discord_message_id=record.discord_message_id,
        author_id=record.author_id,
        author_name=record.author_name,
        content=record.content,
        created_at=record.created_at,
        reply_to_message_id=record.reply_to_message_id,
        attachments=record.attachments or [],
    )

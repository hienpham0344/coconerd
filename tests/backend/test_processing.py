from datetime import UTC, datetime

from sqlalchemy import func, select

from backend.application.services import ingest_message, process_message_record
from backend.domain.entities import ConversationMessage
from backend.domain.enums import AssociationKind
from backend.infrastructure.database.models import (
    DiscordActionRecord,
    EpisodeRecord,
    GuildSettingsRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    TopicRecord,
    TopicSummaryRecord,
)
from backend.infrastructure.meta_provider import MockMetaProvider


async def test_offline_worker_creates_topic_summary_and_outbox(database_factory):
    message = ConversationMessage(
        guild_id="guild-1",
        channel_id="channel-1",
        message_id="message-1",
        author_id="user-1",
        author_name="Hien",
        content="Let's plan the launch timeline.",
        created_at=datetime.now(UTC),
    )
    async with database_factory() as session:
        session.add(
            GuildSettingsRecord(
                guild_id="guild-1",
                enabled=True,
                allowed_channel_ids=["channel-1"],
                retention_days=365,
            )
        )
        await session.commit()
        record, inserted = await ingest_message(session, message, max_attempts=3)
        assert inserted
        await process_message_record(session, record.id, MockMetaProvider())
        await session.commit()

    async with database_factory() as session:
        assert await session.scalar(select(func.count()).select_from(MessageRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(TopicRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(TopicSummaryRecord)) == 1
        action_types = list(
            await session.scalars(
                select(DiscordActionRecord.action_type).order_by(DiscordActionRecord.created_at)
            )
        )
        assert action_types == ["CREATE_THREAD", "UPSERT_SUMMARY"]


async def test_late_reply_uses_same_guild_topic_and_resumes_episode(database_factory):
    async with database_factory() as session:
        session.add(
            GuildSettingsRecord(
                guild_id="guild-1",
                enabled=True,
                allowed_channel_ids=["channel-1"],
                retention_days=365,
            )
        )
        await session.commit()
        first = ConversationMessage(
            guild_id="guild-1",
            channel_id="channel-1",
            message_id="root-message",
            author_id="user-1",
            author_name="Hien",
            content="Let's plan the launch timeline.",
            created_at=datetime.now(UTC),
        )
        record, _ = await ingest_message(session, first, max_attempts=3)
        await process_message_record(session, record.id, MockMetaProvider())
        await session.commit()
        topic = await session.scalar(select(TopicRecord))
        assert topic is not None
        topic_id = topic.id
        topic.status = "DORMANT"
        await session.commit()

        reply = ConversationMessage(
            guild_id="guild-1",
            channel_id="channel-1",
            message_id="late-reply",
            author_id="user-2",
            author_name="Teammate",
            content="I agree; Thursday works.",
            created_at=datetime.now(UTC),
            reply_to_message_id="root-message",
        )
        reply_record, _ = await ingest_message(session, reply, max_attempts=3)
        await process_message_record(session, reply_record.id, MockMetaProvider())
        await session.commit()

        association = await session.scalar(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id == reply_record.id
            )
        )
        topic = await session.get(TopicRecord, topic_id)
        assert association is not None and association.topic_id == topic_id
        assert association.kind == AssociationKind.REPLY_LINK.value
        assert topic is not None and topic.status == "RESUMED"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EpisodeRecord)
                .where(EpisodeRecord.topic_id == topic_id)
            )
            == 2
        )

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from backend.application.contracts import ClassificationResult, TopicDecision
from backend.application.services.messages import ingest_message, process_message_record
from backend.config import Settings
from backend.domain.entities import ConversationMessage
from backend.domain.enums import AssociationKind
from backend.infrastructure.database.connection import create_session_factory
from backend.infrastructure.database.models import (
    AIDecisionRecord,
    Base,
    DiscordActionRecord,
    EpisodeRecord,
    GuildSettingsRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    TopicRecord,
    TopicSummaryRecord,
)
from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from backend.infrastructure.meta_provider import MockMetaProvider


async def test_topic_closed_during_classification_cannot_receive_memory(database_factory):
    from backend.domain.entities import ConversationTopic

    async with database_factory() as session:
        uow = SqlAlchemyUnitOfWork(session)
        topic = await uow.topics.create(ConversationTopic.create("guild-1", "Mobile login"))
        incoming = ConversationMessage(
            guild_id="guild-1",
            channel_id="channel-1",
            message_id="closed-race",
            author_id="user-1",
            author_name="Hien",
            content="Fix mobile login",
            created_at=datetime.now(UTC),
        )
        record, _ = await uow.messages.ingest(incoming, 3)
        await uow.commit()

        class ClosingProvider:
            model_id = "test"

            async def classify(self, message, candidates, context):
                await uow.topics.set_status("guild-1", topic.id, "CLOSED")
                return ClassificationResult(
                    decision=TopicDecision(
                        outcome="existing",
                        topic_id=topic.id,
                        confidence=0.99,
                        reason="match",
                        summary="must not be stored",
                        evidence_message_ids=[message.message_id],
                    ),
                    model_id=self.model_id,
                    latency_ms=1,
                )

        result = await process_message_record(uow, record.id, ClosingProvider())
        await uow.commit()
        assert result.outcome == "defer" and result.topic_id is None
        assert await session.scalar(select(func.count()).select_from(TopicSummaryRecord)) == 0
        assert await session.scalar(select(func.count()).select_from(DiscordActionRecord)) == 0


@pytest.mark.parametrize("content", ["", "  \t\n  "])
async def test_blank_message_is_persisted_without_model_call(database_factory, content):
    class RejectingProvider:
        model_id = "must-not-run"

        async def classify(self, message, candidates, context):
            raise AssertionError("blank message must not call the model")

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
        incoming = ConversationMessage(
            guild_id="guild-1",
            channel_id="channel-1",
            message_id="blank-message",
            author_id="user-1",
            author_name="Hien",
            content=content,
            created_at=datetime.now(UTC),
        )
        ingested = await ingest_message(SqlAlchemyUnitOfWork(session), incoming, 3)
        result = await process_message_record(
            SqlAlchemyUnitOfWork(session), ingested.message_id, RejectingProvider()
        )
        await session.commit()

        association = await session.scalar(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id == ingested.message_id
            )
        )
        decision = await session.scalar(
            select(AIDecisionRecord).where(
                AIDecisionRecord.message_record_id == ingested.message_id
            )
        )
        assert result.outcome == "irrelevant"
        assert association is not None and association.kind == AssociationKind.IRRELEVANT.value
        assert decision is not None and decision.model_id == "local-empty"
        assert decision.payload["usage"] == {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cached_tokens": 0,
            "reasoning_tokens": 0,
            "latency_ms": 0,
        }


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
        result = await ingest_message(SqlAlchemyUnitOfWork(session), message, max_attempts=3)
        assert result.inserted
        await process_message_record(
            SqlAlchemyUnitOfWork(session), result.message_id, MockMetaProvider()
        )
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


async def test_new_topic_persists_with_production_sqlite_foreign_keys(tmp_path):
    settings = Settings(
        _env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path / 'foreign_keys.db'}"
    )
    factory = create_session_factory(settings)
    try:
        async with factory.kw["bind"].begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add(
                GuildSettingsRecord(
                    guild_id="guild-1",
                    enabled=True,
                    allowed_channel_ids=["channel-1"],
                    retention_days=365,
                )
            )
            await session.commit()
            message = ConversationMessage(
                guild_id="guild-1",
                channel_id="channel-1",
                message_id="foreign-key-message",
                author_id="user-1",
                author_name="Hien",
                content="Plan the beta launch.",
                created_at=datetime.now(UTC),
            )
            ingested = await ingest_message(SqlAlchemyUnitOfWork(session), message, 3)
            result = await process_message_record(
                SqlAlchemyUnitOfWork(session), ingested.message_id, MockMetaProvider()
            )
            await session.commit()
            assert result.outcome == "new"

        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(TopicRecord)) == 1
            assert await session.scalar(select(func.count()).select_from(EpisodeRecord)) == 1
            assert await session.scalar(select(func.count()).select_from(DiscordActionRecord)) == 2
    finally:
        await factory.kw["bind"].dispose()


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
        result = await ingest_message(SqlAlchemyUnitOfWork(session), first, max_attempts=3)
        await process_message_record(
            SqlAlchemyUnitOfWork(session), result.message_id, MockMetaProvider()
        )
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
        reply_result = await ingest_message(SqlAlchemyUnitOfWork(session), reply, max_attempts=3)
        await process_message_record(
            SqlAlchemyUnitOfWork(session), reply_result.message_id, MockMetaProvider()
        )
        await session.commit()

        association = await session.scalar(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id == reply_result.message_id
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


async def test_decision_records_selected_context_message_ids(database_factory):
    class RecordingProvider:
        model_id = "test"

        async def classify(self, message, candidates, context):
            assert message.message_id == "target"
            assert [item.message_id for item in context] == ["prior"]
            return ClassificationResult(
                decision=TopicDecision(outcome="defer", confidence=0.2, reason="uncertain"),
                model_id=self.model_id,
                latency_ms=1,
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
        created_at = datetime.now(UTC)
        for message_id, offset in [("prior", -1), ("target", 0)]:
            incoming = ConversationMessage(
                guild_id="guild-1",
                channel_id="channel-1",
                message_id=message_id,
                author_id="user-1",
                author_name="Hien",
                content=message_id,
                created_at=created_at + timedelta(minutes=offset),
            )
            result = await ingest_message(SqlAlchemyUnitOfWork(session), incoming, 3)
            if message_id == "target":
                target_id = result.message_id
        await process_message_record(SqlAlchemyUnitOfWork(session), target_id, RecordingProvider())
        await session.commit()

        decision = await session.scalar(
            select(AIDecisionRecord).where(AIDecisionRecord.message_record_id == target_id)
        )
        assert decision is not None
        assert decision.payload["context_message_ids"] == ["prior"]

import os
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

from datetime import UTC, datetime
from pathlib import Path
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.application.contracts import ModelProvider, TopicCandidate, TopicDecision
from backend.application.services import ingest_message, process_message_record
from backend.config import Settings
from backend.domain.entities import ConversationMessage, ConversationTopic
from backend.domain.enums import AssociationKind, TopicStatus
from backend.infrastructure.database.connection import create_session_factory
from backend.infrastructure.database.models import (
    Base,
    DiscordActionRecord,
    GuildSettingsRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    TopicRecord,
)
from backend.infrastructure.database.repositories import TopicRepository


class DeterministicProvider(ModelProvider):
    model_id = "test-provider"

    def __init__(self, decision: TopicDecision):
        self.decision = decision

    async def classify(
        self, message: ConversationMessage, candidates: list[TopicCandidate]
    ) -> TopicDecision:
        return self.decision


@pytest.fixture
async def memory_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_same_guild_and_channel_assignment_allowed(memory_db):
    async with memory_db() as session:
        session.add(
            GuildSettingsRecord(
                guild_id="guild-1",
                enabled=True,
                allowed_channel_ids=["channel-1"],
                retention_days=365,
            )
        )
        topic_repo = TopicRepository(session)
        created_topic = await topic_repo.create(
            ConversationTopic.create("guild-1", "Frontend Architecture", channel_id="channel-1")
        )
        await session.commit()
        topic_id = created_topic.id

        message = ConversationMessage(
            guild_id="guild-1",
            channel_id="channel-1",
            message_id="msg-1",
            author_id="user-1",
            author_name="Alice",
            content="Let us use React",
            created_at=datetime.now(UTC),
        )
        record, _ = await ingest_message(session, message, max_attempts=3)
        provider = DeterministicProvider(
            TopicDecision(
                outcome="existing",
                topic_id=topic_id,
                confidence=0.9,
                reason="Direct topic match",
                summary="Discussing React",
            )
        )
        await process_message_record(session, record.id, provider)
        await session.commit()

    async with memory_db() as session:
        assoc = await session.scalar(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id == record.id
            )
        )
        assert assoc is not None
        assert assoc.topic_id == topic_id
        assert assoc.kind == AssociationKind.CLASSIFIED.value

        updated_topic = await session.get(TopicRecord, topic_id)
        assert updated_topic is not None
        assert updated_topic.version == 2


@pytest.mark.asyncio
async def test_different_channel_assignment_rejected(memory_db):
    async with memory_db() as session:
        session.add(
            GuildSettingsRecord(
                guild_id="guild-1",
                enabled=True,
                allowed_channel_ids=["channel-1", "channel-2"],
                retention_days=365,
            )
        )
        topic_repo = TopicRepository(session)
        created_topic = await topic_repo.create(
            ConversationTopic.create("guild-1", "Backend Database", channel_id="channel-1")
        )
        await session.commit()
        foreign_topic_id = created_topic.id

        message = ConversationMessage(
            guild_id="guild-1",
            channel_id="channel-2",
            message_id="msg-2",
            author_id="user-2",
            author_name="Bob",
            content="Message in Channel 2 attempting to link to Channel 1",
            created_at=datetime.now(UTC),
        )
        record, _ = await ingest_message(session, message, max_attempts=3)
        provider = DeterministicProvider(
            TopicDecision(
                outcome="existing",
                topic_id=foreign_topic_id,
                confidence=0.9,
                reason="Cross channel hallucination",
            )
        )
        await process_message_record(session, record.id, provider)
        await session.commit()

    async with memory_db() as session:
        assoc = await session.scalar(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id == record.id
            )
        )
        assert assoc is not None
        assert assoc.kind == AssociationKind.DEFERRED.value
        assert assoc.topic_id is None

        topic = await session.get(TopicRecord, foreign_topic_id)
        assert topic.version == 1

        actions = (
            await session.scalars(
                select(DiscordActionRecord).where(
                    DiscordActionRecord.topic_id == foreign_topic_id,
                    DiscordActionRecord.channel_id == "channel-2",
                )
            )
        ).all()
        assert len(actions) == 0


@pytest.mark.asyncio
async def test_different_guild_assignment_rejected(memory_db):
    async with memory_db() as session:
        session.add(
            GuildSettingsRecord(
                guild_id="guild-1",
                enabled=True,
                allowed_channel_ids=["channel-1"],
                retention_days=365,
            )
        )
        session.add(
            GuildSettingsRecord(
                guild_id="guild-2",
                enabled=True,
                allowed_channel_ids=["channel-1"],
                retention_days=365,
            )
        )
        topic_repo = TopicRepository(session)
        created_topic = await topic_repo.create(
            ConversationTopic.create("guild-2", "Foreign Guild Topic", channel_id="channel-1")
        )
        await session.commit()
        foreign_guild_topic_id = created_topic.id

        message = ConversationMessage(
            guild_id="guild-1",
            channel_id="channel-1",
            message_id="msg-3",
            author_id="user-1",
            author_name="Alice",
            content="Message in Guild 1 referencing Guild 2 topic",
            created_at=datetime.now(UTC),
        )
        record, _ = await ingest_message(session, message, max_attempts=3)
        provider = DeterministicProvider(
            TopicDecision(
                outcome="existing",
                topic_id=foreign_guild_topic_id,
                confidence=0.85,
                reason="Cross-guild attempt",
            )
        )
        await process_message_record(session, record.id, provider)
        await session.commit()

    async with memory_db() as session:
        assoc = await session.scalar(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id == record.id
            )
        )
        assert assoc is not None
        assert assoc.kind == AssociationKind.DEFERRED.value
        assert assoc.topic_id is None


@pytest.mark.asyncio
async def test_nonexistent_topic_assignment_rejected(memory_db):
    async with memory_db() as session:
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
            message_id="msg-4",
            author_id="user-1",
            author_name="Alice",
            content="Referencing non-existent topic",
            created_at=datetime.now(UTC),
        )
        record, _ = await ingest_message(session, message, max_attempts=3)
        provider = DeterministicProvider(
            TopicDecision(
                outcome="existing",
                topic_id="completely-fictional-topic-id",
                confidence=0.7,
                reason="Model hallucinated ID",
            )
        )
        await process_message_record(session, record.id, provider)
        await session.commit()

    async with memory_db() as session:
        assoc = await session.scalar(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id == record.id
            )
        )
        assert assoc is not None
        assert assoc.kind == AssociationKind.DEFERRED.value
        assert assoc.topic_id is None


@pytest.mark.asyncio
async def test_malformed_topic_id_assignment_rejected(memory_db):
    async with memory_db() as session:
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
            message_id="msg-5",
            author_id="user-1",
            author_name="Alice",
            content="Missing topic ID with existing outcome",
            created_at=datetime.now(UTC),
        )
        record, _ = await ingest_message(session, message, max_attempts=3)
        provider = DeterministicProvider(
            TopicDecision(
                outcome="existing",
                topic_id=None,
                confidence=0.5,
                reason="No topic ID",
            )
        )
        await process_message_record(session, record.id, provider)
        await session.commit()

    async with memory_db() as session:
        assoc = await session.scalar(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id == record.id
            )
        )
        assert assoc is not None
        assert assoc.kind == AssociationKind.DEFERRED.value
        assert assoc.topic_id is None


@pytest.mark.asyncio
async def test_sqlite_pragmas_configured_on_session_factory():
    db_file = Path("./data/pragma_test.db")
    if db_file.exists():
        db_file.unlink(missing_ok=True)
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{db_file}",
    )
    factory = create_session_factory(settings)
    async with factory() as session:
        fk = (await session.execute(text("PRAGMA foreign_keys;"))).scalar()
        jm = (await session.execute(text("PRAGMA journal_mode;"))).scalar()
        bt = (await session.execute(text("PRAGMA busy_timeout;"))).scalar()

        assert fk == 1
        assert jm.lower() == "wal"
        assert bt == 30000

    await factory.kw["bind"].dispose()
    if db_file.exists():
        db_file.unlink(missing_ok=True)
    wal_file = Path("./data/pragma_test.db-wal")
    if wal_file.exists():
        wal_file.unlink(missing_ok=True)
    shm_file = Path("./data/pragma_test.db-shm")
    if shm_file.exists():
        shm_file.unlink(missing_ok=True)

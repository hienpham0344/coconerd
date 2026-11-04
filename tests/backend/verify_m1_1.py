import asyncio
from datetime import UTC, datetime
import os
from pathlib import Path

# Disable external tracing network calls
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.application.contracts import ModelProvider, TopicCandidate, TopicDecision
from backend.application.services import ingest_message, process_message_record
from backend.config import Settings
from backend.domain.entities import ConversationMessage, ConversationTopic
from backend.domain.enums import AssociationKind
from backend.infrastructure.database.connection import create_session_factory
from backend.infrastructure.database.models import (
    Base,
    DiscordActionRecord,
    GuildSettingsRecord,
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


async def run_all_verifications():
    print("=== STARTING M1.1 TARGETED VERIFICATIONS ===", flush=True)

    # -------------------------------------------------------------------------
    # Priority B: SQLite Reliability PRAGMA Verification
    # -------------------------------------------------------------------------
    print("\n--- Priority B: SQLite PRAGMA Verification ---", flush=True)
    test_db_path = Path("./data/test_m1_1_pragmas.db")
    if test_db_path.exists():
        test_db_path.unlink()

    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{test_db_path}",
    )
    factory = create_session_factory(settings)
    async with factory() as session:
        fk = (await session.execute(text("PRAGMA foreign_keys;"))).scalar()
        jm = (await session.execute(text("PRAGMA journal_mode;"))).scalar()
        bt = (await session.execute(text("PRAGMA busy_timeout;"))).scalar()

        print(f"PRAGMA foreign_keys: {fk} (expected: 1)", flush=True)
        print(f"PRAGMA journal_mode: {jm} (expected: wal)", flush=True)
        print(f"PRAGMA busy_timeout: {bt} (expected: 30000)", flush=True)

        assert fk == 1, f"Expected foreign_keys=1, got {fk}"
        assert jm.lower() == "wal", f"Expected journal_mode=wal, got {jm}"
        assert bt == 30000, f"Expected busy_timeout=30000, got {bt}"

    await factory.kw["bind"].dispose()
    if test_db_path.exists():
        test_db_path.unlink()
    for suffix in ("-wal", "-shm"):
        f = Path(f"./data/test_m1_1_pragmas.db{suffix}")
        if f.exists():
            f.unlink()
    print("✅ Priority B: SQLite PRAGMA settings verified successfully!", flush=True)

    # -------------------------------------------------------------------------
    # Priority A: Topic Channel Isolation Verification
    # -------------------------------------------------------------------------
    print("\n--- Priority A: Topic Channel Isolation Cases ---", flush=True)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    mem_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with mem_factory() as session:
        # Seed test guilds
        session.add(
            GuildSettingsRecord(
                guild_id="guild-1",
                enabled=True,
                allowed_channel_ids=["channel-1", "channel-2"],
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
        # Topic 1: Guild 1, Channel 1
        t1 = await topic_repo.create(
            ConversationTopic.create("guild-1", "Frontend Channel 1 Topic", channel_id="channel-1")
        )
        # Topic 2: Guild 2, Channel 1
        t2 = await topic_repo.create(
            ConversationTopic.create("guild-2", "Guild 2 Foreign Topic", channel_id="channel-1")
        )
        await session.commit()
        topic_1_id = t1.id
        topic_2_id = t2.id

    # Case 1: Message and topic share Guild and Channel -> Assignment allowed
    print("Case 1: Same Guild & Same Channel...", end=" ", flush=True)
    async with mem_factory() as session:
        msg1 = ConversationMessage(
            guild_id="guild-1",
            channel_id="channel-1",
            message_id="msg-case-1",
            author_id="u1",
            author_name="Alice",
            content="Discussing frontend in channel 1",
            created_at=datetime.now(UTC),
        )
        rec1, _ = await ingest_message(session, msg1, max_attempts=3)
        p1 = DeterministicProvider(
            TopicDecision(
                outcome="existing",
                topic_id=topic_1_id,
                confidence=0.9,
                reason="Direct channel topic match",
                summary="Discussing frontend",
            )
        )
        await process_message_record(session, rec1.id, p1)
        await session.commit()

        assoc1 = await session.scalar(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id == rec1.id
            )
        )
        assert assoc1 is not None
        assert assoc1.topic_id == topic_1_id
        assert assoc1.kind == AssociationKind.CLASSIFIED.value

        updated_t1 = await session.get(TopicRecord, topic_1_id)
        assert updated_t1.version == 2
        print("ALLOWED (PASSED)", flush=True)

    # Case 2: Message and topic share Guild but differ in Channel -> Assignment rejected
    print("Case 2: Same Guild & Different Channel...", end=" ", flush=True)
    async with mem_factory() as session:
        msg2 = ConversationMessage(
            guild_id="guild-1",
            channel_id="channel-2",  # Channel 2 != Channel 1
            message_id="msg-case-2",
            author_id="u2",
            author_name="Bob",
            content="Message in Channel 2 trying to attach to Channel 1 topic",
            created_at=datetime.now(UTC),
        )
        rec2, _ = await ingest_message(session, msg2, max_attempts=3)
        p2 = DeterministicProvider(
            TopicDecision(
                outcome="existing",
                topic_id=topic_1_id,  # Points to Channel 1 topic!
                confidence=0.9,
                reason="Cross-channel hallucinated assignment",
            )
        )
        await process_message_record(session, rec2.id, p2)
        await session.commit()

        assoc2 = await session.scalar(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id == rec2.id
            )
        )
        assert assoc2 is not None
        assert assoc2.kind == AssociationKind.DEFERRED.value
        assert assoc2.topic_id is None, "topic_id must be None when deferred"

        # Topic 1 version must NOT be modified
        t1_unchanged = await session.get(TopicRecord, topic_1_id)
        assert t1_unchanged.version == 2

        # No actions created for topic 1 in channel 2
        actions = (
            await session.scalars(
                select(DiscordActionRecord).where(
                    DiscordActionRecord.topic_id == topic_1_id,
                    DiscordActionRecord.channel_id == "channel-2",
                )
            )
        ).all()
        assert len(actions) == 0
        print("REJECTED & DEFERRED (PASSED)", flush=True)

    # Case 3: Message and topic belong to different Guilds -> Assignment rejected
    print("Case 3: Different Guilds...", end=" ", flush=True)
    async with mem_factory() as session:
        msg3 = ConversationMessage(
            guild_id="guild-1",
            channel_id="channel-1",
            message_id="msg-case-3",
            author_id="u3",
            author_name="Charlie",
            content="Message in Guild 1 trying to attach to Guild 2 topic",
            created_at=datetime.now(UTC),
        )
        rec3, _ = await ingest_message(session, msg3, max_attempts=3)
        p3 = DeterministicProvider(
            TopicDecision(
                outcome="existing",
                topic_id=topic_2_id,  # Belongs to Guild 2!
                confidence=0.85,
                reason="Cross-guild assignment attempt",
            )
        )
        await process_message_record(session, rec3.id, p3)
        await session.commit()

        assoc3 = await session.scalar(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id == rec3.id
            )
        )
        assert assoc3 is not None
        assert assoc3.kind == AssociationKind.DEFERRED.value
        assert assoc3.topic_id is None
        print("REJECTED & DEFERRED (PASSED)", flush=True)

    # Case 4: Topic does not exist -> Existing safe fallback behavior
    print("Case 4: Non-existent topic...", end=" ", flush=True)
    async with mem_factory() as session:
        msg4 = ConversationMessage(
            guild_id="guild-1",
            channel_id="channel-1",
            message_id="msg-case-4",
            author_id="u4",
            author_name="Dana",
            content="Message referencing phantom topic",
            created_at=datetime.now(UTC),
        )
        rec4, _ = await ingest_message(session, msg4, max_attempts=3)
        p4 = DeterministicProvider(
            TopicDecision(
                outcome="existing",
                topic_id="non-existent-topic-uuid",
                confidence=0.7,
                reason="Phantom topic",
            )
        )
        await process_message_record(session, rec4.id, p4)
        await session.commit()

        assoc4 = await session.scalar(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id == rec4.id
            )
        )
        assert assoc4 is not None
        assert assoc4.kind == AssociationKind.DEFERRED.value
        assert assoc4.topic_id is None
        print("FALLBACK DEFERRED (PASSED)", flush=True)

    # Case 5: AI returns invalid or malformed topic ID -> Existing safe fallback behavior
    print("Case 5: Malformed / None topic_id with existing outcome...", end=" ", flush=True)
    async with mem_factory() as session:
        msg5 = ConversationMessage(
            guild_id="guild-1",
            channel_id="channel-1",
            message_id="msg-case-5",
            author_id="u5",
            author_name="Eve",
            content="Existing outcome with None topic_id",
            created_at=datetime.now(UTC),
        )
        rec5, _ = await ingest_message(session, msg5, max_attempts=3)
        p5 = DeterministicProvider(
            TopicDecision(
                outcome="existing",
                topic_id=None,
                confidence=0.4,
                reason="Missing topic ID from provider",
            )
        )
        await process_message_record(session, rec5.id, p5)
        await session.commit()

        assoc5 = await session.scalar(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id == rec5.id
            )
        )
        assert assoc5 is not None
        assert assoc5.kind == AssociationKind.DEFERRED.value
        assert assoc5.topic_id is None
        print("FALLBACK DEFERRED (PASSED)", flush=True)

    await engine.dispose()
    print("\n✅ Priority A: All 5 Topic Channel Isolation cases passed with 100% compliance!", flush=True)
    print("=== ALL TARGETED VERIFICATIONS COMPLETED SUCCESSFULLY ===", flush=True)


if __name__ == "__main__":
    asyncio.run(run_all_verifications())

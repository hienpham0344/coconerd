from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from backend.infrastructure.database.models import (
    Base,
    DiscordActionRecord,
    MessageRecord,
    ProcessingJobRecord,
    TopicRecord,
)


async def source_database(tmp_path):
    path = tmp_path / "source.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            MessageRecord.__table__.insert().values(
                id="record-1",
                guild_id="g",
                channel_id="c",
                discord_message_id="m",
                author_id="u",
                author_name="Lan",
                content="Nội dung gốc 🥥",
                created_at=datetime.now(UTC),
            )
        )
        await conn.execute(
            TopicRecord.__table__.insert().values(
                id="topic-1",
                guild_id="g",
                channel_id="c",
                title="Chủ đề gốc",
                discord_thread_id="2000",
            )
        )
        await conn.execute(
            DiscordActionRecord.__table__.insert().values(
                id="action-1",
                guild_id="g",
                channel_id="c",
                topic_id="topic-1",
                action_type="CREATE_THREAD",
                status="SUCCEEDED",
                payload={},
                discord_thread_id="2000",
                discord_message_id="3000",
            )
        )
        await conn.execute(
            ProcessingJobRecord.__table__.insert().values(
                id="job-1",
                guild_id="g",
                message_record_id="record-1",
                status="SUCCEEDED",
            )
        )
    await engine.dispose()
    return path


async def test_history_import_preserves_ids_and_can_be_repeated(tmp_path, database_factory):
    from scripts.import_sqlite_history import import_sqlite_snapshot

    source = await source_database(tmp_path)
    destination = database_factory.kw["bind"]
    counts = await import_sqlite_snapshot(source, destination)
    assert counts["messages"] == 1
    assert counts["topics"] == 1
    assert await import_sqlite_snapshot(source, destination) == counts
    async with destination.connect() as conn:
        message = (await conn.execute(select(MessageRecord.__table__))).mappings().one()
        topic = (await conn.execute(select(TopicRecord.__table__))).mappings().one()
        assert await conn.scalar(select(DiscordActionRecord.status)) == "SUCCEEDED"
        assert await conn.scalar(select(ProcessingJobRecord.status)) == "SUCCEEDED"
    assert message["id"] == "record-1"
    assert message["content"] == "Nội dung gốc 🥥"
    assert topic["discord_thread_id"] == "2000"


async def test_history_import_rolls_back_every_table_on_conflict(tmp_path, database_factory):
    from scripts.import_sqlite_history import import_sqlite_snapshot

    source = await source_database(tmp_path)
    destination = database_factory.kw["bind"]
    async with destination.begin() as conn:
        await conn.execute(
            TopicRecord.__table__.insert().values(
                id="topic-1",
                guild_id="g",
                channel_id="c",
                title="Dữ liệu khác",
            )
        )
    with pytest.raises(ValueError, match="Conflicting destination row"):
        await import_sqlite_snapshot(source, destination)
    async with destination.connect() as conn:
        assert (await conn.execute(select(MessageRecord.__table__))).first() is None
        assert await conn.scalar(select(TopicRecord.title)) == "Dữ liệu khác"

"""Message context is bounded, chronological, and never crosses conversation scope."""

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select

from backend.application.services.message_context import build_message_context
from backend.domain.entities import ConversationMessage
from backend.infrastructure.database.models import MessageRecord
from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

BASE = datetime(2026, 1, 1, 12, tzinfo=UTC)


def message(
    message_id: str,
    minutes: int,
    *,
    guild_id: str = "guild-1",
    channel_id: str = "channel-1",
    reply_to_message_id: str | None = None,
    content: str | None = None,
) -> ConversationMessage:
    return ConversationMessage(
        guild_id=guild_id,
        channel_id=channel_id,
        message_id=message_id,
        author_id="author-1",
        author_name="User",
        content=content if content is not None else message_id,
        created_at=BASE + timedelta(minutes=minutes),
        reply_to_message_id=reply_to_message_id,
    )


async def test_reply_chain_prioritized_and_scoped_with_out_of_order_ingest(database_factory):
    async with database_factory() as session:
        port = SqlAlchemyUnitOfWork(session).messages
        target = message("target", 60, reply_to_message_id="old-reply")
        for item in [
            target,
            message("later", 61),
            message("cross-channel", 59, channel_id="channel-2"),
            message("cross-guild", 59, guild_id="guild-2"),
            message("recent-1", 58),
            message("recent-2", 57),
            message("old-reply", 2, reply_to_message_id="old-root"),
            message("old-root", 1),
        ]:
            await port.ingest(item, max_attempts=3)
        await session.commit()

        context = await build_message_context(port, target)
        assert [item.message_id for item in context] == [
            "old-root",
            "old-reply",
            "recent-2",
            "recent-1",
        ]
        assert [item.relation for item in context] == [
            "reply_ancestor",
            "reply_ancestor",
            "recent",
            "recent",
        ]


async def test_context_budget_and_invalid_reply_are_enforced(database_factory):
    async with database_factory() as session:
        port = SqlAlchemyUnitOfWork(session).messages
        target = message("target", 60, reply_to_message_id="cross-reply")
        for index in range(1, 10):
            await port.ingest(message(f"recent-{index}", 60 - index, content="x" * 1000), 3)
        await port.ingest(message("zzz-blank", 59, content=""), 3)
        await port.ingest(message("cross-reply", 2, channel_id="channel-2"), 3)
        await port.ingest(target, 3)
        await session.commit()

        context = await build_message_context(port, target)
        assert len(context) <= 6
        assert all(item.relation == "recent" for item in context)
        assert all(len(item.content) <= 400 for item in context)
        assert sum(len(item.content) for item in context) <= 1600
        assert "cross-reply" not in [item.message_id for item in context]
        assert [item.message_id for item in context] == [
            "recent-4",
            "recent-3",
            "recent-2",
            "recent-1",
        ]


async def test_recent_query_excludes_current_future_and_other_guild(database_factory):
    async with database_factory() as session:
        port = SqlAlchemyUnitOfWork(session).messages
        target = message("target", 60)
        for item in [
            message("prior", 59),
            target,
            message("later", 61),
            message("other", 58, guild_id="guild-2"),
        ]:
            await port.ingest(item, 3)
        await session.commit()

        result = await port.recent_before(
            target.guild_id,
            target.channel_id,
            target.created_at,
            limit=6,
            after=target.created_at - timedelta(minutes=10),
        )
        assert [item.discord_message_id for item in result] == ["prior"]
        assert await session.scalar(select(MessageRecord).where(MessageRecord.id == target.id))


async def test_offset_timestamps_are_normalized_before_context_lookup(database_factory):
    async with database_factory() as session:
        port = SqlAlchemyUnitOfWork(session).messages
        prior = message("prior", 0)
        target = message("target", 1)
        target.created_at = datetime(2026, 1, 1, 19, 1, tzinfo=timezone(timedelta(hours=7)))
        await port.ingest(prior, 3)
        await port.ingest(target, 3)
        await session.commit()

        context = await build_message_context(port, target)
        assert [item.message_id for item in context] == ["prior"]

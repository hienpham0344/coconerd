"""Unit tests for Milestone 1 (M1 — Topic Index & /summarize).

Verifies:
1. Backend GET /api/v1/topics channel filtering, closed exclusion, and message count aggregation.
2. Backend GET /api/v1/topics/{topic_id}/summary channel isolation invariant.
3. Ingestion pipeline protection: messages in discord.Thread are ignored.
4. Slash command /summarize:
   - Unmanaged Threads cannot publish a summary.
   - Rejected when invoked from the Output Channel.
   - Rejected when invoked from an unconfigured channel.
   - topic_id: 0 lists topics with 1-based sequential indices.
   - topic_id: 0 pagination view handles page transitions and permission guards.
   - topic_id: N (N >= 1) maps 1-based index to real database topic ID and displays summary embed.
   - topic_id: N out of bounds returns friendly guidance to run /summarize topic_id:0.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.domain.enums import TopicStatus
from backend.infrastructure.database.models import (
    MessageRecord,
    MessageTopicAssociationRecord,
    TopicRecord,
    TopicSummaryRecord,
)
from bot.main import (
    TopicPaginationView,
    create_bot,
)

# =============================================================================
# 1. Backend API Endpoint Tests (Channel Isolation & Filtering)
# =============================================================================


@pytest.mark.asyncio
async def test_backend_list_topics_channel_isolation_and_exclude_closed(
    api_client, database_factory
):
    headers = {"X-API-Key": "bot-test-key"}
    async with database_factory() as session:
        # Topic 1: in channel-1, ACTIVE
        session.add(
            TopicRecord(
                id="topic-1",
                guild_id="guild-1",
                channel_id="channel-1",
                title="Active Topic 1",
                status=TopicStatus.ACTIVE,
                last_activity_at=datetime(2026, 11, 4, 10, 0, tzinfo=UTC),
            )
        )
        # Topic 2: in channel-1, DORMANT
        session.add(
            TopicRecord(
                id="topic-2",
                guild_id="guild-1",
                channel_id="channel-1",
                title="Dormant Topic 2",
                status=TopicStatus.DORMANT,
                last_activity_at=datetime(2026, 11, 4, 9, 0, tzinfo=UTC),
            )
        )
        # Topic 3: in channel-1, CLOSED
        session.add(
            TopicRecord(
                id="topic-3",
                guild_id="guild-1",
                channel_id="channel-1",
                title="Closed Topic 3",
                status=TopicStatus.CLOSED,
                last_activity_at=datetime(2026, 11, 4, 11, 0, tzinfo=UTC),
            )
        )
        # Topic 4: in channel-2 (different channel), ACTIVE
        session.add(
            TopicRecord(
                id="topic-4",
                guild_id="guild-1",
                channel_id="channel-2",
                title="Channel 2 Topic",
                status=TopicStatus.ACTIVE,
                last_activity_at=datetime(2026, 11, 4, 12, 0, tzinfo=UTC),
            )
        )
        # Create backing MessageRecords
        session.add_all(
            [
                MessageRecord(
                    id="msg-rec-1",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    discord_message_id="msg-1",
                    author_id="user-1",
                    author_name="User 1",
                    content="Hello 1",
                    created_at=datetime(2026, 11, 4, 10, 0, tzinfo=UTC),
                ),
                MessageRecord(
                    id="msg-rec-2",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    discord_message_id="msg-2",
                    author_id="user-2",
                    author_name="User 2",
                    content="Hello 2",
                    created_at=datetime(2026, 11, 4, 10, 5, tzinfo=UTC),
                ),
                MessageRecord(
                    id="msg-rec-3",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    discord_message_id="msg-3",
                    author_id="user-3",
                    author_name="User 3",
                    content="Hello 3",
                    created_at=datetime(2026, 11, 4, 9, 5, tzinfo=UTC),
                ),
            ]
        )
        # Associate message records to count
        session.add_all(
            [
                MessageTopicAssociationRecord(
                    id="assoc-1",
                    guild_id="guild-1",
                    message_record_id="msg-rec-1",
                    topic_id="topic-1",
                    kind="CLASSIFIED",
                    confidence=1.0,
                    reason="",
                ),
                MessageTopicAssociationRecord(
                    id="assoc-2",
                    guild_id="guild-1",
                    message_record_id="msg-rec-2",
                    topic_id="topic-1",
                    kind="CLASSIFIED",
                    confidence=1.0,
                    reason="",
                ),
                MessageTopicAssociationRecord(
                    id="assoc-3",
                    guild_id="guild-1",
                    message_record_id="msg-rec-3",
                    topic_id="topic-2",
                    kind="CLASSIFIED",
                    confidence=1.0,
                    reason="",
                ),
            ]
        )
        await session.commit()

    # Query topics for channel-1 with include_closed=False (default)
    resp = await api_client.get(
        "/api/v1/topics?guild_id=guild-1&channel_id=channel-1",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    items = data["items"]

    # Must contain topic-1 and topic-2, but NOT topic-3 (CLOSED) and NOT topic-4 (channel-2)
    item_ids = [it["topic_id"] for it in items]
    assert item_ids == ["topic-1", "topic-2"]

    # Verify message count aggregation
    count_map = {it["topic_id"]: it.get("message_count", 0) for it in items}
    assert count_map["topic-1"] == 2
    assert count_map["topic-2"] == 1


@pytest.mark.asyncio
async def test_backend_get_topic_summary_channel_isolation(api_client, database_factory):
    headers = {"X-API-Key": "bot-test-key"}
    async with database_factory() as session:
        session.add(
            TopicRecord(
                id="topic-isolated-1",
                guild_id="guild-1",
                channel_id="channel-input-a",
                title="Isolated Topic",
                status=TopicStatus.ACTIVE,
            )
        )
        session.add(
            TopicSummaryRecord(
                id="summary-1",
                guild_id="guild-1",
                topic_id="topic-isolated-1",
                version=1,
                data={
                    "overview": "Test overview",
                    "proposals": ["P1"],
                    "decisions": ["D1"],
                    "action_items": ["A1"],
                },
                source_message_ids=["msg-1"],
            )
        )
        await session.commit()

    # Same channel -> 200 OK
    resp_ok = await api_client.get(
        "/api/v1/topics/topic-isolated-1/summary?guild_id=guild-1&channel_id=channel-input-a",
        headers=headers,
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["title"] == "Isolated Topic"

    # Cross channel query -> 404 Not Found
    resp_cross = await api_client.get(
        "/api/v1/topics/topic-isolated-1/summary?guild_id=guild-1&channel_id=channel-input-b",
        headers=headers,
    )
    assert resp_cross.status_code == 404
    assert "channel" in resp_cross.json()["detail"].lower()


# =============================================================================
# 2. Pipeline Protection Tests (Thread Exclusion)
# =============================================================================


@pytest.mark.asyncio
async def test_on_message_ignores_threads():
    bot = create_bot()
    bot._connection.user = MagicMock(spec=discord.ClientUser, id=999999999)
    bot.backend = MagicMock()
    bot.backend.ingest_message = AsyncMock()
    bot.backend.get_guild_settings = AsyncMock(
        return_value={
            "enabled": True,
            "allowed_channel_ids": ["12345"],
            "output_channel_id": "99999",
        }
    )

    # Thread message
    mock_thread = MagicMock(spec=discord.Thread)
    mock_thread.id = 12345
    mock_thread.name = "sub-discussion"

    mock_msg = MagicMock(spec=discord.Message)
    mock_msg.channel = mock_thread
    mock_msg.guild = MagicMock(spec=discord.Guild, id=100)
    mock_msg.author = MagicMock(spec=discord.Member, bot=False, id=111111111)
    mock_msg.content = "Chatter inside a thread"
    mock_msg.mentions = []

    # Get on_message listener
    on_message_fn = bot.extra_events.get("on_message") or [getattr(bot, "on_message", None)]
    handler = on_message_fn[0] if isinstance(on_message_fn, list) else on_message_fn

    await handler(mock_msg)

    # Must NEVER ingest messages from threads
    bot.backend.ingest_message.assert_not_called()


# =============================================================================
# 3. Slash Command /summarize Tests (Routing, Rejection, Scope Validation)
# =============================================================================


@pytest.fixture
def mock_bot_with_settings():
    bot = create_bot()
    bot.backend = MagicMock()
    bot.backend.get_topic_messages = AsyncMock(return_value=[])
    bot.backend.get_guild_settings = AsyncMock(
        return_value={
            "enabled": True,
            "allowed_channel_ids": ["11111", "22222"],
            "output_channel_id": "99999",
        }
    )
    bot.backend.list_topics = AsyncMock(
        return_value=[
            {
                "id": "uuid-topic-1",
                "topic_id": "uuid-topic-1",
                "title": "Roadmap Q4",
                "status": "ACTIVE",
                "channel_id": "11111",
                "last_activity": "2026-11-04T12:00:00+00:00",
                "message_count": 15,
            },
            {
                "id": "uuid-topic-2",
                "topic_id": "uuid-topic-2",
                "title": "Backend Refactor",
                "status": "DORMANT",
                "channel_id": "11111",
                "last_activity": "2026-11-03T18:00:00+00:00",
                "message_count": 8,
            },
        ]
    )
    bot.backend.get_topic_summary = AsyncMock(
        return_value={
            "topic_id": "uuid-topic-1",
            "title": "Roadmap Q4",
            "status": "ACTIVE",
            "channel_id": "11111",
            "version": 2,
            "overview": "Overview of Q4 priorities.",
            "proposals": ["Ship M1", "Ship M2"],
            "decisions": ["Focus on reliability"],
            "action_items": ["Implement /summarize"],
            "open_questions": ["Timeline?"],
            "source_message_ids": ["m1", "m2"],
        }
    )
    return bot


@pytest.mark.asyncio
async def test_summarize_rejects_thread_outside_configured_output(mock_bot_with_settings):
    bot = mock_bot_with_settings
    cmd = bot.tree.get_command("summarize")
    assert cmd is not None

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock(spec=discord.Guild, id=100)
    interaction.channel = MagicMock(spec=discord.Thread)
    interaction.channel.parent_id = 12345
    interaction.channel_id = 45678
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    await cmd.callback(interaction, topic_id=0)

    interaction.followup.send.assert_awaited_once()
    args, kwargs = interaction.followup.send.call_args
    assert "Output Channel" in args[0]
    assert kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_summarize_rejects_in_output_channel(mock_bot_with_settings):
    bot = mock_bot_with_settings
    cmd = bot.tree.get_command("summarize")

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock(spec=discord.Guild, id=100)
    interaction.channel_id = 99999  # Configured output channel
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.name = "output-summaries"
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await cmd.callback(interaction, topic_id=0)

    interaction.followup.send.assert_called_once()
    args, kwargs = interaction.followup.send.call_args
    assert "output channel is reserved" in args[0].lower()
    assert kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_summarize_rejects_in_unconfigured_channel(mock_bot_with_settings):
    bot = mock_bot_with_settings
    cmd = bot.tree.get_command("summarize")

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock(spec=discord.Guild, id=100)
    interaction.channel_id = 33333  # Not in allowed channels
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await cmd.callback(interaction, topic_id=0)

    interaction.followup.send.assert_called_once()
    args, kwargs = interaction.followup.send.call_args
    assert "not configured as an input channel" in args[0].lower()
    assert kwargs.get("ephemeral") is True


@pytest.mark.asyncio
async def test_summarize_topic_id_0_listing(mock_bot_with_settings):
    bot = mock_bot_with_settings
    cmd = bot.tree.get_command("summarize")

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock(spec=discord.Guild, id=100)
    interaction.channel_id = 11111  # Allowed input channel
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.name = "engineering"
    interaction.user = MagicMock(id=55555)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await cmd.callback(interaction, topic_id=0)

    bot.backend.list_topics.assert_called_once_with(
        guild_id="100",
        channel_id="11111",
        include_closed=False,
        limit=50,
    )

    interaction.followup.send.assert_called_once()
    _, kwargs = interaction.followup.send.call_args
    assert kwargs.get("ephemeral") is True
    embed = kwargs.get("embed")
    assert isinstance(embed, discord.Embed)
    assert "#engineering" in embed.title

    # Must contain both topics with 1-based sequential indices
    field_names = [f.name for f in embed.fields]
    assert any("#1 — Roadmap Q4" in name for name in field_names)
    assert any("#2 — Backend Refactor" in name for name in field_names)


@pytest.mark.asyncio
async def test_summarize_topic_id_positive_maps_1based_index(mock_bot_with_settings):
    bot = mock_bot_with_settings
    cmd = bot.tree.get_command("summarize")

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock(spec=discord.Guild, id=100)
    interaction.channel_id = 11111
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.name = "engineering"
    interaction.user = MagicMock(id=55555)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    # User asks for topic 1 (1-based index)
    await cmd.callback(interaction, topic_id=1)

    # Must map index 1 -> uuid-topic-1
    bot.backend.get_topic_summary.assert_called_once_with(
        guild_id="100",
        topic_id="uuid-topic-1",
        channel_id="11111",
    )

    interaction.followup.send.assert_called_once()
    _, kwargs = interaction.followup.send.call_args
    assert kwargs.get("ephemeral") is True
    embed = kwargs.get("embed")
    assert isinstance(embed, discord.Embed)
    assert "#1 — Roadmap Q4" in embed.title

    field_names = [f.name for f in embed.fields]
    assert any("Overview" in name for name in field_names)
    assert any("Proposals" in name for name in field_names)
    assert any("Decisions" in name for name in field_names)
    assert any("Action Items" in name for name in field_names)


@pytest.mark.asyncio
async def test_summarize_topic_id_out_of_bounds(mock_bot_with_settings):
    bot = mock_bot_with_settings
    cmd = bot.tree.get_command("summarize")

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock(spec=discord.Guild, id=100)
    interaction.channel_id = 11111
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.channel.name = "engineering"
    interaction.user = MagicMock(id=55555)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    # Only 2 topics exist, user asks for 5
    await cmd.callback(interaction, topic_id=5)

    interaction.followup.send.assert_called_once()
    args, kwargs = interaction.followup.send.call_args
    assert "invalid topic index `#5`" in args[0].lower()
    assert "/summarize topic_id:0" in args[0]
    assert kwargs.get("ephemeral") is True


# =============================================================================
# 4. Pagination View Component Tests
# =============================================================================


@pytest.mark.asyncio
async def test_topic_pagination_view_navigation():
    # 7 sample topics
    topics = [{"title": f"Topic {i}", "status": "ACTIVE", "message_count": i} for i in range(1, 8)]
    view = TopicPaginationView(
        topics=topics,
        channel_name="test-channel",
        author_id=123,
        guild_id=456,
        channel_id=789,
        per_page=5,
    )

    # Initial page 0
    assert view.page == 0
    assert view.total_pages == 2
    assert view.prev_btn.disabled is True
    assert view.next_btn.disabled is False

    embed_p0 = view.build_embed()
    assert len(embed_p0.fields) == 5
    assert "#1 — Topic 1" in embed_p0.fields[0].name
    assert "#5 — Topic 5" in embed_p0.fields[4].name

    # Simulate interaction check for another user -> blocked
    stranger_interaction = MagicMock(spec=discord.Interaction)
    stranger_interaction.guild = MagicMock(id=456)
    stranger_interaction.channel_id = 789
    stranger_interaction.user = MagicMock(id=999)
    stranger_interaction.response = MagicMock()
    stranger_interaction.response.send_message = AsyncMock()

    assert await view.interaction_check(stranger_interaction) is False

    # Simulate author interaction for Next button
    author_interaction = MagicMock(spec=discord.Interaction)
    author_interaction.guild = MagicMock(id=456)
    author_interaction.channel_id = 789
    author_interaction.user = MagicMock(id=123)
    author_interaction.response = MagicMock()
    author_interaction.response.edit_message = AsyncMock()

    await view.next_btn.callback(author_interaction)
    assert view.page == 1
    assert view.prev_btn.disabled is False
    assert view.next_btn.disabled is True

    embed_p1 = view.build_embed()
    assert len(embed_p1.fields) == 2
    assert "#6 — Topic 6" in embed_p1.fields[0].name
    assert "#7 — Topic 7" in embed_p1.fields[1].name

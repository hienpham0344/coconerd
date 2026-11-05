from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from backend.infrastructure.database.models import TopicRecord
from bot.main import create_bot


@pytest.fixture
def thread_summary():
    bot = create_bot()
    backend = bot.backend = MagicMock()
    backend.get_guild_settings = AsyncMock(
        return_value={
            "enabled": True,
            "allowed_channel_ids": ["1"],
            "output_channel_id": "2",
        }
    )
    backend.get_thread_topic = AsyncMock(
        return_value={
            "topic_id": "study",
            "guild_id": "7",
            "channel_id": "1",
            "title": "Mai học gì",
            "discord_thread_id": "2000",
            "status": "ACTIVE",
        }
    )
    backend.get_topic_summary = AsyncMock(
        return_value={
            "overview": "Ngày mai học Avalanche; có câu hỏi về Docker.",
            "source_message_ids": ["m1", "m2", "m3"],
            "version": 3,
        }
    )
    thread = MagicMock(spec=discord.Thread)
    thread.id, thread.parent_id, thread.name = 2000, 2, "Mai học gì"
    thread.send = AsyncMock(return_value=SimpleNamespace(id=3000))
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=7),
        channel=thread,
        channel_id=2000,
        response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        user=SimpleNamespace(id=99),
    )
    return SimpleNamespace(bot=bot, backend=backend, thread=thread, interaction=interaction)


async def test_summarize_posts_only_when_invoked_inside_its_mapped_thread(thread_summary):
    state = thread_summary
    command = state.bot.tree.get_command("summarize")
    await command.callback(state.interaction, topic_id=0)
    state.thread.send.assert_awaited_once()
    embed = state.thread.send.call_args.kwargs["embed"]
    assert "Mai học gì" in embed.title
    assert any("Avalanche" in field.value and "Docker" in field.value for field in embed.fields)
    assert state.thread.send.call_args.kwargs["allowed_mentions"].everyone is False
    state.backend.get_thread_topic.assert_awaited_once_with("7", "2000")
    assert state.backend.get_topic_summary.call_args.kwargs["channel_id"] == "1"


def test_summarize_requires_no_topic_number_in_a_thread(thread_summary):
    command = thread_summary.bot.tree.get_command("summarize")
    assert command.parameters[0].required is False


async def test_unmapped_thread_cannot_publish_another_topics_summary(thread_summary):
    state = thread_summary
    state.backend.get_thread_topic.return_value = None
    await state.bot.tree.get_command("summarize").callback(state.interaction, topic_id=0)
    state.thread.send.assert_not_awaited()
    state.backend.get_topic_summary.assert_not_awaited()


async def test_thread_outside_configured_output_cannot_publish_summary(thread_summary):
    state = thread_summary
    state.thread.parent_id = 999
    await state.bot.tree.get_command("summarize").callback(state.interaction, topic_id=0)
    state.thread.send.assert_not_awaited()
    state.backend.get_thread_topic.assert_not_awaited()


@pytest.mark.parametrize("guild,status", [("g", 200), ("other", 404)])
async def test_thread_lookup_is_guild_scoped(api_client, database_factory, guild, status):
    async with database_factory() as session:
        session.add(
            TopicRecord(
                id="study",
                guild_id="g",
                channel_id="input",
                title="Mai học gì",
                discord_thread_id="2000",
            )
        )
        await session.commit()
    response = await api_client.get(
        "/api/v1/threads/2000/topic",
        params={"guild_id": guild},
        headers={"X-API-Key": "bot-test-key"},
    )
    assert response.status_code == status
    if status == 200:
        assert response.json()["topic_id"] == "study"
        assert response.json()["channel_id"] == "input"


async def test_thread_lookup_requires_bot_auth(api_client):
    response = await api_client.get("/api/v1/threads/2000/topic?guild_id=g")
    assert response.status_code == 401

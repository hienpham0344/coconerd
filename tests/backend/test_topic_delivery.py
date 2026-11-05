from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.delivery import DeliveryError
from bot.main import create_bot


async def empty_history(**kwargs):
    if False:
        yield None


@pytest.fixture
def delivery(monkeypatch, tmp_path):
    bot = create_bot()
    bot._connection.user = SimpleNamespace(id=99)
    bot.commands_synced = True
    bot.greeting_sent = True
    bot.wait_until_ready = AsyncMock()
    bot.backend = MagicMock()
    receipts = {}
    bot.backend.get_delivery_receipt = AsyncMock(side_effect=lambda key: receipts.get(key))

    async def save_receipt(key, value):
        receipts[key] = value

    bot.backend.put_delivery_receipt = AsyncMock(side_effect=save_receipt)
    bot.backend.get_guild_settings = AsyncMock(
        return_value={
            "enabled": True,
            "allowed_channel_ids": ["1"],
            "output_channel_id": "2",
        }
    )
    topic = {"topic_id": "topic", "title": "Ăn trưa", "discord_thread_id": None}
    bot.backend.get_topic = AsyncMock(side_effect=lambda *args: dict(topic))
    bot.backend.get_topic_messages = AsyncMock(return_value=[])
    bot.backend.complete_action = AsyncMock(return_value=True)
    bot.backend.fail_action = AsyncMock(return_value=True)
    guild = SimpleNamespace(id=7, me=SimpleNamespace(id=99))
    messages = {}
    thread = MagicMock(spec=discord.Thread)
    thread.id, thread.parent_id, thread.guild, thread.archived = 2000, 2, guild, False
    thread.history = empty_history
    thread.edit = AsyncMock()

    async def send_member(*args, **kwargs):
        message = SimpleNamespace(
            id=3000 + len(messages),
            content=args[0] if args else "",
            edit=AsyncMock(),
            author=SimpleNamespace(id=99),
        )
        messages[message.id] = message
        return message

    thread.send = AsyncMock(side_effect=send_member)
    thread.fetch_message = AsyncMock(side_effect=lambda identifier: messages[identifier])
    channels = {}
    for identifier in (1, 2):
        channel = MagicMock(spec=discord.TextChannel)
        channel.id, channel.guild, channel.name = identifier, guild, str(identifier)
        channel.permissions_for.return_value = discord.Permissions.all()
        channel.threads = []
        channels[identifier] = channel
    source, output = channels[1], channels[2]
    source_thread = MagicMock(spec=discord.Thread)
    source_thread.id, source_thread.parent_id = 1000, 1
    source_thread.guild, source_thread.archived = guild, False
    source_thread.history = empty_history
    source_thread.send = AsyncMock(return_value=SimpleNamespace(id=999))
    source.create_thread = AsyncMock(return_value=source_thread)
    channels[1000] = source_thread
    starter = MagicMock(spec=discord.Message)
    starter.id = 2000
    starter.edit = AsyncMock()

    async def create_thread(**kwargs):
        channels[2000] = thread
        return thread

    starter.create_thread = AsyncMock(side_effect=create_thread)
    output.send = AsyncMock(return_value=starter)
    output.fetch_message = AsyncMock(return_value=starter)
    bot.get_channel = MagicMock(side_effect=lambda identifier: channels.get(identifier))

    async def fetch_channel(identifier):
        if identifier not in channels:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Missing")
        return channels[identifier]

    bot.fetch_channel = AsyncMock(side_effect=fetch_channel)
    return SimpleNamespace(
        bot=bot,
        source=source,
        output=output,
        starter=starter,
        thread=thread,
        topic=topic,
        messages=messages,
    )


def action(kind="CREATE_THREAD", source_id="m1", content="Ăn trưa lúc 11:30"):
    return {
        "action_id": "action-" + source_id,
        "type": kind,
        "guild_id": "7",
        "channel_id": "1",
        "topic_id": "topic",
        "payload": {
            "title": "Ăn trưa",
            "source_message_id": source_id,
            "source_author_name": "Lan",
            "source_content": content,
        },
    }


async def run_action(delivery, item):
    calls = 0

    def closed():
        nonlocal calls
        calls += 1
        return calls > 1

    delivery.bot.is_closed = MagicMock(side_effect=closed)
    delivery.bot.backend.claim_actions = AsyncMock(return_value=[item])
    await delivery.bot.on_ready()
    await delivery.bot._outbox_task


async def test_topic_header_and_linked_thread_are_created_in_output_channel(delivery):
    await run_action(delivery, action())
    delivery.output.send.assert_awaited_once()
    assert delivery.output.send.call_args.args[0] == "Ăn trưa"
    assert delivery.starter.create_thread.call_args.kwargs["name"] == "Ăn trưa"
    delivery.source.create_thread.assert_not_awaited()
    assert delivery.thread.send.call_args.args[0] == "[Lan]-Ăn trưa lúc 11:30"
    assert delivery.bot.backend.complete_action.call_args.kwargs["discord_thread_id"] == "2000"


async def test_retry_after_lost_ack_reuses_header_thread_and_forwarded_message(delivery):
    delivery.bot.backend.complete_action.side_effect = [False, True]
    await run_action(delivery, action())
    await run_action(delivery, action())
    assert delivery.output.send.await_count == 1
    assert delivery.starter.create_thread.await_count == 1
    assert delivery.thread.send.await_count == 1


async def test_old_input_thread_is_replaced_and_existing_topic_messages_are_replayed(delivery):
    delivery.topic["discord_thread_id"] = "1000"
    delivery.bot.backend.get_topic_messages.return_value = [
        {
            "message_id": "m1",
            "author_name": "Lan",
            "content": "Ăn trưa lúc 11:30",
            "created_at": "2026-11-05T12:00:00Z",
        }
    ]
    await run_action(delivery, action("APPEND_MESSAGE", "m2", "Mình đồng ý"))
    assert [call.args[0] for call in delivery.thread.send.await_args_list] == [
        "[Lan]-Ăn trưa lúc 11:30",
        "[Lan]-Mình đồng ý",
    ]
    completion = delivery.bot.backend.complete_action.call_args.kwargs
    assert completion["previous_discord_thread_id"] == "1000"
    assert completion["discord_channel_id"] == "2"


async def test_forwarding_preserves_long_member_messages_without_pinging(delivery):
    content = "@everyone " + "🥥" * 2100
    await run_action(delivery, action(content=content))
    calls = delivery.thread.send.await_args_list
    assert len(calls) > 1
    assert "".join(call.args[0].removeprefix("[Lan]-") for call in calls) == content
    for call in calls:
        assert len(call.args[0].encode("utf-16-le")) // 2 <= 2000
        assert call.kwargs["allowed_mentions"].everyone is False


async def test_missing_output_configuration_does_not_post_to_input(delivery):
    delivery.bot.backend.get_guild_settings.return_value["output_channel_id"] = None
    await run_action(delivery, action())
    delivery.source.create_thread.assert_not_awaited()
    delivery.output.send.assert_not_awaited()
    delivery.bot.backend.fail_action.assert_awaited_once()


async def test_backfill_reads_every_page_in_chronological_order(delivery):
    history = [
        {
            "message_id": f"m{index}",
            "author_name": "Lan",
            "content": str(index),
            "created_at": f"2026-11-05T12:{index // 60:02}:{index % 60:02}Z",
        }
        for index in range(101)
    ]
    delivery.bot.backend.get_topic_messages.side_effect = [history[:0:-1], history[:1]]
    await run_action(delivery, action(source_id="m100", content="100"))
    assert [call.args[0] for call in delivery.thread.send.await_args_list] == [
        f"[Lan]-{index}" for index in range(101)
    ]
    calls = delivery.bot.backend.get_topic_messages.await_args_list
    assert calls[1].kwargs["before"] == history[1]["created_at"]


async def test_retry_after_thread_creation_failure_reuses_header(delivery):
    create_thread = delivery.starter.create_thread.side_effect
    delivery.starter.create_thread.side_effect = RuntimeError("Temporary failure")
    await run_action(delivery, action())
    delivery.starter.create_thread.side_effect = create_thread
    await run_action(delivery, action())
    delivery.output.send.assert_awaited_once()
    assert delivery.starter.create_thread.await_count == 2
    delivery.thread.send.assert_awaited_once()
    delivery.bot.backend.complete_action.assert_awaited_once()


async def test_retry_after_missing_thread_receipt_recovers_from_header(delivery):
    await run_action(delivery, action())
    await delivery.bot.backend.put_delivery_receipt("7:topic:2:thread", "")
    await run_action(delivery, action())
    delivery.output.send.assert_awaited_once()
    delivery.starter.create_thread.assert_awaited_once()
    delivery.thread.send.assert_awaited_once()


async def test_receipt_storage_outage_stops_discord_delivery(delivery):
    delivery.bot.backend.get_delivery_receipt.side_effect = DeliveryError(
        "Backend unavailable", retryable=True
    )
    await run_action(delivery, action())
    delivery.output.send.assert_not_awaited()
    delivery.thread.send.assert_not_awaited()
    delivery.bot.backend.fail_action.assert_awaited_once()


async def test_summary_updates_the_existing_header_without_duplicate_posts(delivery):
    await run_action(delivery, action())
    item = action("UPSERT_SUMMARY")
    item["payload"] = {"summary": {"overview": "Bản đầu"}, "version": 1}
    await run_action(delivery, item)
    await run_action(delivery, item)
    item["payload"] = {"summary": {"overview": "Bản mới"}, "version": 2}
    await run_action(delivery, item)
    item["payload"] = {"summary": {"overview": "Bản cũ"}, "version": 1}
    await run_action(delivery, item)
    delivery.output.send.assert_awaited_once()
    delivery.thread.send.assert_awaited_once()
    assert delivery.starter.edit.await_count == 2
    embed = delivery.starter.edit.call_args.kwargs["embed"]
    assert [field.value for field in embed.fields] == ["Bản mới"]
    assert delivery.starter.edit.call_args.kwargs["allowed_mentions"].everyone is False


async def test_initial_header_separates_proposals_from_decisions(delivery):
    item = action()
    item["payload"]["summary"] = {
        "overview": "Nhóm đang chọn chỗ ăn trưa, chưa chốt địa điểm.",
        "proposals": ["Lan đề xuất ăn phở."],
        "decisions": [],
        "open_questions": ["Ai tham gia ăn trưa?"],
        "action_items": [],
    }
    await run_action(delivery, item)
    embed = delivery.output.send.call_args.kwargs["embed"]
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Nội dung chính"] == "Nhóm đang chọn chỗ ăn trưa, chưa chốt địa điểm."
    assert fields["Đề xuất"] == "• Lan đề xuất ăn phở."
    assert fields["Còn cần làm rõ"] == "• Ai tham gia ăn trưa?"
    assert "Đã chốt" not in fields


async def test_long_notes_keep_the_latest_decision_visible(delivery):
    item = action()
    item["payload"]["summary"] = {
        "overview": "Đang chọn món ăn trưa.",
        "decisions": [f"Kết luận cũ {index}: " + "x" * 400 for index in range(10)]
        + ["Chốt ăn phở lúc 12h tại quán A."],
    }
    await run_action(delivery, item)
    embed = delivery.output.send.call_args.kwargs["embed"]
    decision = next(field.value for field in embed.fields if field.name == "Đã chốt")
    assert "Chốt ăn phở lúc 12h tại quán A." in decision
    assert "Kết luận cũ 0" not in decision


async def test_conversation_note_fits_discord_limits_with_emoji(delivery):
    item = action()
    item["payload"]["summary"] = {
        "overview": "🥥" * 2000,
        **{
            field: ["🥥" * 500] * 20
            for field in ("proposals", "decisions", "action_items", "open_questions")
        },
    }
    await run_action(delivery, item)
    embed = delivery.output.send.call_args.kwargs["embed"]

    def units(text):
        return len(text.encode("utf-16-le")) // 2

    assert all(units(field.value) <= 1024 for field in embed.fields)
    assert sum(units(field.name) + units(field.value) for field in embed.fields) <= 6000


async def test_failed_history_fetch_is_retried_before_marking_backfill_done(delivery):
    delivery.bot.backend.get_topic_messages.side_effect = [RuntimeError("Backend down"), []]
    await run_action(delivery, action())
    delivery.bot.backend.complete_action.assert_not_awaited()
    await run_action(delivery, action())
    assert delivery.bot.backend.get_topic_messages.await_count == 2
    delivery.bot.backend.complete_action.assert_awaited_once()
    delivery.output.send.assert_awaited_once()

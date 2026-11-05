import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from test_message_media import ATTACHMENT

from bot.delivery import DeliveryError, DeliveryReceipts, TopicDelivery


def test_attachment_capture_keeps_original_url_and_spoiler():
    from bot.media import attachment_payloads

    message = SimpleNamespace(
        attachments=[
            SimpleNamespace(
                id=55,
                filename="photo.png",
                url=ATTACHMENT["url"],
                content_type="image/png",
                size=12,
                is_spoiler=lambda: True,
            )
        ]
    )
    assert attachment_payloads(message) == [{**ATTACHMENT, "spoiler": True}]


@pytest.fixture
def media_delivery():
    receipts = {}
    backend = SimpleNamespace(
        get_delivery_receipt=AsyncMock(side_effect=lambda key: receipts.get(key)),
        put_delivery_receipt=AsyncMock(
            side_effect=lambda key, value: receipts.update({key: value})
        ),
    )
    guild = SimpleNamespace(id=7, filesize_limit=1024, me=None)
    attachment = SimpleNamespace(
        id=55,
        filename="photo.png",
        url=ATTACHMENT["url"],
        size=12,
        is_spoiler=lambda: True,
        to_file=AsyncMock(
            side_effect=lambda **kwargs: discord.File(io.BytesIO(b"image"), filename="photo.png")
        ),
    )
    source = SimpleNamespace(guild=guild, attachments=[attachment])
    channel = SimpleNamespace(guild=guild, fetch_message=AsyncMock(return_value=source))
    bot = SimpleNamespace(get_channel=lambda identifier: channel, fetch_channel=AsyncMock())
    thread = SimpleNamespace(
        id=99,
        guild=guild,
        send=AsyncMock(side_effect=lambda *args, **kwargs: SimpleNamespace(id=100 + len(receipts))),
    )
    delivery = TopicDelivery(bot, backend, DeliveryReceipts(backend))
    delivery._ensure_thread = AsyncMock(return_value=(thread, {}, "scope", "99", "2"))
    item = {
        "type": "APPEND_MESSAGE",
        "guild_id": "7",
        "channel_id": "1",
        "topic_id": "topic",
        "payload": {
            "source_message_id": "10",
            "source_author_name": "Lan",
            "source_content": "",
            "source_attachments": [dict(ATTACHMENT)],
        },
    }
    return SimpleNamespace(
        delivery=delivery,
        item=item,
        thread=thread,
        channel=channel,
        source=source,
        attachment=attachment,
        receipts=receipts,
    )


async def test_attachment_only_uploads_file_and_retry_does_not_duplicate(media_delivery):
    state = media_delivery
    await state.delivery.deliver(state.item)
    await state.delivery.deliver(state.item)
    state.attachment.to_file.assert_awaited_once_with(use_cached=True, spoiler=True)
    state.channel.fetch_message.assert_awaited_once_with(10)
    state.thread.send.assert_awaited_once()
    assert "file" in state.thread.send.call_args.kwargs
    assert state.thread.send.call_args.args[0] == "[Lan]-"


async def test_link_and_caption_are_preserved_with_attached_image(media_delivery):
    state = media_delivery
    text = "Ảnh đây https://example.com/page?a=1&b=2"
    state.item["payload"]["source_content"] = text
    await state.delivery.deliver(state.item)
    assert state.thread.send.call_args_list[0].args[0] == "[Lan]-" + text
    assert state.thread.send.await_count == 2


async def test_oversize_attachment_keeps_filename_and_link_without_downloading(media_delivery):
    state = media_delivery
    state.attachment.size = 2000
    await state.delivery.deliver(state.item)
    state.attachment.to_file.assert_not_awaited()
    sent = state.thread.send.call_args.args[0]
    assert state.attachment.url in sent and "photo.png" in sent


async def test_source_channel_must_belong_to_the_same_guild(media_delivery):
    state = media_delivery
    state.channel.guild = SimpleNamespace(id=8)
    with pytest.raises(DeliveryError):
        await state.delivery.deliver(state.item)
    state.channel.fetch_message.assert_not_awaited()
    state.attachment.to_file.assert_not_awaited()


def test_long_message_does_not_split_a_normal_url_across_parts():
    from bot.delivery import member_message_parts

    url = "https://example.com/path?" + "a" * 100
    content = "x" * 1950 + " " + url + " cuối tin"
    parts = member_message_parts("Lan", content)
    assert any(url in part for part in parts)
    assert "".join(part.removeprefix("[Lan]-") for part in parts) == content


async def test_spoiler_fallback_does_not_reveal_the_attachment(media_delivery):
    state = media_delivery
    state.attachment.size = 2000
    state.item["payload"]["source_attachments"][0]["spoiler"] = True
    await state.delivery.deliver(state.item)
    assert "||" + state.attachment.url + "||" in state.thread.send.call_args.args[0]


async def test_multiple_images_use_independent_receipts_across_partial_retry(media_delivery):
    state = media_delivery
    second = SimpleNamespace(
        id=56,
        filename="next.png",
        size=12,
        url=ATTACHMENT["url"].replace("55", "56"),
        is_spoiler=lambda: False,
        to_file=AsyncMock(
            side_effect=[
                OSError("temporary"),
                discord.File(io.BytesIO(b"next"), filename="next.png"),
            ]
        ),
    )
    state.source.attachments.append(second)
    state.item["payload"]["source_attachments"].append({**ATTACHMENT, "id": "56"})
    with pytest.raises(OSError):
        await state.delivery.deliver(state.item)
    assert state.thread.send.await_count == 1
    await state.delivery.deliver(state.item)
    assert state.thread.send.await_count == 2
    state.attachment.to_file.assert_awaited_once()


async def test_long_attachment_fallback_url_stays_complete_within_discord_limits(media_delivery):
    state = media_delivery
    state.attachment.size = 2000
    state.attachment.url = "https://cdn.discordapp.com/attachments/1/55/" + "a" * 2200
    await state.delivery.deliver(state.item)
    args, kwargs = state.thread.send.call_args
    assert len(args[0].encode("utf-16-le")) // 2 <= 2000
    assert state.attachment.url in kwargs["embed"].description


async def test_bot_ingests_an_attachment_without_a_caption(monkeypatch):
    from bot.main import create_bot

    bot = create_bot()
    bot.backend = SimpleNamespace(
        get_guild_settings=AsyncMock(return_value={"enabled": True, "allowed_channel_ids": ["1"]}),
        ingest_message=AsyncMock(return_value=True),
    )
    bot.process_commands = AsyncMock()
    channel = MagicMock(spec=discord.TextChannel)
    channel.id, channel.name = 1, "input"
    message = SimpleNamespace(
        guild=SimpleNamespace(id=7),
        channel=channel,
        content="",
        attachments=[object()],
        author=SimpleNamespace(bot=False, name="Lan"),
    )
    await bot.on_message(message)
    bot.backend.ingest_message.assert_awaited_once_with(message)


async def test_backend_client_sends_attachment_metadata():
    from datetime import UTC, datetime

    from bot.main import BackendClient

    item = SimpleNamespace(
        id=55,
        filename="photo.png",
        url=ATTACHMENT["url"],
        content_type="image/png",
        size=12,
        is_spoiler=lambda: False,
    )
    message = SimpleNamespace(
        guild=SimpleNamespace(id=7),
        channel=SimpleNamespace(id=1),
        id=10,
        content="",
        author=SimpleNamespace(id=3, display_name="Lan"),
        created_at=datetime.now(UTC),
        reference=None,
        attachments=[item],
    )
    session = MagicMock()
    session.post.return_value.__aenter__ = AsyncMock(return_value=SimpleNamespace(status=202))
    session.post.return_value.__aexit__ = AsyncMock(return_value=False)
    backend = BackendClient("http://backend", "test-key")
    backend.get_session = AsyncMock(return_value=session)
    assert await backend.ingest_message(message)
    assert session.post.call_args.kwargs["json"]["attachments"] == [ATTACHMENT]

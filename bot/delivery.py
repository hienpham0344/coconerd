"""Deliver topic actions into message-linked threads in the configured output channel."""

import re
from contextlib import suppress

import discord


class DeliveryError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class DeliveryReceipts:
    """Keep Discord result IDs in the backend's shared database."""

    def __init__(self, backend):
        self.backend = backend

    async def get(self, key: str) -> str | None:
        return await self.backend.get_delivery_receipt(key)

    async def put(self, key: str, value: str) -> None:
        await self.backend.put_delivery_receipt(key, value)


def member_message_parts(author: str, content: str) -> list[str]:
    name = " ".join(str(author).split())[:200] or "Thành viên"
    prefix = f"[{name}]-"
    limit = 2000 - len(prefix.encode("utf-16-le")) // 2
    parts, current, size = [], [], 0
    for token in re.findall(
        r"\[[^\]\n]*\]\(https?://[^\s)]+\)|https?://\S+|.", str(content), re.DOTALL
    ):
        token_size = len(token.encode("utf-16-le")) // 2
        if token_size <= limit:
            if size + token_size > limit:
                parts.append(prefix + "".join(current))
                current, size = [], 0
            current.append(token)
            size += token_size
        else:
            for character in token:
                units = len(character.encode("utf-16-le")) // 2
                if size + units > limit:
                    parts.append(prefix + "".join(current))
                    current, size = [], 0
                current.append(character)
                size += units
    parts.append(prefix + "".join(current))
    return parts


def _note_text(text: str, limit: int = 1000) -> str:
    encoded = text.encode("utf-16-le")
    if len(encoded) <= limit * 2:
        return text
    lines = text.splitlines()
    if len(lines) > 1:
        # Memory appends new facts; keep the newest complete facts visible.
        selected, remaining = [], limit - 2
        for line in reversed(lines):
            size = len(line.encode("utf-16-le")) // 2
            if size > remaining:
                if not selected:
                    selected.append(_note_text(line, remaining))
                break
            selected.append(line)
            remaining -= size + 1
        return "…\n" + "\n".join(reversed(selected))
    return encoded[: (limit - 1) * 2].decode("utf-16-le", errors="ignore").rstrip() + "…"


def conversation_note_embed(summary: dict) -> discord.Embed | None:
    """Render the useful facts on the thread's starter message, within Discord limits."""
    embed = discord.Embed(color=0x22C55E)
    overview = summary.get("overview")
    if isinstance(overview, str) and overview.strip():
        embed.add_field(name="Nội dung chính", value=_note_text(overview.strip()), inline=False)
    for key, name in (
        ("proposals", "Đề xuất"),
        ("decisions", "Đã chốt"),
        ("action_items", "Việc cần làm"),
        ("open_questions", "Còn cần làm rõ"),
    ):
        values = summary.get(key)
        if isinstance(values, list):
            facts = [value.strip() for value in values if isinstance(value, str) and value.strip()]
            if facts:
                embed.add_field(
                    name=name,
                    value=_note_text("\n".join(f"• {fact}" for fact in facts)),
                    inline=False,
                )
    return embed if embed.fields else None


class TopicDelivery:
    def __init__(self, bot, backend, receipts: DeliveryReceipts):
        self.bot, self.backend, self.receipts = bot, backend, receipts

    async def _thread_in_output(self, identifier, guild_id: str, output_id: str):
        if not identifier:
            return None
        try:
            thread = self.bot.get_channel(int(identifier))
            if thread is None:
                thread = await self.bot.fetch_channel(int(identifier))
        except discord.NotFound:
            return None
        if str(thread.guild.id) != guild_id or str(getattr(thread, "parent_id", "")) != output_id:
            return None
        if getattr(thread, "archived", False):
            await thread.edit(archived=False)
        return thread

    async def _forward(
        self,
        thread,
        scope: str,
        source_id: str,
        author: str,
        content: str,
        attachments: list[dict] | None = None,
        source_channel_id: str | None = None,
    ):
        if not source_id:
            raise DeliveryError("Source message ID is missing")
        first_id = None
        parts = member_message_parts(author, content) if content or not attachments else []
        for index, part in enumerate(parts):
            key = f"{scope}:member:{thread.id}:{source_id}:{index}"
            identifier = await self.receipts.get(key)
            if identifier is None:
                sent = await thread.send(part, allowed_mentions=discord.AllowedMentions.none())
                identifier = str(sent.id)
                await self.receipts.put(key, identifier)
            first_id = first_id or identifier
        if attachments:
            attachment_id = await self._forward_attachments(
                thread, scope, source_id, author, attachments, source_channel_id
            )
            first_id = first_id or attachment_id
        return first_id

    async def _forward_attachments(
        self,
        thread,
        scope: str,
        source_id: str,
        author: str,
        attachments: list[dict],
        source_channel_id: str | None,
    ) -> str | None:
        source = None
        source_missing = False
        first_id = None
        for metadata in attachments:
            key = f"{scope}:attachment:{thread.id}:{source_id}:{metadata['id']}"
            identifier = await self.receipts.get(key)
            if identifier is not None:
                first_id = first_id or identifier
                continue
            if source is None and not source_missing:
                if not source_channel_id:
                    raise DeliveryError("Attachment source channel is missing")
                try:
                    channel = self.bot.get_channel(int(source_channel_id))
                    if channel is None:
                        channel = await self.bot.fetch_channel(int(source_channel_id))
                    if str(channel.guild.id) != str(thread.guild.id):
                        raise DeliveryError("Attachment source belongs to another guild")
                    source = await channel.fetch_message(int(source_id))
                except discord.NotFound:
                    source_missing = True
                except discord.Forbidden as exc:
                    raise DeliveryError("Cannot read attachment source channel") from exc
            attachment = (
                next(
                    (item for item in source.attachments if str(item.id) == str(metadata["id"])),
                    None,
                )
                if source is not None
                else None
            )
            file = None
            fallback_reason = "nguồn không còn khả dụng"
            if attachment is not None:
                fallback_reason = "vượt giới hạn tải file của server"
                can_upload = True
                if thread.guild.me is not None:
                    can_upload = thread.permissions_for(thread.guild.me).attach_files
                if not can_upload:
                    fallback_reason = "bot thiếu quyền Attach Files"
                elif attachment.size <= thread.guild.filesize_limit:
                    try:
                        file = await attachment.to_file(
                            use_cached=True, spoiler=attachment.is_spoiler()
                        )
                    except discord.NotFound:
                        fallback_reason = "ảnh/tệp gốc không còn khả dụng"
                    except discord.Forbidden:
                        fallback_reason = "không có quyền tải ảnh/tệp gốc"
            prefix = member_message_parts(author, "")[0]
            try:
                if file is not None:
                    sent = await thread.send(
                        prefix, file=file, allowed_mentions=discord.AllowedMentions.none()
                    )
                else:
                    url = attachment.url if attachment is not None else metadata["url"]
                    if metadata.get("spoiler") or (
                        attachment is not None and attachment.is_spoiler()
                    ):
                        url = f"||{url}||"
                    name = " ".join(str(metadata["filename"]).split())[:200]
                    # Keep the complete URL on its own line, without Markdown rewriting.
                    caption = f"{prefix}{name} ({fallback_reason})"
                    if len((caption + "\n" + url).encode("utf-16-le")) // 2 <= 2000:
                        sent = await thread.send(
                            caption + "\n" + url,
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    else:
                        sent = await thread.send(
                            caption,
                            embed=discord.Embed(description=url),
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
            finally:
                if file is not None:
                    file.close()
            identifier = str(sent.id)
            await self.receipts.put(key, identifier)
            first_id = first_id or identifier
        return first_id

    async def _ensure_thread(self, action):
        guild_id, topic_id = str(action["guild_id"]), str(action["topic_id"])
        settings = await self.backend.get_guild_settings(guild_id)
        output_id = str(settings.get("output_channel_id") or "")
        if not settings.get("enabled") or not output_id:
            raise DeliveryError("Configure an Output Channel with /setup first")
        output = self.bot.get_channel(int(output_id))
        if output is None:
            output = await self.bot.fetch_channel(int(output_id))
        if str(output.guild.id) != guild_id or not isinstance(output, discord.TextChannel):
            raise DeliveryError("Output must be a text channel in the action's guild")
        member = output.guild.me or output.guild.get_member(self.bot.user.id)
        if member:
            permissions = output.permissions_for(member)
            required = (
                "view_channel",
                "send_messages",
                "create_public_threads",
                "send_messages_in_threads",
                "read_message_history",
            )
            missing = [
                permission for permission in required if not getattr(permissions, permission)
            ]
            if missing:
                raise DeliveryError("Output Channel lacks permissions: " + ", ".join(missing))
        topic = await self.backend.get_topic(guild_id, topic_id)
        if topic is None:
            raise DeliveryError("Cannot load topic from backend", retryable=True)
        previous = topic.get("discord_thread_id")
        scope = f"{guild_id}:{topic_id}:{output_id}"
        thread = await self._thread_in_output(previous, guild_id, output_id)
        if thread is None:
            thread = await self._thread_in_output(
                await self.receipts.get(scope + ":thread"), guild_id, output_id
            )
        if thread is None:
            header_id = await self.receipts.get(scope + ":header")
            header = None
            if header_id:
                with suppress(discord.NotFound):
                    header = await output.fetch_message(int(header_id))
            title = " ".join(
                str(topic.get("title") or action["payload"].get("title") or "Chủ đề mới").split()
            )[:100]
            if header is None:
                header = await output.send(
                    title,
                    embed=conversation_note_embed(action["payload"].get("summary", {})),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                await self.receipts.put(scope + ":header", str(header.id))
            else:
                thread = await self._thread_in_output(str(header.id), guild_id, output_id)
            if thread is None:
                thread = await header.create_thread(name=title, auto_archive_duration=1440)
            await self.receipts.put(scope + ":thread", str(thread.id))
        marker = f"{scope}:backfilled:{thread.id}"
        if await self.receipts.get(marker) is None:
            history, before = [], None
            while True:
                page = await self.backend.get_topic_messages(
                    guild_id, topic_id, limit=100, before=before, require_success=True
                )
                history.extend(page)
                if len(page) < 100:
                    break
                cursor = page[-1]["created_at"]
                if cursor == before:
                    raise DeliveryError("Topic history cursor did not advance", retryable=True)
                before = cursor
            for message in reversed(history):
                await self._forward(
                    thread,
                    scope,
                    str(message["message_id"]),
                    message["author_name"],
                    message["content"],
                    message.get("attachments", []),
                    message.get("channel_id") or action["channel_id"],
                )
            await self.receipts.put(marker, "1")
        return thread, topic, scope, previous, output_id

    async def _update_note(self, action, thread, scope: str, output_id: str) -> str:
        header_id = await self.receipts.get(scope + ":header") or str(thread.id)
        version_key = f"{scope}:note-version:{header_id}"
        version = int(action["payload"].get("version", 0))
        saved_version = await self.receipts.get(version_key)
        if saved_version is None or int(saved_version) < version:
            output = self.bot.get_channel(int(output_id))
            if output is None:
                output = await self.bot.fetch_channel(int(output_id))
            header = await output.fetch_message(int(header_id))
            await header.edit(
                embed=conversation_note_embed(action["payload"].get("summary", {})),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            await self.receipts.put(version_key, str(version))
        return header_id

    async def deliver(self, action) -> dict:
        kind, payload = action["type"], action["payload"]
        if kind not in {"CREATE_THREAD", "APPEND_MESSAGE", "UPSERT_SUMMARY"}:
            raise DeliveryError("Unsupported action type: " + kind)
        thread, topic, scope, previous, output_id = await self._ensure_thread(action)
        if kind == "UPSERT_SUMMARY":
            message_id = await self._update_note(action, thread, scope, output_id)
        elif payload.get("source_message_id"):
            message_id = await self._forward(
                thread,
                scope,
                str(payload["source_message_id"]),
                payload.get("source_author_name", "Thành viên"),
                payload.get("source_content", ""),
                payload.get("source_attachments", []),
                str(action["channel_id"]),
            )
        else:
            message_id = await self.receipts.get(scope + ":header")
        result = {"discord_thread_id": str(thread.id), "discord_message_id": message_id}
        if str(previous or "") != str(thread.id):
            result.update(previous_discord_thread_id=previous, discord_channel_id=output_id)
        return result

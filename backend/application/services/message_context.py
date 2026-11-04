"""Select a small, scoped set of prior messages for one classification."""

from datetime import UTC, datetime, timedelta

from backend.application.ports.persistence import MessagesRepository
from backend.application.read_models import ContextMessage, MessageReadModel
from backend.application.topic_terms import search_terms
from backend.domain.entities import ConversationMessage

MAX_REPLY_ANCESTORS = 3
MAX_CONTEXT_MESSAGES = 6
MAX_MESSAGE_CHARS = 400
MAX_CONTEXT_CHARS = 1600
RECENT_MINUTES = 10


def bound_context(items: list[ContextMessage]) -> list[ContextMessage]:
    from dataclasses import replace

    priorities = {
        "followup_clarification": 0,
        "reply_ancestor": 1,
        "topic_evidence": 2,
        "recent": 3,
    }
    selected = {}
    remaining = MAX_CONTEXT_CHARS
    for item in sorted(items, key=lambda item: priorities.get(item.relation, 4)):
        if item.message_id in selected or not item.content.strip():
            continue
        content = item.content[: min(remaining, MAX_MESSAGE_CHARS)]
        if not content or len(selected) == MAX_CONTEXT_MESSAGES:
            break
        selected[item.message_id] = replace(item, content=content, created_at=_utc(item.created_at))
        remaining -= len(content)
    return sorted(selected.values(), key=lambda item: (item.created_at, item.message_id))


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def build_message_context(
    messages: MessagesRepository, target: ConversationMessage
) -> list[ContextMessage]:
    """Prioritize reply ancestry, then recent messages; return chronological JSON-ready items."""
    chosen: list[ContextMessage] = []
    seen = {target.message_id}
    remaining_chars = MAX_CONTEXT_CHARS

    def include(record: MessageReadModel, relation: str) -> None:
        nonlocal remaining_chars
        if record.discord_message_id in seen or len(chosen) >= MAX_CONTEXT_MESSAGES:
            return
        seen.add(record.discord_message_id)
        content = record.content[: min(MAX_MESSAGE_CHARS, remaining_chars)]
        if not content:
            return
        chosen.append(
            ContextMessage(
                message_id=record.discord_message_id,
                author_id=record.author_id,
                author_name=record.author_name,
                created_at=_utc(record.created_at),
                relation=relation,
                content=content,
            )
        )
        remaining_chars -= len(content)

    reply_id = target.reply_to_message_id
    next_time = _utc(target.created_at)
    for _ in range(MAX_REPLY_ANCESTORS):
        if not reply_id or reply_id in seen:
            break
        ancestor = await messages.get_by_discord_id(target.guild_id, reply_id)
        if (
            ancestor is None
            or ancestor.channel_id != target.channel_id
            or _utc(ancestor.created_at) >= next_time
        ):
            break
        include(ancestor, "reply_ancestor")
        next_time = _utc(ancestor.created_at)
        reply_id = ancestor.reply_to_message_id

    if len(chosen) >= MAX_CONTEXT_MESSAGES or remaining_chars == 0:
        return sorted(chosen, key=lambda item: (item.created_at, item.message_id))

    recent = await messages.recent_before(
        target.guild_id,
        target.channel_id,
        target.created_at,
        limit=MAX_CONTEXT_MESSAGES * 2,
        after=_utc(target.created_at) - timedelta(minutes=RECENT_MINUTES),
    )
    target_terms = set(search_terms(target.content))
    ranked_recent = sorted(
        recent,
        key=lambda item: (
            -len(target_terms & set(search_terms(item.content))),
            item.author_id != target.author_id,
        ),
    )
    for record in ranked_recent:
        if len(chosen) >= MAX_CONTEXT_MESSAGES or remaining_chars == 0:
            break
        include(record, "recent")
    return sorted(chosen, key=lambda item: (item.created_at, item.message_id))

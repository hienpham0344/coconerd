"""Conservative links for a single deferred-message reassessment."""

from datetime import UTC, datetime, timedelta

from backend.application.read_models import MessageReadModel
from backend.application.topic_terms import normalize_text

DEFER_WINDOW_SECONDS = 600
CONVERSATION_FOLLOWUP_SECONDS = 120


def is_conversation_followup(target: MessageReadModel, followup: MessageReadModel) -> bool:
    """A nearby turn is possible evidence, never proof that its topic matches."""
    return (
        (target.guild_id, target.channel_id) == (followup.guild_id, followup.channel_id)
        and utc(target.created_at)
        < utc(followup.created_at)
        <= utc(target.created_at) + timedelta(seconds=CONVERSATION_FOLLOWUP_SECONDS)
        and not followup.reply_to_message_id
        and bool(normalize_text(followup.content))
        and normalize_text(followup.content) != normalize_text(target.content)
    )


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def is_clarification(target: MessageReadModel, followup: MessageReadModel) -> bool:
    if (target.guild_id, target.channel_id) != (followup.guild_id, followup.channel_id):
        return False
    if (
        not utc(target.created_at)
        < utc(followup.created_at)
        <= utc(target.created_at) + timedelta(seconds=DEFER_WINDOW_SECONDS)
    ):
        return False
    text = normalize_text(followup.content)
    if not text:
        return False
    if followup.reply_to_message_id:
        return followup.reply_to_message_id == target.discord_message_id
    return target.author_id == followup.author_id and any(
        text.startswith(prefix) for prefix in ("y minh la ", "minh noi ", "i mean ", "to clarify ")
    )

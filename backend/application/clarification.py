"""Conservative links for a single deferred-message reassessment."""

from datetime import UTC, datetime, timedelta

from backend.application.read_models import MessageReadModel
from backend.application.topic_terms import normalize_text

DEFER_WINDOW_SECONDS = 600


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

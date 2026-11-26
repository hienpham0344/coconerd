"""Guild-scoped topic reads, lifecycle and deletion use cases."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.application.errors import Conflict, InvalidTransition, NotFound
from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import MessageReadModel, SummaryReadModel, TopicReadModel
from backend.domain.entities import ConversationTopic
from backend.domain.enums import TopicStatus
from backend.domain.exceptions import InvalidTopicTransition


def _serialize_topic(topic: TopicReadModel) -> dict[str, Any]:
    return {
        "topic_id": topic.id,
        "guild_id": topic.guild_id,
        "channel_id": topic.channel_id,
        "title": topic.title,
        "description": topic.description,
        "status": topic.status,
        "version": topic.version,
        "sync_paused": topic.sync_paused,
        "discord_thread_id": topic.discord_thread_id,
        "last_activity": topic.last_activity_at,
    }


async def list_guild_topics(
    uow: UnitOfWork,
    guild_id: str,
    status: str | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if query and query.strip():
        rows = list(await uow.topics.search(guild_id, query.strip(), limit=limit))
        if status:
            rows = [row for row in rows if row.status == status]
        if offset > 0:
            rows = rows[offset : offset + limit]
    else:
        rows = list(await uow.topics.list_for_guild(guild_id, limit, offset, status))
    return [_serialize_topic(topic) for topic in rows]


async def get_topic(uow: UnitOfWork, guild_id: str, topic_id: str) -> TopicReadModel:
    topic = await uow.topics.get(guild_id, topic_id)
    if topic is None:
        raise NotFound("Topic not found")
    return topic


async def list_topics(
    uow: UnitOfWork, guild_id: str, channel_id: str | None, include_closed: bool, limit: int
) -> Sequence[TopicReadModel]:
    return await uow.topics.list_for_channel(guild_id, channel_id, include_closed, limit)


async def get_thread_topic(uow: UnitOfWork, guild_id: str, thread_id: str) -> TopicReadModel:
    topic = await uow.topics.get_by_thread(guild_id, thread_id)
    if topic is None:
        raise NotFound("Topic not found for this thread")
    return topic


async def get_topic_messages(
    uow: UnitOfWork, guild_id: str, topic_id: str, limit: int, before: str | None
) -> Sequence[MessageReadModel]:
    await get_topic(uow, guild_id, topic_id)
    try:
        before_at = datetime.fromisoformat(before) if before else None
    except ValueError as exc:
        raise InvalidTransition("before must be an ISO-8601 timestamp") from exc
    if before_at is not None:
        before_at = (
            before_at.replace(tzinfo=UTC) if before_at.tzinfo is None else before_at.astimezone(UTC)
        )
    return await uow.messages.list_for_topic(guild_id, topic_id, limit, before_at)


async def get_topic_summary(uow: UnitOfWork, guild_id: str, topic_id: str) -> SummaryReadModel:
    summary = await uow.summaries.latest(guild_id, topic_id)
    if summary is None:
        raise NotFound("Topic summary not found")
    return summary


async def close_topic(uow: UnitOfWork, guild_id: str, topic_id: str) -> None:
    topic = await get_topic(uow, guild_id, topic_id)
    lifecycle = ConversationTopic.create(topic.guild_id, topic.title)
    lifecycle.status = TopicStatus(topic.status)
    try:
        lifecycle.close()
    except InvalidTopicTransition as exc:
        raise Conflict(str(exc)) from exc
    try:
        await uow.topics.set_status(guild_id, topic_id, lifecycle.status.value)
    except RuntimeError as exc:
        raise Conflict("Topic changed concurrently") from exc
    close_episode = getattr(uow.topics, "close_latest_episode", None)
    if close_episode is not None:
        await close_episode(guild_id, topic_id, datetime.now(UTC))
    await uow.commit()


async def delete_topic(uow: UnitOfWork, guild_id: str, topic_id: str) -> None:
    await get_topic(uow, guild_id, topic_id)
    await uow.topics.delete_data(guild_id, topic_id)
    await uow.commit()


async def mark_dormant_topics(uow: UnitOfWork, dormant_after_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=dormant_after_days)
    inactive_topics = await uow.topics.inactive(cutoff)
    for topic in inactive_topics:
        await uow.topics.set_status(topic.guild_id, topic.id, TopicStatus.DORMANT.value)
        await uow.topics.close_latest_episode(topic.guild_id, topic.id, topic.last_activity_at)
    await uow.commit()
    return len(inactive_topics)

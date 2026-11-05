"""Guild-scoped topic reads, lifecycle and deletion use cases."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from backend.application.errors import Conflict, InvalidTransition, NotFound
from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import MessageReadModel, SummaryReadModel, TopicReadModel
from backend.domain.entities import ConversationTopic
from backend.domain.enums import TopicStatus
from backend.domain.exceptions import InvalidTopicTransition


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
    await uow.topics.set_status(guild_id, topic_id, lifecycle.status.value)
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

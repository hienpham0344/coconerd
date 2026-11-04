"""Maintain the transactional, same-database lexical topic index."""

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.topic_terms import weighted_topic_terms
from backend.infrastructure.database.models import TopicRecord, TopicSearchTermRecord


async def index_topic(
    session: AsyncSession, topic: TopicRecord, summary: dict[str, object]
) -> None:
    await session.execute(
        delete(TopicSearchTermRecord).where(TopicSearchTermRecord.topic_id == topic.id)
    )
    rows = [
        dict(topic_id=topic.id, guild_id=topic.guild_id, term=term, weight=weight)
        for term, weight in weighted_topic_terms(topic.title, topic.description, summary).items()
    ]
    if rows:
        await session.execute(insert(TopicSearchTermRecord), rows)

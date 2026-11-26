"""Maintain the transactional, same-database lexical topic index."""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.topic_terms import weighted_topic_terms
from backend.infrastructure.database.models import TopicRecord, TopicSearchTermRecord
from backend.infrastructure.database.statements import conflict_insert


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
        statement = conflict_insert(session, TopicSearchTermRecord).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=["topic_id", "term"],
            set_={
                "guild_id": statement.excluded.guild_id,
                "weight": statement.excluded.weight,
            },
        )
        await session.execute(statement)

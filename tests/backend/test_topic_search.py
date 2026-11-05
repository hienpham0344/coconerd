from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from backend.domain.entities import ConversationTopic
from backend.infrastructure.database.models import TopicSearchTermRecord
from backend.infrastructure.database.repositories.guilds import GuildRepository
from backend.infrastructure.database.repositories.summaries import SummaryRepository
from backend.infrastructure.database.repositories.topics import TopicRepository


def test_search_terms_skip_oversized_tokens_without_losing_short_terms():
    from backend.application.topic_terms import search_terms, weighted_topic_terms

    content = "DB " + "x" * 301
    assert "database" in search_terms(content)
    assert all(len(term) <= 300 for term in search_terms(content))
    assert all(len(term) <= 300 for term in weighted_topic_terms("Atlas", content, {}))


async def test_latest_summaries_are_batched_and_guild_scoped(database_factory):
    from sqlalchemy import event

    from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

    async with database_factory() as session:
        topics, summaries = TopicRepository(session), SummaryRepository(session)
        first = await topics.create(ConversationTopic.create("g", "Atlas"))
        second = await topics.create(ConversationTopic.create("g", "Boreal"))
        foreign = await topics.create(ConversationTopic.create("other", "Private"))
        for topic in (first, second, foreign):
            for version in (1, 2):
                await summaries.add(
                    topic.guild_id, topic.id, version, {"overview": str(version)}, []
                )
        await session.commit()
        reads = []

        def capture(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                reads.append(statement)

        engine = database_factory.kw["bind"].sync_engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            rows = await SqlAlchemyUnitOfWork(session).summaries.latest_many(
                "g", [first.id, second.id, foreign.id, "missing"]
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert set(rows) == {first.id, second.id}
        assert {row.version for row in rows.values()} == {2}
        assert len(reads) == 1


async def test_search_finds_old_topic_and_normalizes_accents_aliases(database_factory):
    async with database_factory() as session:
        topics = TopicRepository(session)
        old = ConversationTopic.create("g", "Thiết kế cơ sở dữ liệu")
        old.last_activity_at = datetime.now(UTC) - timedelta(days=60)
        await topics.create(old)
        for index in range(35):
            await topics.create(ConversationTopic.create("g", f"Recent unrelated {index}"))
        foreign = ConversationTopic.create("other", "database")
        await topics.create(foreign)
        closed = ConversationTopic.create("g", "database closed")
        await topics.create(closed)
        await topics.set_status("g", closed.id, "CLOSED")
        await session.commit()

        assert old.id not in {item.id for item in await topics.candidates("g")}
        assert [item.id for item in await topics.search("g", "DB")] == [old.id]
        assert [item.id for item in await topics.search("g", "co so du lieu")] == [old.id]


async def test_summary_index_tracks_latest_version(database_factory):
    async with database_factory() as session:
        topics = TopicRepository(session)
        topic = ConversationTopic.create("g", "Project")
        await topics.create(topic)
        summaries = SummaryRepository(session)
        await summaries.add("g", topic.id, 1, {"overview": "database"}, ["m1"])
        await session.commit()
        assert [item.id for item in await topics.search("g", "db")] == [topic.id]
        await summaries.add("g", topic.id, 2, {"overview": "payment"}, ["m2"])
        await session.commit()
        assert await topics.search("g", "db") == []
        assert [item.id for item in await topics.search("g", "payment")] == [topic.id]


@pytest.mark.parametrize("scope", ["topic", "guild"])
async def test_delete_removes_search_terms_without_touching_another_guild(database_factory, scope):
    async with database_factory() as session:
        topics = TopicRepository(session)
        target = ConversationTopic.create("g", "private database")
        foreign = ConversationTopic.create("other", "other database")
        await topics.create(target)
        await topics.create(foreign)
        await session.commit()
        if scope == "guild":
            await GuildRepository(session).delete_data("g")
        else:
            await topics.delete_data("g", target.id)
        await session.commit()
        remaining = list(await session.scalars(select(TopicSearchTermRecord)))
        assert remaining
        assert {item.topic_id for item in remaining} == {foreign.id}


async def test_final_topic_write_rejects_closure_after_read(database_factory):
    async with database_factory() as session:
        topics = TopicRepository(session)
        topic = await topics.create(ConversationTopic.create("g", "database"))
        await session.commit()
        previous_version = topic.version
        await topics.set_status("g", topic.id, "CLOSED")
        await session.commit()
        with pytest.raises(RuntimeError, match="concurrently"):
            await topics.touch("g", topic.id, previous_version, datetime.now(UTC))

import pytest

from backend.infrastructure.database.models import TopicRecord
from backend.infrastructure.database.repositories import TopicRepository as LegacyTopicRepository
from backend.infrastructure.database.repositories.topics import TopicRepository


class ScalarResult(list):
    pass


class SessionSpy:
    def __init__(self, values=()):
        self.values = values
        self.statement = None
        self.commits = 0
        self.rollbacks = 0

    async def scalars(self, statement):
        self.statement = statement
        return ScalarResult(self.values)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_topic_candidates_filter_open_statuses_and_order_by_activity():
    assert LegacyTopicRepository is TopicRepository
    session = SessionSpy([TopicRecord(id="topic", guild_id="g1", title="Topic")])
    candidates = await TopicRepository(session).candidates("g1", limit=7)

    sql = str(session.statement.compile(compile_kwargs={"literal_binds": True}))
    assert candidates == session.values
    assert "topics.guild_id = 'g1'" in sql
    assert "topics.status IN ('ACTIVE', 'DORMANT', 'RESUMED')" in sql
    assert "ORDER BY topics.last_activity_at DESC" in sql
    assert "LIMIT 7" in sql


@pytest.mark.asyncio
async def test_unit_of_work_delegates_commit_and_rollback_to_session():
    from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

    session = SessionSpy()
    unit_of_work = SqlAlchemyUnitOfWork(session)
    await unit_of_work.commit()
    await unit_of_work.rollback()

    assert session.commits == 1
    assert session.rollbacks == 1
    assert all(
        getattr(unit_of_work, name) is not None
        for name in (
            "messages",
            "topics",
            "actions",
            "guilds",
            "health",
            "model_config",
            "jobs",
            "summaries",
            "retention",
        )
    )

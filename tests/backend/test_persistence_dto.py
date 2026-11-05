from datetime import UTC, datetime, timedelta

import pytest

from backend.domain.entities import ConversationMessage
from backend.domain.enums import ActionStatus, ActionType, JobStatus
from backend.infrastructure.database.models import (
    DiscordActionRecord,
    MessageRecord,
    ProcessingJobRecord,
)
from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


class Result:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount


class ScalarRows(list):
    def all(self):
        return self


class SessionSpy:
    def get_bind(self):
        from types import SimpleNamespace

        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    def __init__(self, *, scalar_values=(), scalar_rows=(), get_result=None, rowcounts=()):
        self.scalar_values = iter(scalar_values)
        self.scalar_rows = iter(scalar_rows)
        self.get_result = get_result
        self.rowcounts = iter(rowcounts)

    async def execute(self, _statement):
        return Result(next(self.rowcounts, 1))

    async def scalar(self, _statement):
        return next(self.scalar_values, None)

    async def scalars(self, _statement):
        return ScalarRows(next(self.scalar_rows, ()))

    async def get(self, _model, _key):
        return self.get_result

    def add(self, _record):
        pass


@pytest.mark.asyncio
async def test_uow_message_ingest_and_list_return_plain_read_models():
    from backend.application.read_models import MessageReadModel

    message = ConversationMessage(
        guild_id="g1",
        channel_id="c1",
        message_id="m1",
        author_id="u1",
        author_name="User",
        content="hello",
        created_at=datetime.now(UTC),
    )
    row = MessageRecord(
        id="record-1",
        guild_id="g1",
        channel_id="c1",
        discord_message_id="m1",
        author_id="u1",
        author_name="User",
        content="hello",
        created_at=message.created_at,
    )
    session = SessionSpy(scalar_values=(row,), scalar_rows=((row,),), rowcounts=(1, 1))
    uow = SqlAlchemyUnitOfWork(session)

    ingested, inserted = await uow.messages.ingest(message, max_attempts=3)
    listed = await uow.messages.list_for_topic("g1", "t1", 10, None)

    assert inserted is True
    assert isinstance(ingested, MessageReadModel)
    assert isinstance(listed[0], MessageReadModel)
    assert listed[0].discord_message_id == "m1"
    assert (listed[0].channel_id, listed[0].author_id, listed[0].author_name) == (
        "c1",
        "u1",
        "User",
    )
    assert (ingested.id, ingested.guild_id, ingested.content) == ("record-1", "g1", "hello")


@pytest.mark.asyncio
async def test_uow_claims_return_plain_action_and_job_read_models():
    from backend.application.read_models import ClaimedAction, ClaimedJob

    action = DiscordActionRecord(
        id="a1",
        guild_id="g1",
        channel_id="c1",
        topic_id="t1",
        action_type=ActionType.CREATE_THREAD.value,
        status=ActionStatus.CLAIMED.value,
        payload={"title": "Topic"},
    )
    job = ProcessingJobRecord(
        id="j1",
        guild_id="g1",
        message_record_id="m1",
        status=JobStatus.CLAIMED.value,
    )
    action_session = SessionSpy(scalar_values=(None,), scalar_rows=(("a1",), (action,)))
    action_uow = SqlAlchemyUnitOfWork(action_session)
    now = datetime.now(UTC)
    actions = await action_uow.actions.claim_available(
        "worker", 1, now, now + timedelta(seconds=30)
    )

    job_session = SessionSpy(scalar_values=("j1",), get_result=job)
    job_uow = SqlAlchemyUnitOfWork(job_session)
    claimed_job = await job_uow.jobs.claim_one("worker", 30)

    assert isinstance(actions[0], ClaimedAction)
    assert (actions[0].id, actions[0].action_type, actions[0].status) == (
        "a1",
        "CREATE_THREAD",
        "CLAIMED",
    )
    assert actions[0].payload == {"title": "Topic"}
    assert isinstance(claimed_job, ClaimedJob)
    assert (claimed_job.id, claimed_job.guild_id, claimed_job.message_record_id) == (
        "j1",
        "g1",
        "m1",
    )

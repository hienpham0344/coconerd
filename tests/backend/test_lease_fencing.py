from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from backend.application.errors import Conflict
from backend.application.services.actions import complete_action, fail_action
from backend.application.services.jobs import complete_job, fail_job
from backend.infrastructure.database.models import (
    DiscordActionRecord,
    MessageRecord,
    ProcessingJobRecord,
    TopicRecord,
)
from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


async def seed(session, *, expired=False):
    session.add(TopicRecord(id="t", guild_id="g", title="Topic"))
    session.add(
        MessageRecord(
            id="m",
            guild_id="g",
            channel_id="c",
            discord_message_id="d",
            author_id="a",
            author_name="A",
            content="topic",
            created_at=datetime.now(UTC),
        )
    )
    await session.flush()
    expiry = datetime.now(UTC) + timedelta(seconds=-1 if expired else 120)
    session.add(
        ProcessingJobRecord(
            id="j",
            guild_id="g",
            message_record_id="m",
            status="CLAIMED",
            lease_owner="new",
            lease_expires_at=expiry,
            attempt_count=2,
            max_attempts=2,
        )
    )
    session.add(
        DiscordActionRecord(
            id="a",
            guild_id="g",
            channel_id="c",
            topic_id="t",
            action_type="CREATE_THREAD",
            payload={},
            status="CLAIMED",
            lease_owner="new",
            lease_expires_at=expiry,
            attempt_count=2,
            max_attempts=2,
        )
    )
    await session.commit()


@pytest.mark.parametrize("expired,owner", [(False, "old"), (True, "new")])
async def test_stale_job_cannot_complete_fail_or_wait(database_factory, expired, owner):
    async with database_factory() as session:
        await seed(session, expired=expired)
        uow = SqlAlchemyUnitOfWork(session)
        with pytest.raises(Conflict):
            await complete_job(uow, "j", owner=owner)
        await session.rollback()
        await fail_job(uow, "j", "OldFailure", owner=owner)
        assert not await uow.jobs.wait_for_context("j", datetime.now(UTC), owner=owner)
        job = await session.get(ProcessingJobRecord, "j")
        assert (job.status, job.lease_owner, job.error_type) == ("CLAIMED", "new", None)


async def test_claim_cleanup_preserves_active_final_attempt(database_factory):
    async with database_factory() as session:
        await seed(session)
        uow = SqlAlchemyUnitOfWork(session)
        now = datetime.now(UTC)
        assert await uow.jobs.claim_available("other", now, now + timedelta(minutes=1)) is None
        assert await uow.actions.claim_available("other", 10, now, now + timedelta(minutes=1)) == []
        await session.commit()
        assert (await session.get(ProcessingJobRecord, "j")).status == "CLAIMED"
        assert (await session.get(DiscordActionRecord, "a")).status == "CLAIMED"


async def test_expired_exhausted_work_and_failed_dependency_are_terminal(database_factory):
    async with database_factory() as session:
        await seed(session, expired=True)
        session.add(
            DiscordActionRecord(
                id="child",
                guild_id="g",
                channel_id="c",
                topic_id="t",
                action_type="UPSERT_SUMMARY",
                payload={},
                dependency_id="a",
            )
        )
        await session.commit()
        uow = SqlAlchemyUnitOfWork(session)
        now = datetime.now(UTC)
        assert await uow.jobs.claim_available("other", now, now + timedelta(minutes=1)) is None
        assert await uow.actions.claim_available("other", 10, now, now + timedelta(minutes=1)) == []
        await session.commit()
        rows = list(
            await session.scalars(select(DiscordActionRecord).order_by(DiscordActionRecord.id))
        )
        assert [(r.status, r.error_type) for r in rows] == [
            ("DEAD", "LeaseAttemptsExhausted"),
            ("DEAD", "DependencyFailed"),
        ]
        job = await session.get(ProcessingJobRecord, "j")
        assert (job.status, job.lease_owner) == ("DEAD", None)


@pytest.mark.parametrize("operation", ["ack", "fail"])
async def test_expired_action_cannot_ack_or_fail_or_bind_thread(database_factory, operation):
    async with database_factory() as session:
        await seed(session, expired=True)
        uow = SqlAlchemyUnitOfWork(session)
        with pytest.raises(Conflict):
            if operation == "ack":
                await complete_action(uow, "a", "new", "thread", None)
            else:
                await fail_action(uow, "a", "new", "Error", "failed", False)
        await session.rollback()
        assert (await session.get(TopicRecord, "t")).discord_thread_id is None
        assert (await session.get(DiscordActionRecord, "a")).status == "CLAIMED"


async def test_action_stolen_after_read_cannot_ack(database_factory):
    from sqlalchemy import update

    async with database_factory() as session:
        await seed(session)
        uow = SqlAlchemyUnitOfWork(session)
        original_get = uow.actions.get

        async def read_then_steal(action_id):
            state = await original_get(action_id)
            await session.execute(
                update(DiscordActionRecord)
                .where(DiscordActionRecord.id == action_id)
                .values(lease_owner="next-worker")
            )
            await session.commit()
            return state

        uow.actions.get = read_then_steal
        with pytest.raises(Conflict):
            await complete_action(uow, "a", "new", "wrong-thread", None)
        await session.rollback()
        assert (await session.get(TopicRecord, "t")).discord_thread_id is None
        action = await session.get(DiscordActionRecord, "a")
        assert (action.status, action.lease_owner) == ("CLAIMED", "next-worker")


async def test_lost_job_lease_rolls_back_real_classification_projection(database_factory):
    from sqlalchemy import func

    from backend.application.services.messages import process_message_record
    from backend.infrastructure.database.models import (
        AIDecisionRecord,
        MessageTopicAssociationRecord,
        TopicSummaryRecord,
    )
    from backend.infrastructure.meta_provider import MockMetaProvider

    async with database_factory() as session:
        await seed(session, expired=True)
        uow = SqlAlchemyUnitOfWork(session)
        await process_message_record(uow, "m", MockMetaProvider())
        with pytest.raises(Conflict):
            await complete_job(uow, "j", owner="new")
        await session.rollback()
        for model in (AIDecisionRecord, MessageTopicAssociationRecord, TopicSummaryRecord):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        assert await session.scalar(select(func.count()).select_from(TopicRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(DiscordActionRecord)) == 1


async def test_reclaim_by_same_bot_owner_rejects_old_lease_token(api_client, database_factory):
    async with database_factory() as session:
        await seed(session)
        action = await session.get(DiscordActionRecord, "a")
        action.status, action.attempt_count, action.max_attempts = "PENDING", 0, 3
        await session.commit()
    headers = {"X-API-Key": "bot-test-key"}
    url = "/api/v1/actions"
    first = (
        await api_client.post(f"{url}/claim", headers=headers, json={"worker_id": "bot"})
    ).json()[0]
    async with database_factory() as session:
        action = await session.get(DiscordActionRecord, "a")
        action.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    second = (
        await api_client.post(f"{url}/claim", headers=headers, json={"worker_id": "bot"})
    ).json()[0]
    payload = {
        "worker_id": "bot",
        "discord_thread_id": "late-thread",
        "lease_token": first.get("lease_token", "old-lease"),
    }
    late = await api_client.post(f"{url}/a/complete", headers=headers, json=payload)
    assert late.status_code == 409, late.text
    assert first["lease_token"] != second["lease_token"]
    missing = await api_client.post(
        f"{url}/a/complete",
        headers=headers,
        json={"worker_id": "bot", "discord_thread_id": "correct-thread"},
    )
    assert missing.status_code == 409
    payload.update(lease_token=second["lease_token"], discord_thread_id="correct-thread")
    assert (
        await api_client.post(f"{url}/a/complete", headers=headers, json=payload)
    ).status_code == 200

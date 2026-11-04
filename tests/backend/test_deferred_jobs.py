from datetime import UTC, datetime, timedelta

import pytest

from backend.domain.entities import ConversationMessage
from backend.infrastructure.database.repositories.jobs import JobRepository
from backend.infrastructure.database.repositories.messages import MessageRepository


def msg(id, content="ok", *, guild="g", channel="c", author="a", reply=None, at=None):
    return ConversationMessage(
        guild_id=guild,
        channel_id=channel,
        message_id=id,
        author_id=author,
        author_name=author,
        content=content,
        created_at=at or datetime.now(UTC),
        reply_to_message_id=reply,
    )


async def store(session, message):
    record, _ = await MessageRepository(session).ingest(message, 5)
    await session.commit()
    return record


async def test_budget_survives_retry_and_allows_only_two_calls(database_factory):
    async with database_factory() as session:
        await store(session, msg("root"))
        jobs = JobRepository(session)
        job = await jobs.claim_one("w", 60)
        assert await jobs.reserve_model_call(job.id, "w")
        await session.commit()
        assert not await jobs.reserve_model_call(job.id, "other-owner")
        assert await jobs.reserve_model_call(job.id, "w")
        await session.commit()
        assert not await jobs.reserve_model_call(job.id, "w")
        await session.refresh(job)
        assert job.model_call_count == 2


@pytest.mark.parametrize("early", [False, True])
async def test_clarification_wakes_once_even_when_already_ingested(database_factory, early):
    async with database_factory() as session:
        now = datetime.now(UTC)
        root = await store(session, msg("root", at=now - timedelta(seconds=5)))
        jobs = JobRepository(session)
        job = await jobs.claim_one("w", 60)
        if early:
            followup = await store(session, msg("clarify", "ý mình là lịch beta", at=now))
        await jobs.wait_for_context(job.id, now + timedelta(minutes=10))
        if not early:
            followup = await store(session, msg("clarify", "ý mình là lịch beta", at=now))
            await jobs.wake_deferred(followup.id)
        await session.commit()
        await session.refresh(job)
        assert (job.status, job.reassessment_count, job.followup_message_id) == (
            "PENDING",
            1,
            followup.id,
        )
        await jobs.wake_deferred(followup.id)
        await session.commit()
        await session.refresh(job)
        assert job.reassessment_count == 1
        assert job.message_record_id == root.id


@pytest.mark.parametrize(
    "override",
    [
        dict(guild="other"),
        dict(channel="other"),
        dict(author="other"),
        dict(content="random nearby chat"),
    ],
)
async def test_unrelated_message_cannot_wake_deferred(database_factory, override):
    async with database_factory() as session:
        now = datetime.now(UTC)
        await store(session, msg("root", at=now - timedelta(seconds=5)))
        jobs = JobRepository(session)
        job = await jobs.claim_one("w", 60)
        await jobs.wait_for_context(job.id, now + timedelta(minutes=10))
        fields = {"content": "ý mình là lịch beta", **override}
        followup = await store(session, msg("followup", at=now, **fields))
        await jobs.wake_deferred(followup.id)
        await session.commit()
        await session.refresh(job)
        assert job.status == "WAITING"


async def test_expiry_does_not_queue_a_model_call(database_factory):
    async with database_factory() as session:
        await store(session, msg("root"))
        jobs = JobRepository(session)
        job = await jobs.claim_one("w", 60)
        await jobs.wait_for_context(job.id, datetime.now(UTC) - timedelta(seconds=1))
        await session.commit()
        assert await jobs.claim_one("w", 60) is None
        await session.refresh(job)
        assert job.status == "SUCCEEDED" and job.model_call_count == 0


@pytest.mark.parametrize("early", [False, True])
async def test_clarification_reply_to_another_message_never_wakes_target(database_factory, early):
    async with database_factory() as session:
        now = datetime.now(UTC)
        await store(session, msg("root", at=now - timedelta(seconds=5)))
        jobs = JobRepository(session)
        job = await jobs.claim_one("w", 60)
        followup_message = msg("clarify", "ý mình là lịch beta", reply="another", at=now)
        if early:
            await store(session, followup_message)
        await jobs.wait_for_context(job.id, now + timedelta(minutes=10))
        if not early:
            followup = await store(session, followup_message)
            await jobs.wake_deferred(followup.id)
        await session.commit()
        await session.refresh(job)
        assert job.status == "WAITING"
        assert job.reassessment_count == 0


@pytest.mark.parametrize("early", [False, True])
async def test_implicit_clarification_does_not_skip_newer_message_from_same_author(
    database_factory, early
):
    async with database_factory() as session:
        now = datetime.now(UTC)
        await store(session, msg("older", at=now - timedelta(seconds=10)))
        jobs = JobRepository(session)
        job = await jobs.claim_one("w", 60)
        await store(session, msg("newer", "another subject", at=now - timedelta(seconds=5)))
        if early:
            await store(session, msg("clarify", "ý mình là lịch beta", at=now))
        await jobs.wait_for_context(job.id, now + timedelta(minutes=10))
        if not early:
            followup = await store(session, msg("clarify", "ý mình là lịch beta", at=now))
            await jobs.wake_deferred(followup.id)
        await session.commit()
        await session.refresh(job)
        assert job.status == "WAITING"


async def test_concurrent_reservations_never_exceed_two(database_factory):
    import asyncio

    async with database_factory() as session:
        await store(session, msg("root"))
        job = await JobRepository(session).claim_one("w", 60)
        await session.commit()
        job_id = job.id

    async def reserve():
        async with database_factory() as session:
            result = await JobRepository(session).reserve_model_call(job_id, "w")
            await session.commit()
            return result

    assert sum(await asyncio.gather(reserve(), reserve(), reserve())) == 2

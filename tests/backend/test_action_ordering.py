import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from backend.application.services.actions import claim_actions, complete_action, fail_action
from backend.infrastructure.database.models import DiscordActionRecord, TopicRecord
from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


async def seed_actions(factory, *, delayed=False, tied=False):
    now = datetime.now(UTC)
    async with factory() as session:
        session.add_all([TopicRecord(id=t, guild_id="g", title=t) for t in ("t", "other")])
        await session.flush()
        for action_id, topic_id, version, seconds in [
            ("a-first", "t", 1, -3),
            ("b-second", "t", 2, -3 if tied else -2),
            ("c-other", "other", 1, -1),
        ]:
            session.add(
                DiscordActionRecord(
                    id=action_id,
                    guild_id="g",
                    channel_id="c",
                    topic_id=topic_id,
                    action_type="UPSERT_SUMMARY",
                    payload={"version": version},
                    created_at=now + timedelta(seconds=seconds),
                    available_at=now
                    + timedelta(seconds=60 if delayed and version == 1 and topic_id == "t" else -1),
                )
            )
        await session.commit()


async def claim(factory, owner):
    async with factory() as session:
        return await claim_actions(SqlAlchemyUnitOfWork(session), owner, 20, 60)


@pytest.mark.parametrize("tied", [False, True])
async def test_only_one_action_per_topic_is_in_flight(database_factory, tied):
    await seed_actions(database_factory, tied=tied)
    first = await claim(database_factory, "bot-a")
    assert {a.id for a in first} == {"a-first", "c-other"}
    assert await claim(database_factory, "bot-b") == []
    action = next(a for a in first if a.id == "a-first")
    async with database_factory() as session:
        await complete_action(
            SqlAlchemyUnitOfWork(session),
            action.id,
            "bot-a",
            None,
            "summary-1",
            lease_token=action.lease_token,
        )
    assert [a.id for a in await claim(database_factory, "bot-b")] == ["b-second"]


async def test_retry_backoff_blocks_newer_summary_but_not_other_topics(database_factory):
    await seed_actions(database_factory, delayed=True)
    assert [a.id for a in await claim(database_factory, "bot")] == ["c-other"]


async def test_dead_action_does_not_block_newer_independent_actions(database_factory):
    await seed_actions(database_factory)
    first = next(a for a in await claim(database_factory, "bot") if a.id == "a-first")
    async with database_factory() as session:
        await fail_action(
            SqlAlchemyUnitOfWork(session),
            first.id,
            "bot",
            "Forbidden",
            "synthetic failure",
            False,
            lease_token=first.lease_token,
        )
    assert [a.id for a in await claim(database_factory, "bot")] == ["b-second"]


async def test_concurrent_bot_claims_cannot_take_two_versions_of_one_topic(database_factory):
    await seed_actions(database_factory)
    batches = await asyncio.gather(
        claim(database_factory, "bot-a"), claim(database_factory, "bot-b")
    )
    claimed = [item for batch in batches for item in batch]
    assert sorted(item.id for item in claimed) == ["a-first", "c-other"]

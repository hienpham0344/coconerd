from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from backend.infrastructure.database.models import (
    DiscordActionRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    ProcessingJobRecord,
    TopicRecord,
    TopicSummaryRecord,
)

ADMIN = {"X-Admin-API-Key": "admin-test-key"}
BASE = "/api/v1/guilds/g"


async def seed(factory):
    async with factory() as session:
        session.add_all(
            [
                TopicRecord(id="old", guild_id="g", title="Atlas", discord_thread_id="thread-old"),
                TopicRecord(id="new", guild_id="g", title="Beta"),
                TopicRecord(id="foreign", guild_id="other", title="Secret"),
                MessageRecord(
                    id="m",
                    guild_id="g",
                    channel_id="c",
                    discord_message_id="discord-m",
                    author_id="u",
                    author_name="User",
                    content="Beta phát hành thứ Sáu",
                    created_at=datetime.now(UTC),
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                MessageTopicAssociationRecord(
                    id="assoc",
                    guild_id="g",
                    message_record_id="m",
                    topic_id="old",
                    kind="CLASSIFIED",
                    confidence=0.8,
                ),
                ProcessingJobRecord(
                    id="j",
                    guild_id="g",
                    message_record_id="m",
                    status="SUCCEEDED",
                    model_call_count=1,
                ),
                TopicSummaryRecord(
                    id="s",
                    guild_id="g",
                    topic_id="old",
                    version=1,
                    data={"overview": "Beta phát hành thứ Sáu"},
                    source_message_ids=["discord-m"],
                ),
                DiscordActionRecord(
                    id="sent",
                    guild_id="g",
                    channel_id="c",
                    topic_id="old",
                    action_type="APPEND_MESSAGE",
                    status="SUCCEEDED",
                    payload={"source_message_id": "discord-m"},
                    discord_message_id="external-copy",
                    attempt_count=1,
                ),
                DiscordActionRecord(
                    id="pending",
                    guild_id="g",
                    channel_id="c",
                    topic_id="old",
                    action_type="UPSERT_SUMMARY",
                    payload={"version": 1},
                ),
            ]
        )
        await session.commit()


def correction(**changes):
    return (
        dict(
            request_id="fix-1",
            actor="moderator",
            reason="Wrong project",
            expected_revision=1,
            target_topic_id="new",
            summaries=[
                {
                    "topic_id": "old",
                    "expected_version": 1,
                    "overview": "",
                    "source_message_ids": [],
                },
                {
                    "topic_id": "new",
                    "expected_version": 1,
                    "overview": "Beta phát hành thứ Sáu",
                    "source_message_ids": ["discord-m"],
                },
            ],
        )
        | changes
    )


async def test_correction_rebuilds_memory_preserves_history_and_pauses_outbox(
    api_client, database_factory
):
    await seed(database_factory)
    url = f"{BASE}/messages/discord-m"
    status = await api_client.get(f"{url}/review", headers=ADMIN)
    assert status.status_code == 200
    assert status.json()["revision"] == 1
    response = await api_client.post(f"{url}/corrections", headers=ADMIN, json=correction())
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 2
    assert response.json()["sync_paused_topic_ids"] == ["new", "old"]
    repeated = await api_client.post(f"{url}/corrections", headers=ADMIN, json=correction())
    assert repeated.json() == response.json()
    async with database_factory() as session:
        assoc = await session.get(MessageTopicAssociationRecord, "assoc")
        assert (assoc.topic_id, assoc.kind, assoc.revision) == ("new", "MANUAL", 2)
        assert (await session.get(MessageRecord, "m")).content == "Beta phát hành thứ Sáu"
        assert (await session.get(ProcessingJobRecord, "j")).model_call_count == 1
        summaries = list(await session.scalars(select(TopicSummaryRecord)))
        assert len(summaries) == 3
        assert next(s for s in summaries if s.id == "s").source_message_ids == ["discord-m"]
        assert (
            next(s for s in summaries if s.topic_id == "old" and s.version == 2).source_message_ids
            == []
        )
        assert (
            next(s for s in summaries if s.topic_id == "new").data["overview"]
            == "Beta phát hành thứ Sáu"
        )
        assert (await session.get(DiscordActionRecord, "pending")).status == "CANCELLED"
        assert (
            await session.get(DiscordActionRecord, "sent")
        ).discord_message_id == "external-copy"
        assert (await session.get(TopicRecord, "old")).sync_paused
    claim = await api_client.post(
        "/api/v1/actions/claim",
        headers={"X-API-Key": "bot-test-key"},
        json={"worker_id": "bot", "limit": 20},
    )
    assert claim.status_code == 200
    assert claim.json() == []


@pytest.mark.parametrize(
    "case,expected", [("stale", 409), ("foreign", 404), ("source", 422), ("missing_summary", 422)]
)
async def test_rejected_correction_has_no_partial_writes(
    api_client, database_factory, case, expected
):
    await seed(database_factory)
    body = correction()
    if case == "stale":
        body["expected_revision"] = 0
    elif case == "foreign":
        body["target_topic_id"] = "foreign"
    elif case == "source":
        body["summaries"][0]["source_message_ids"] = ["discord-m"]
    else:
        body["summaries"] = []
    response = await api_client.post(
        f"{BASE}/messages/discord-m/corrections", headers=ADMIN, json=body
    )
    assert response.status_code == expected, response.text
    async with database_factory() as session:
        assert (await session.get(MessageTopicAssociationRecord, "assoc")).topic_id == "old"
        assert len(list(await session.scalars(select(TopicSummaryRecord)))) == 1
        assert (await session.get(DiscordActionRecord, "pending")).status == "PENDING"


async def test_review_auth_guild_scope_and_idempotency_conflict(api_client, database_factory):
    await seed(database_factory)
    assert (await api_client.get(f"{BASE}/messages/discord-m/review")).status_code == 401
    assert (
        await api_client.get("/api/v1/guilds/other/messages/discord-m/review", headers=ADMIN)
    ).status_code == 404
    url = f"{BASE}/messages/discord-m/corrections"
    assert (await api_client.post(url, headers=ADMIN, json=correction())).status_code == 200
    assert (
        await api_client.post(url, headers=ADMIN, json=correction(reason="changed"))
    ).status_code == 409
    assert (
        await api_client.post(url, headers=ADMIN, json=correction(request_id="fix-2"))
    ).status_code == 409


async def test_sync_resume_requires_current_version_and_never_replays_actions(
    api_client, database_factory
):
    await seed(database_factory)
    assert (
        await api_client.post(
            f"{BASE}/messages/discord-m/corrections", headers=ADMIN, json=correction()
        )
    ).status_code == 200
    review = await api_client.get(f"{BASE}/topics/new/sync", headers=ADMIN)
    assert review.status_code == 200, review.text
    assert review.json()["sync_paused"]
    body = dict(
        request_id="resume",
        actor="mod",
        reason="Manually reconciled",
        expected_version=1,
        discord_reconciled=True,
        discord_thread_id="thread-new",
    )
    url = f"{BASE}/topics/new/resume-sync"
    assert (await api_client.post(url, headers=ADMIN, json=body)).status_code == 409
    body["expected_version"] = review.json()["version"]
    response = await api_client.post(url, headers=ADMIN, json=body)
    assert response.status_code == 200, response.text
    assert (await api_client.post(url, headers=ADMIN, json=body)).json() == response.json()
    async with database_factory() as session:
        topic = await session.get(TopicRecord, "new")
        assert not topic.sync_paused and topic.discord_thread_id == "thread-new"
        assert len(list(await session.scalars(select(DiscordActionRecord)))) == 2


@pytest.mark.parametrize("resolution", ["not_performed", "performed"])
async def test_failed_thread_recovery_is_audited_and_unblocks_dependencies(
    api_client, database_factory, resolution
):
    await seed(database_factory)
    async with database_factory() as session:
        session.add(
            DiscordActionRecord(
                id="create",
                guild_id="g",
                channel_id="c",
                topic_id="new",
                action_type="CREATE_THREAD",
                status="DEAD",
                payload={},
                attempt_count=5,
                max_attempts=5,
            )
        )
        await session.flush()
        session.add(
            DiscordActionRecord(
                id="child",
                guild_id="g",
                channel_id="c",
                topic_id="new",
                action_type="UPSERT_SUMMARY",
                status="DEAD",
                payload={},
                dependency_id="create",
                error_type="DependencyFailed",
            )
        )
        await session.commit()
    body = dict(
        request_id="recover",
        actor="mod",
        reason="Checked Discord",
        expected_attempt_count=5,
        resolution=resolution,
        discord_thread_id="thread-new" if resolution == "performed" else None,
    )
    url = f"{BASE}/actions/create/recover"
    response = await api_client.post(url, headers=ADMIN, json=body)
    assert response.status_code == 200, response.text
    assert (await api_client.post(url, headers=ADMIN, json=body)).json() == response.json()
    async with database_factory() as session:
        action = await session.get(DiscordActionRecord, "create")
        assert action.status == ("PENDING" if resolution == "not_performed" else "SUCCEEDED")
        assert action.attempt_count == 5
        assert (await session.get(DiscordActionRecord, "child")).status == "PENDING"
        if resolution == "performed":
            assert (await session.get(TopicRecord, "new")).discord_thread_id == "thread-new"
        else:
            assert action.max_attempts == 6


@pytest.mark.parametrize("active", ["job", "action"])
async def test_live_processing_or_discord_lease_blocks_correction(
    api_client, database_factory, active
):
    from datetime import timedelta

    await seed(database_factory)
    async with database_factory() as session:
        row = await session.get(
            ProcessingJobRecord if active == "job" else DiscordActionRecord,
            "j" if active == "job" else "pending",
        )
        row.status = "CLAIMED"
        row.lease_owner = "busy"
        row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        await session.commit()
    response = await api_client.post(
        f"{BASE}/messages/discord-m/corrections", headers=ADMIN, json=correction()
    )
    assert response.status_code == 409, response.text
    async with database_factory() as session:
        assert (await session.get(MessageTopicAssociationRecord, "assoc")).topic_id == "old"
        assert not (await session.get(TopicRecord, "new")).sync_paused


async def test_correction_supersedes_failed_actions_even_after_resume(api_client, database_factory):
    await seed(database_factory)
    async with database_factory() as session:
        row = await session.get(DiscordActionRecord, "pending")
        row.status, row.attempt_count, row.error_type = "DEAD", 1, "Timeout"
        await session.commit()
    assert (
        await api_client.post(
            f"{BASE}/messages/discord-m/corrections", headers=ADMIN, json=correction()
        )
    ).status_code == 200
    resumed = await api_client.post(
        f"{BASE}/topics/old/resume-sync",
        headers=ADMIN,
        json={
            "request_id": "resume-old",
            "actor": "mod",
            "reason": "Reconciled",
            "expected_version": 2,
            "discord_reconciled": True,
            "discord_thread_id": "thread-old",
        },
    )
    assert resumed.status_code == 200, resumed.text
    response = await api_client.post(
        f"{BASE}/actions/pending/recover",
        headers=ADMIN,
        json={
            "request_id": "bad-replay",
            "actor": "mod",
            "reason": "Retry",
            "expected_attempt_count": 1,
            "resolution": "not_performed",
        },
    )
    assert response.status_code == 409
    async with database_factory() as session:
        row = await session.get(DiscordActionRecord, "pending")
        assert row.status == "DEAD" and row.superseded and row.error_type == "Timeout"


async def test_guild_deletion_removes_review_audit_and_preserves_foreign_guild(
    api_client, database_factory
):
    from sqlalchemy import text

    from backend.application.services.guilds import delete_guild_data
    from backend.infrastructure.database.models import ReviewEventRecord
    from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

    await seed(database_factory)
    response = await api_client.post(
        f"{BASE}/messages/discord-m/corrections", headers=ADMIN, json=correction()
    )
    assert response.status_code == 200
    async with database_factory() as session:
        if session.get_bind().dialect.name == "sqlite":
            await session.execute(text("PRAGMA foreign_keys=ON"))
        assert len(list(await session.scalars(select(ReviewEventRecord)))) == 1
        await delete_guild_data(SqlAlchemyUnitOfWork(session), "g")
        assert list(await session.scalars(select(ReviewEventRecord))) == []
        assert (await session.get(TopicRecord, "foreign")).guild_id == "other"

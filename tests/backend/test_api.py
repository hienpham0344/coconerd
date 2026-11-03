from datetime import UTC, datetime

from sqlalchemy import func, select

from backend.infrastructure.database.models import (
    DiscordActionRecord,
    GuildSettingsRecord,
    MessageRecord,
    ProcessingJobRecord,
    TopicRecord,
)


def message_payload(message_id: str = "message-1") -> dict[str, object]:
    return {
        "guild_id": "guild-1",
        "channel_id": "channel-1",
        "message_id": message_id,
        "author_id": "user-1",
        "author_name": "Hien",
        "content": "We should discuss the launch plan.",
        "created_at": datetime.now(UTC).isoformat(),
    }


async def enable_channel(database_factory) -> None:
    async with database_factory() as session:
        session.add(
            GuildSettingsRecord(
                guild_id="guild-1",
                enabled=True,
                allowed_channel_ids=["channel-1"],
                retention_days=365,
            )
        )
        await session.commit()


async def test_message_ingest_requires_bot_key(unauthenticated_api_client):
    response = await unauthenticated_api_client.post("/api/v1/messages", json=message_payload())

    assert response.status_code == 401


async def test_ingest_persists_once_and_queues_durable_job(api_client, database_factory):
    await enable_channel(database_factory)
    headers = {"X-API-Key": "bot-test-key"}

    first = await api_client.post("/api/v1/messages", json=message_payload(), headers=headers)
    duplicate = await api_client.post("/api/v1/messages", json=message_payload(), headers=headers)

    assert first.status_code == 202
    assert first.json() == {"message_id": "message-1", "status": "accepted"}
    assert duplicate.status_code == 202
    async with database_factory() as session:
        assert await session.scalar(select(func.count()).select_from(MessageRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(ProcessingJobRecord)) == 1


async def test_ingest_rejects_channel_outside_admin_allowlist(api_client, database_factory):
    await enable_channel(database_factory)
    payload = message_payload()
    payload["channel_id"] = "other-channel"

    response = await api_client.post(
        "/api/v1/messages", json=payload, headers={"X-API-Key": "bot-test-key"}
    )

    assert response.status_code == 403


async def test_claim_respects_thread_dependency_and_ack_is_idempotent(api_client, database_factory):
    async with database_factory() as session:
        session.add(TopicRecord(id="topic-1", guild_id="guild-1", title="Release", status="ACTIVE"))
        session.add_all(
            [
                DiscordActionRecord(
                    id="create-1",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    topic_id="topic-1",
                    action_type="CREATE_THREAD",
                    status="PENDING",
                    payload={"title": "Release"},
                ),
                DiscordActionRecord(
                    id="append-1",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    topic_id="topic-1",
                    action_type="APPEND_MESSAGE",
                    status="PENDING",
                    payload={"source_message_id": "message-2"},
                    dependency_id="create-1",
                ),
            ]
        )
        await session.commit()
    headers = {"X-API-Key": "bot-test-key"}

    claimed = await api_client.post(
        "/api/v1/actions/claim", json={"worker_id": "bot-worker"}, headers=headers
    )
    assert [item["action_id"] for item in claimed.json()] == ["create-1"]

    completion = {
        "worker_id": "bot-worker",
        "discord_thread_id": "thread-1",
    }
    completed = await api_client.post(
        "/api/v1/actions/create-1/complete", json=completion, headers=headers
    )
    repeated = await api_client.post(
        "/api/v1/actions/create-1/complete", json=completion, headers=headers
    )
    assert completed.status_code == 200
    assert repeated.status_code == 200

    next_claim = await api_client.post(
        "/api/v1/actions/claim", json={"worker_id": "bot-worker"}, headers=headers
    )
    assert [item["action_id"] for item in next_claim.json()] == ["append-1"]


async def test_topic_reads_are_guild_isolated(api_client, database_factory):
    async with database_factory() as session:
        session.add(TopicRecord(id="topic-1", guild_id="guild-1", title="Private", status="ACTIVE"))
        await session.commit()

    response = await api_client.get(
        "/api/v1/topics/topic-1?guild_id=guild-2", headers={"X-API-Key": "bot-test-key"}
    )

    assert response.status_code == 404

from datetime import UTC, datetime

from sqlalchemy import func, select

from backend.application.services import actions, guilds, model_config
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
        "lease_token": claimed.json()[0]["lease_token"],
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


# Route translation is checked without connecting to SQLite. Persistence integration
# remains covered by the existing API tests using database_factory.
async def test_api_service_error_mapping(monkeypatch):
    from unittest.mock import AsyncMock

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.application.errors import Conflict, InvalidTransition, NotFound
    from backend.config import Settings
    from backend.presentation.api import app as api

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def no_rate_limit():
        pass

    monkeypatch.setattr(api, "rate_limit_dependency", lambda *args: no_rate_limit)
    application = api.create_app(
        Settings(_env_file=None, bot_api_key="bot-key", admin_api_key="admin-key"), factory
    )
    operation = AsyncMock()
    monkeypatch.setattr(actions, "complete_action", operation)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        for error, code in [
            (NotFound("Action not found"), 404),
            (Conflict("Action is not leased by this worker"), 409),
            (InvalidTransition("CREATE_THREAD completion requires discord_thread_id"), 422),
        ]:
            operation.side_effect = error
            response = await client.post(
                "/api/v1/actions/a/complete",
                json={"worker_id": "w"},
                headers={"X-API-Key": "bot-key"},
            )
            assert response.status_code == code, response.text
            assert response.json() == {"detail": str(error)}
        operation.reset_mock()
        denied = await client.post("/api/v1/actions/a/complete", json={"worker_id": "w"})
        assert denied.status_code == 401
        operation.assert_not_awaited()
    await engine.dispose()


async def test_api_service_dto_contracts(monkeypatch):
    from unittest.mock import AsyncMock

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.application.read_models import ActionResult, GuildSettings, ModelConfiguration
    from backend.config import Settings
    from backend.presentation.api import app as api

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def no_rate_limit():
        pass

    monkeypatch.setattr(api, "rate_limit_dependency", lambda *args: no_rate_limit)
    application = api.create_app(
        Settings(_env_file=None, bot_api_key="bot-key", admin_api_key="admin-key"), factory
    )
    setting = GuildSettings("g", True, ["c"], 30)
    configuration = ModelConfiguration("guild", "g", "meta", "model", 0.2, 100)
    save = AsyncMock(return_value=setting)
    config = AsyncMock(return_value=configuration)
    complete = AsyncMock(return_value=ActionResult("a", "SUCCEEDED"))
    monkeypatch.setattr(guilds, "set_guild_settings", save)
    monkeypatch.setattr(model_config, "get_model_config", config)
    monkeypatch.setattr(actions, "complete_action", complete)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/v1/admin/guilds/g/settings",
            json={"enabled": True, "allowed_channel_ids": ["c"], "retention_days": 30},
            headers={"X-Admin-API-Key": "admin-key"},
        )
        assert response.status_code == 200
        assert response.json() == {
            "guild_id": "g",
            "enabled": True,
            "allowed_channel_ids": ["c"],
            "retention_days": 30,
            "output_channel_id": None,
        }
        response = await client.get(
            "/api/v1/admin/model-config?guild_id=g", headers={"X-Admin-API-Key": "admin-key"}
        )
        assert response.status_code == 200
        assert response.json() == {
            "scope": "guild",
            "guild_id": "g",
            "provider": "meta",
            "model_id": "model",
            "temperature": 0.2,
            "max_tokens": 100,
            "enabled": True,
        }
        response = await client.post(
            "/api/v1/actions/a/complete",
            json={"worker_id": "w", "discord_thread_id": "thread"},
            headers={"X-API-Key": "bot-key"},
        )
        assert response.status_code == 200
        assert response.json() == {"action_id": "a", "status": "SUCCEEDED"}
        assert complete.call_args.args[1:] == ("a", "w", "thread", None)
    await engine.dispose()

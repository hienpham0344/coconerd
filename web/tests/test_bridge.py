from datetime import UTC, datetime

import pytest
from bridge.app import create_bridge
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config import Settings
from backend.infrastructure.database.models import Base, GuildSettingsRecord, TopicRecord


@pytest.mark.asyncio
async def test_dashboard_reads_are_authenticated_scoped_and_paginated(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'web.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                GuildSettingsRecord(
                    guild_id="one", enabled=True, allowed_channel_ids=["c1"], retention_days=30
                ),
                GuildSettingsRecord(
                    guild_id="two", enabled=False, allowed_channel_ids=[], retention_days=90
                ),
                TopicRecord(
                    id="t1",
                    guild_id="one",
                    title="Garden release",
                    description="Planning",
                    status="ACTIVE",
                    last_activity_at=datetime.now(UTC),
                ),
                TopicRecord(
                    id="t2",
                    guild_id="two",
                    title="Private topic",
                    description="Hidden",
                    status="CLOSED",
                    last_activity_at=datetime.now(UTC),
                ),
            ]
        )
        await session.commit()
    settings = Settings(_env_file=None, bot_api_key="test-bot", admin_api_key="test-admin")
    app = create_bridge(settings, factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        path = "/api/v1/admin/web/guilds"
        assert (await client.get(path)).status_code == 401
        headers = {"X-Admin-API-Key": "test-admin"}
        assert len((await client.get(path, headers=headers)).json()["items"]) == 2
        topics = await client.get("/api/v1/admin/web/guilds/one/topics", headers=headers)
        assert topics.status_code == 200
        assert topics.json()["total"] == 1
        assert topics.json()["items"][0]["topic_id"] == "t1"
        assert (
            await client.get("/api/v1/admin/web/guilds/one/topics?q=Private", headers=headers)
        ).json()["total"] == 0
        assert (
            await client.get("/api/v1/admin/web/guilds/one/topics?offset=1", headers=headers)
        ).json()["items"] == []
        assert (
            await client.get("/api/v1/admin/web/guilds/one/topics?status=CLOSED", headers=headers)
        ).json()["total"] == 0
        assert (
            await client.get("/api/v1/admin/web/guilds/one/topics?status=invalid", headers=headers)
        ).status_code == 422
        assert (
            await client.get("/api/v1/admin/web/guilds/missing/overview", headers=headers)
        ).status_code == 404
        overview = (
            await client.get("/api/v1/admin/web/guilds/one/overview", headers=headers)
        ).json()
        assert overview == {"topics": 1, "active_topics": 1, "messages": 0, "channels": 1}
        wrong_guild = await client.get(
            "/api/v1/topics/t2?guild_id=one", headers={"X-API-Key": "test-bot"}
        )
        assert wrong_guild.status_code == 404
    await engine.dispose()


@pytest.mark.asyncio
async def test_real_backend_workflow_and_web_edits_use_isolated_database(tmp_path):
    from backend.worker import ConversationWorker

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'integration.db'}"
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        database_url=database_url,
        bot_api_key="test-bot",
        admin_api_key="test-admin",
        app_env="test",
        mock_llm=True,
    )
    app = create_bridge(settings, factory)
    admin = {"X-Admin-API-Key": "test-admin"}
    bot = {"X-API-Key": "test-bot"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        result = await http.put(
            "/api/v1/admin/guilds/123456789012345678/settings",
            headers=admin,
            json={
                "enabled": True,
                "allowed_channel_ids": ["234567890123456789"],
                "retention_days": 30,
            },
        )
        assert result.status_code == 200
        result = await http.post(
            "/api/v1/messages",
            headers=bot,
            json={
                "guild_id": "123456789012345678",
                "channel_id": "234567890123456789",
                "message_id": "345678901234567890",
                "author_id": "456789012345678901",
                "author_name": "Integration test",
                "content": "We are planning a garden community launch next weekend.",
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        assert result.status_code == 202
        worker = ConversationWorker(settings)
        try:
            assert await worker.process_once()
        finally:
            await worker.session_factory.kw["bind"].dispose()
        listing = (
            await http.get("/api/v1/admin/web/guilds/123456789012345678/topics", headers=admin)
        ).json()
        assert listing["total"] == 1
        topic_id = listing["items"][0]["topic_id"]
        assert listing["items"][0]["message_count"] == 1
        query = "?guild_id=123456789012345678"
        messages = (
            await http.get(f"/api/v1/topics/{topic_id}/messages{query}", headers=bot)
        ).json()
        assert messages["items"][0]["message_id"] == "345678901234567890"
        summary = await http.get(f"/api/v1/topics/{topic_id}/summary{query}", headers=bot)
        assert summary.status_code == 200
        model = {
            "provider": "meta",
            "model_id": "test-model",
            "temperature": 0.1,
            "max_tokens": 1024,
        }
        assert (
            await http.put(f"/api/v1/admin/model-config{query}", headers=admin, json=model)
        ).status_code == 200
        assert (await http.get(f"/api/v1/admin/model-config{query}", headers=admin)).json()[
            "model_id"
        ] == "test-model"
        assert (
            await http.post(f"/api/v1/admin/topics/{topic_id}/close{query}", headers=admin)
        ).status_code == 200
        closed = (
            await http.get(
                "/api/v1/admin/web/guilds/123456789012345678/topics?status=CLOSED", headers=admin
            )
        ).json()
        assert closed["total"] == 1
    await engine.dispose()

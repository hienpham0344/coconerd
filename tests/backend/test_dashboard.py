from datetime import UTC, datetime, timedelta

import pytest

from backend.infrastructure.database.models import GuildSettingsRecord, TopicRecord

ADMIN = {"X-Admin-API-Key": "admin-test-key"}
BASE = "/api/v1/admin/web"


@pytest.mark.asyncio
async def test_dashboard_main_api_is_authenticated_scoped_and_paginated(
    api_client, database_factory
):
    async with database_factory() as session:
        session.add_all(
            [
                GuildSettingsRecord(
                    guild_id="one",
                    enabled=True,
                    allowed_channel_ids=["c1"],
                    output_channel_id="out",
                    retention_days=30,
                ),
                GuildSettingsRecord(guild_id="two", enabled=False, allowed_channel_ids=[]),
                TopicRecord(id="t1", guild_id="one", title="Garden release", status="ACTIVE"),
                TopicRecord(id="t2", guild_id="two", title="Secret", status="CLOSED"),
            ]
        )
        await session.commit()
    assert (await api_client.get(f"{BASE}/guilds")).status_code == 401
    response = await api_client.get(f"{BASE}/guilds", headers=ADMIN)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
    result = await api_client.get(f"{BASE}/guilds/one/topics", headers=ADMIN)
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["topic_id"] == "t1"
    assert (await api_client.get(f"{BASE}/guilds/one/topics?q=Secret", headers=ADMIN)).json()[
        "total"
    ] == 0
    assert (await api_client.get(f"{BASE}/guilds/one/topics?offset=1", headers=ADMIN)).json()[
        "items"
    ] == []
    assert (
        await api_client.get(f"{BASE}/guilds/one/topics?status=invalid", headers=ADMIN)
    ).status_code == 422
    assert (
        await api_client.get(f"{BASE}/guilds/missing/overview", headers=ADMIN)
    ).status_code == 404
    overview = (await api_client.get(f"{BASE}/guilds/one/overview", headers=ADMIN)).json()
    assert overview == {"topics": 1, "active_topics": 1, "messages": 0, "channels": 1}
    settings = (await api_client.get(f"{BASE}/guilds/one/settings", headers=ADMIN)).json()
    assert settings["output_channel_id"] == "out"


@pytest.mark.asyncio
async def test_dashboard_credentials_are_persistent_expiring_and_one_use(api_client):
    path = f"{BASE}/credentials/oauth/{'a' * 64}"
    body = {
        "payload": "encrypted-opaque-value",
        "expires_at": (datetime.now(UTC) + timedelta(minutes=4)).isoformat(),
    }
    assert (await api_client.put(path, json=body)).status_code == 401
    assert (await api_client.put(path, json=body, headers=ADMIN)).status_code == 200
    stored = (await api_client.get(path, headers=ADMIN)).json()
    assert stored["payload"] == body["payload"]
    assert stored["expires_at"].endswith(("Z", "+00:00"))
    assert (await api_client.post(path + "/consume", headers=ADMIN)).status_code == 200
    assert (await api_client.post(path + "/consume", headers=ADMIN)).status_code == 404
    assert (await api_client.get(path, headers=ADMIN)).status_code == 404
    session_path = f"{BASE}/credentials/session/{'b' * 64}"
    assert (await api_client.put(session_path, json=body, headers=ADMIN)).status_code == 200
    assert (await api_client.delete(session_path, headers=ADMIN)).status_code == 204
    assert (await api_client.get(session_path, headers=ADMIN)).status_code == 404
    retry = {**body, "expected_payload": body["payload"]}
    assert (await api_client.put(session_path, json=retry, headers=ADMIN)).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,hours", [("session", 13), ("oauth", 1), ("session", -1)])
async def test_dashboard_rejects_invalid_credential_expiry(api_client, kind, hours):
    body = {
        "payload": "opaque",
        "expires_at": (datetime.now(UTC) + timedelta(hours=hours)).isoformat(),
    }
    response = await api_client.put(
        f"{BASE}/credentials/{kind}/{'c' * 64}", json=body, headers=ADMIN
    )
    assert response.status_code == 422


def test_dashboard_migration_preserves_existing_data(tmp_path, monkeypatch):
    import asyncio

    from alembic.config import Config
    from sqlalchemy import inspect, text
    from sqlalchemy.ext.asyncio import create_async_engine

    from alembic import command
    from backend.config import get_settings

    database_url = f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("COCONERD_DATABASE_URL", database_url)
    monkeypatch.setenv("COCONERD_REQUIRE_POSTGRES", "false")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    config = Config("alembic.ini")

    async def seed():
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO guild_settings("
                    "guild_id,enabled,allowed_channel_ids,retention_days,"
                    "updated_at) VALUES ('existing',1,'[]',30,CURRENT_TIMESTAMP)"
                )
            )
        await engine.dispose()

    async def verify():
        engine = create_async_engine(database_url)
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT guild_id FROM guild_settings")) == "existing"
            )
            assert await connection.run_sync(
                lambda conn: inspect(conn).has_table("dashboard_credentials")
            )
        await engine.dispose()

    try:
        command.upgrade(config, "20261105_0006")
        asyncio.run(seed())
        command.upgrade(config, "head")
        command.check(config)
        asyncio.run(verify())
    finally:
        get_settings.cache_clear()

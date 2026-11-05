import pytest
from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command
from backend.config import get_settings


def test_postgres_migration_preserves_old_data_and_schema(postgres_database_url, monkeypatch):
    if not postgres_database_url:
        pytest.skip("Set COCONERD_TEST_POSTGRES_URL to a disposable PostgreSQL server")
    monkeypatch.setenv("COCONERD_DATABASE_URL", postgres_database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "20261103_0001")
        import asyncio
        import json

        from sqlalchemy.ext.asyncio import create_async_engine

        async def seed():
            engine = create_async_engine(postgres_database_url)
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO topics(id,guild_id,title,description,status,created_at,"
                        "last_activity_at,version) VALUES "
                        "('old','g','Persistent storage engine','','ACTIVE',now(),now(),3)"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO topic_summaries(id,guild_id,topic_id,version,data,"
                        "source_message_ids,created_at) VALUES "
                        "('s','g','old',1,CAST(:data AS JSON),'[]',now())"
                    ),
                    {"data": json.dumps({"overview": "Sign in " + "A" * 450})},
                )
            await engine.dispose()

        asyncio.run(seed())
        command.upgrade(config, "head")
        command.check(config)

        async def verify():
            engine = create_async_engine(postgres_database_url)
            async with engine.connect() as connection:
                row = (
                    await connection.execute(
                        text("SELECT version,sync_paused FROM topics WHERE id='old'")
                    )
                ).one()
                assert row == (3, False)
                terms = set(
                    (
                        await connection.execute(
                            text("SELECT term FROM topic_search_terms WHERE topic_id='old'")
                        )
                    ).scalars()
                )
                assert {"database", "login"} <= terms
                indexes = await connection.run_sync(
                    lambda conn: inspect(conn).get_indexes("model_configs")
                )
                assert all(
                    index["dialect_options"].get("postgresql_where")
                    for index in indexes
                    if index["name"].startswith("uq_model_configs_")
                )
            await engine.dispose()

        asyncio.run(verify())
    finally:
        get_settings.cache_clear()

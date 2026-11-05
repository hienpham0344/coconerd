import asyncio
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config import Settings
from backend.infrastructure.database.models import Base
from backend.presentation.api.app import create_app


@pytest.fixture(autouse=True)
def isolate_runtime_database(monkeypatch):
    # bot.main loads .env during collection; tests must never inherit its Railway URL.
    monkeypatch.setenv("COCONERD_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("COCONERD_REQUIRE_POSTGRES", "false")


@pytest.fixture
def postgres_database_url():
    """Create/drop only a fresh test-owned database on an explicitly selected server."""
    server_url = os.environ.get("COCONERD_TEST_POSTGRES_URL")
    if not server_url:
        yield None
        return
    database = "coconerd_test_" + uuid4().hex
    admin_url = make_url(server_url).set(drivername="postgresql")
    dsn = admin_url.render_as_string(hide_password=False)

    async def execute(statement):
        connection = await asyncpg.connect(dsn)
        try:
            await connection.execute(statement)
        finally:
            await connection.close()

    asyncio.run(execute(f'CREATE DATABASE "{database}"'))
    try:
        yield admin_url.set(drivername="postgresql+asyncpg", database=database).render_as_string(
            hide_password=False
        )
    finally:
        asyncio.run(execute(f'DROP DATABASE "{database}" WITH (FORCE)'))


@pytest_asyncio.fixture
async def database_factory(tmp_path, postgres_database_url) -> AsyncIterator[async_sessionmaker]:
    engine = create_async_engine(
        postgres_database_url or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def api_client(database_factory) -> AsyncIterator[AsyncClient]:
    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        bot_api_key="bot-test-key",
        admin_api_key="admin-test-key",
    )
    app = create_app(settings=settings, session_factory=database_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def unauthenticated_api_client(tmp_path) -> AsyncIterator[AsyncClient]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'unused.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        bot_api_key="bot-test-key",
        admin_api_key="admin-test-key",
    )
    app = create_app(settings=settings, session_factory=factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await engine.dispose()


@pytest_asyncio.fixture
def unit_of_work_factory():
    from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

    return SqlAlchemyUnitOfWork

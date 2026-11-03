from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config import Settings
from backend.infrastructure.database.models import Base
from backend.presentation.api.app import create_app


@pytest_asyncio.fixture
async def database_factory(tmp_path) -> AsyncIterator[async_sessionmaker]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
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

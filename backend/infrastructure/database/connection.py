from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import Settings


def create_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    url = settings.database_url
    if url.startswith("sqlite+aiosqlite:///"):
        file_path = url.removeprefix("sqlite+aiosqlite:///").split("?", maxsplit=1)[0]
        if file_path and file_path != ":memory:":
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_async_engine(url, pool_pre_ping=True)
    if url.startswith("sqlite+"):

        @event.listens_for(engine.sync_engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def session_dependency(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session

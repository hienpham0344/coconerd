from sqlalchemy import text

from backend.config import Settings
from backend.infrastructure.database.connection import create_session_factory


async def test_sqlite_pragmas_configured_on_session_factory(tmp_path):
    settings = Settings(
        _env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path / 'pragma.db'}"
    )
    factory = create_session_factory(settings)
    try:
        async with factory() as session:
            assert (await session.execute(text("PRAGMA foreign_keys"))).scalar() == 1
            assert (await session.execute(text("PRAGMA journal_mode"))).scalar().lower() == "wal"
            assert (await session.execute(text("PRAGMA busy_timeout"))).scalar() == 30000
    finally:
        await factory.kw["bind"].dispose()

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from backend.config import Settings
from backend.infrastructure.database.models import ModelConfigRecord
from backend.infrastructure.database.repositories.health import HealthRepository


def test_railway_required_never_falls_back_to_sqlite():
    with pytest.raises(ValidationError, match="PostgreSQL is required"):
        Settings(_env_file=None, require_postgres=True)
    settings = Settings(
        _env_file=None,
        require_postgres=True,
        database_url="postgresql://user:password@db.example/railway",
    )
    assert settings.database_url.startswith("postgresql+asyncpg://")


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
def test_railway_postgres_url_uses_asyncpg_without_losing_credentials(scheme):
    url = f"{scheme}://user:p%40ss%2Fword@db.example:15432/coconerd?ssl=require"
    settings = Settings(_env_file=None, database_url=url)
    assert settings.database_url == url.replace(scheme + "://", "postgresql+asyncpg://", 1)


@pytest.mark.parametrize("url", ["mysql://db/app", "postgresql+psycopg://db/app"])
def test_unsupported_database_driver_is_rejected(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=url)


def test_postgres_model_config_indexes_keep_guild_filters():
    indexes = {index.name: index for index in ModelConfigRecord.__table__.indexes}
    for name, predicate in [
        ("uq_model_configs_global", "guild_id IS NULL"),
        ("uq_model_configs_guild", "guild_id IS NOT NULL"),
    ]:
        ddl = str(CreateIndex(indexes[name]).compile(dialect=postgresql.dialect()))
        assert f"WHERE {predicate}" in ddl


async def test_heartbeat_uses_the_bound_postgres_dialect():
    statements = []

    class Session:
        def get_bind(self):
            return SimpleNamespace(dialect=postgresql.dialect())

        async def execute(self, statement):
            statements.append(statement)

    from datetime import UTC, datetime

    await HealthRepository(Session()).record_heartbeat("worker", "idle", datetime.now(UTC))
    assert statements[0].__class__.__module__ == "sqlalchemy.dialects.postgresql.dml"

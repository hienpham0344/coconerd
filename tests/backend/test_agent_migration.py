import sqlite3

from alembic.config import Config

from alembic import command
from backend.config import get_settings


def test_additive_agent_migration_preserves_and_indexes_existing_topics(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setenv("COCONERD_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    get_settings.cache_clear()
    try:
        config = Config("alembic.ini")
        command.upgrade(config, "20261103_0001")
        with sqlite3.connect(path) as connection:
            connection.execute(
                "INSERT INTO topics(id,guild_id,title,description,status,created_at,"
                "last_activity_at,version) VALUES "
                "('old','g','Cơ sở dữ liệu','','ACTIVE','2026-01-01','2026-01-01',1)"
            )
        command.upgrade(config, "head")
        with sqlite3.connect(path) as connection:
            assert (
                connection.execute("SELECT title FROM topics WHERE id='old'").fetchone()[0]
                == "Cơ sở dữ liệu"
            )
            assert (
                connection.execute(
                    "SELECT term FROM topic_search_terms WHERE topic_id='old'"
                ).fetchone()[0]
                == "database"
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(processing_jobs)")}
            assert {
                "model_call_count",
                "reassessment_count",
                "deferred_until",
                "followup_message_id",
            } <= columns
    finally:
        get_settings.cache_clear()

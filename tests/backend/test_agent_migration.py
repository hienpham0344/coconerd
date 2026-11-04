import sqlite3

from alembic.config import Config

from alembic import command
from backend.config import get_settings


def test_discord_channel_migration_preserves_existing_data(tmp_path, monkeypatch):
    path = tmp_path / "discord.db"
    monkeypatch.setenv("COCONERD_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    get_settings.cache_clear()
    try:
        config = Config("alembic.ini")
        command.upgrade(config, "20261104_0003")
        with sqlite3.connect(path) as connection:
            connection.execute(
                "INSERT INTO guild_settings VALUES ('g',1,'[\"input\"]',90,'2026-11-04')"
            )
            connection.execute(
                "INSERT INTO topics(id,guild_id,title,description,status,created_at,"
                "last_activity_at,version) VALUES "
                "('topic','g','Preserved','','ACTIVE','2026-11-04','2026-11-04',1)"
            )
            connection.execute(
                "INSERT INTO messages(id,guild_id,channel_id,discord_message_id,author_id,"
                "author_name,content,created_at,ingested_at) VALUES "
                "('m','g','input','discord-m','u','User','Hello','2026-11-04','2026-11-04')"
            )
            connection.execute(
                "INSERT INTO message_topic_associations(id,guild_id,message_record_id,topic_id,"
                "kind,confidence,reason) VALUES "
                "('a','g','m','topic','CLASSIFIED',1,'')"
            )
        command.upgrade(config, "head")
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT title,channel_id FROM topics").fetchone() == (
                "Preserved",
                "input",
            )
            assert connection.execute(
                "SELECT retention_days,output_channel_id FROM guild_settings"
            ).fetchone() == (90, None)
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        get_settings.cache_clear()


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


def test_reliability_migration_backfills_review_state_and_old_phrase_index(tmp_path, monkeypatch):
    path = tmp_path / "reliability.db"
    monkeypatch.setenv("COCONERD_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    get_settings.cache_clear()
    try:
        config = Config("alembic.ini")
        command.upgrade(config, "20261104_0002")
        with sqlite3.connect(path) as connection:
            connection.execute(
                "INSERT INTO topics(id,guild_id,title,description,status,created_at,"
                "last_activity_at,version) VALUES "
                "('old','g','Sign in','','ACTIVE','2026-01-01','2026-01-01',3)"
            )
            connection.execute("INSERT INTO topic_search_terms VALUES ('old','sign','g',3)")
        command.upgrade(config, "head")
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT version,sync_paused FROM topics").fetchone() == (3, 0)
            assert connection.execute(
                "SELECT weight FROM topic_search_terms WHERE term='login'"
            ).fetchone() == (3.0,)
            assert "revision" in {
                r[1] for r in connection.execute("PRAGMA table_info(message_topic_associations)")
            }
            assert "superseded" in {
                r[1] for r in connection.execute("PRAGMA table_info(discord_actions)")
            }
            assert connection.execute("SELECT count(*) FROM review_events").fetchone()[0] == 0
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        command.downgrade(config, "20261104_0002")
        command.upgrade(config, "head")
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT title FROM topics").fetchone()[0] == "Sign in"
    finally:
        get_settings.cache_clear()

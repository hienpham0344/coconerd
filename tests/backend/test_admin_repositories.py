"""SQL query, scope, ordering and DTO checks without an async database driver."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from backend.application.read_models import GuildSettings, ModelConfiguration
from backend.infrastructure.database.models import (
    DiscordActionRecord,
    GuildSettingsRecord,
    ModelConfigRecord,
)
from backend.infrastructure.database.repositories.actions import ActionRepository
from backend.infrastructure.database.repositories.guilds import GuildRepository
from backend.infrastructure.database.repositories.health import HealthRepository
from backend.infrastructure.database.repositories.model_config import ModelConfigRepository
from backend.infrastructure.database.repositories.topics import TopicRepository


def sql(statement):
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.parametrize(
    "kind,tables",
    [
        (
            "guild",
            [
                "processing_jobs",
                "discord_actions",
                "topic_summaries",
                "conversation_episodes",
                "message_topic_associations",
                "ai_decisions",
                "topic_search_terms",
                "topics",
                "messages",
                "guild_settings",
                "model_configs",
            ],
        ),
        (
            "topic",
            [
                "discord_actions",
                "processing_jobs",
                "ai_decisions",
                "messages",
                "topic_summaries",
                "message_topic_associations",
                "conversation_episodes",
                "topic_search_terms",
                "topics",
            ],
        ),
    ],
)
async def test_deletion_order_and_scoping_match_contract(kind, tables):
    session = Mock(execute=AsyncMock(), commit=AsyncMock())
    if kind == "guild":
        await GuildRepository(session).delete_data("g")
    else:
        await TopicRepository(session).delete_data("g", "t")
    statements = [call.args[0] for call in session.execute.call_args_list]
    assert [statement.table.name for statement in statements] == tables
    for statement in statements:
        compiled = sql(statement)
        assert "guild_id = 'g'" in compiled
        if kind == "topic":
            assert "topic_id = 't'" in compiled or "topics.id = 't'" in compiled
    session.commit.assert_not_awaited()


@pytest.mark.parametrize("existing", [None, GuildSettingsRecord(guild_id="g", enabled=False)])
async def test_guild_settings_insert_or_update_maps_values_without_commit(existing):
    session = Mock(get=AsyncMock(return_value=existing), add=Mock(), commit=AsyncMock())
    settings = GuildSettings("g", True, ["c"], 42)
    assert await GuildRepository(session).save_settings(settings) == settings
    record = existing if existing is not None else session.add.call_args.args[0]
    assert (record.guild_id, record.enabled, record.allowed_channel_ids, record.retention_days) == (
        "g",
        True,
        ["c"],
        42,
    )
    session.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "existing", [None, ModelConfigRecord(id="old", scope="guild", guild_id="g")]
)
async def test_model_config_upsert_maps_scope_and_preserves_existing_id(existing):
    session = Mock(scalar=AsyncMock(return_value=existing), add=Mock(), commit=AsyncMock())
    config = ModelConfiguration("guild", "g", "meta", "model", 0.5, 120)
    await ModelConfigRepository(session).save(config)
    record = existing if existing is not None else session.add.call_args.args[0]
    assert (
        record.scope,
        record.guild_id,
        record.provider,
        record.model_id,
        record.temperature,
        record.max_tokens,
    ) == ("guild", "g", "meta", "model", 0.5, 120)
    if existing is not None:
        assert record.id == "old"
        session.add.assert_not_called()
    session.commit.assert_not_awaited()


async def test_model_config_global_query_uses_null_and_returns_plain_dto():
    record = ModelConfigRecord(
        id="config",
        scope="global",
        guild_id=None,
        provider="meta",
        model_id="model",
        temperature=0.1,
        max_tokens=42,
    )
    session = Mock(scalar=AsyncMock(return_value=record))
    result = await ModelConfigRepository(session).get("global", None)
    assert result == ModelConfiguration("global", None, "meta", "model", 0.1, 42)
    assert "model_configs.guild_id IS NULL" in sql(session.scalar.call_args.args[0])


async def test_action_state_read_and_update_do_not_own_transaction():
    record = DiscordActionRecord(
        id="a",
        guild_id="g",
        channel_id="c",
        topic_id="t",
        action_type="CREATE_THREAD",
        status="CLAIMED",
        payload={},
        lease_owner="worker",
        attempt_count=2,
        max_attempts=3,
    )
    session = Mock(get=AsyncMock(return_value=record), execute=AsyncMock(), commit=AsyncMock())
    repository = ActionRepository(session)
    result = await repository.get("a")
    assert result.id == "a" and result.lease_owner == "worker" and result.attempt_count == 2
    await repository.update("a", status="DEAD", lease_owner=None, lease_expires_at=None)
    compiled = sql(session.execute.call_args.args[0])
    assert "WHERE discord_actions.id = 'a'" in compiled
    assert "lease_owner=NULL" in compiled and "status='DEAD'" in compiled
    session.commit.assert_not_awaited()


async def test_action_claim_uses_service_clock_and_keeps_dependency_budget_and_expiry_filters():
    empty_rows = Mock(all=Mock(return_value=[]))
    session = Mock(scalars=AsyncMock(return_value=empty_rows), execute=AsyncMock())
    now = datetime.now(UTC)
    assert (
        await ActionRepository(session).claim_available("w", 7, now, now + timedelta(seconds=30))
        == []
    )
    statement = session.scalars.call_args.args[0]
    compiled = sql(statement)
    assert "discord_actions.status = 'PENDING'" in compiled
    assert "discord_actions.status = 'CLAIMED'" in compiled
    assert "discord_actions.lease_expires_at <" in compiled
    assert "discord_actions.available_at <=" in compiled
    assert "discord_actions.attempt_count < discord_actions.max_attempts" in compiled
    assert "discord_actions.dependency_id IS NULL" in compiled
    assert "discord_actions.status = 'SUCCEEDED'" in compiled
    assert "LIMIT 7" in compiled
    session.execute.assert_not_awaited()


async def test_health_filters_live_worker_status_and_cutoff():
    session = Mock(scalar=AsyncMock(return_value="worker"), execute=AsyncMock())
    cutoff = datetime.now(UTC)
    repository = HealthRepository(session)
    await repository.probe()
    assert sql(session.execute.call_args.args[0]) == "SELECT 1"
    assert await repository.has_recent_worker(cutoff)
    compiled = sql(session.scalar.call_args.args[0])
    assert "worker_heartbeats.status IN ('running', 'idle')" in compiled
    assert "worker_heartbeats.last_seen_at >=" in compiled

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.application.errors import Conflict, InvalidTransition, NotFound
from backend.application.read_models import (
    ActionState,
    GuildSettings,
    ModelConfiguration,
    TopicReadModel,
)
from backend.application.services import actions, guilds, health, model_config, topics


def uow(**repositories):
    return SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock(), **repositories)


def topic(status="ACTIVE"):
    return TopicReadModel("t", "g", "Title", "Description", status, datetime.now(UTC), 1, None)


def action(**changes):
    values = dict(
        id="a",
        guild_id="g",
        channel_id="c",
        topic_id="t",
        action_type="CREATE_THREAD",
        status="CLAIMED",
        payload={},
        dependency_id=None,
        lease_owner="worker",
        attempt_count=1,
        max_attempts=3,
        discord_thread_id=None,
        discord_message_id=None,
    )
    return ActionState(**(values | changes))


async def test_guild_settings_and_delete_commit_once():
    settings = GuildSettings("g", True, ["c"], 30)
    repo = SimpleNamespace(save_settings=AsyncMock(return_value=settings), delete_data=AsyncMock())
    work = uow(guilds=repo)
    assert await guilds.set_guild_settings(work, "g", True, ["c"], 30) == settings
    repo.save_settings.assert_awaited_once_with(settings)
    await guilds.delete_guild_data(work, "g")
    repo.delete_data.assert_awaited_once_with("g")
    assert work.commit.await_count == 2


async def test_guild_delete_failure_does_not_commit():
    work = uow(guilds=SimpleNamespace(delete_data=AsyncMock(side_effect=RuntimeError("database"))))
    with pytest.raises(RuntimeError):
        await guilds.delete_guild_data(work, "g")
    work.commit.assert_not_awaited()


async def test_model_configuration_falls_back_guild_global_defaults():
    default = ModelConfiguration("global", None, "meta", "default-model", 0.1, 100)
    global_config = ModelConfiguration("global", None, "meta", "global-model", 0.2, 200)
    override = ModelConfiguration("guild", "g", "meta", "guild-model", 0.3, 300)
    repo = SimpleNamespace(get=AsyncMock(side_effect=[override, None, global_config, None, None]))
    work = uow(model_config=repo)
    assert await model_config.get_model_config(work, "g", default) == override
    assert await model_config.get_model_config(work, "g", default) == global_config
    assert await model_config.get_model_config(work, "g", default) == default
    work.commit.assert_not_awaited()


async def test_model_configuration_write_chooses_scope():
    repo = SimpleNamespace(save=AsyncMock())
    work = uow(model_config=repo)
    result = await model_config.set_model_config(work, "g", "meta", "model", 0.2, 200)
    assert result.scope == "guild" and result.guild_id == "g"
    repo.save.assert_awaited_once_with(result)
    work.commit.assert_awaited_once()


async def test_topic_read_and_close_use_guild_scope():
    repo = SimpleNamespace(get=AsyncMock(return_value=topic()), set_status=AsyncMock())
    work = uow(topics=repo)
    assert (await topics.get_topic(work, "g", "t")).id == "t"
    repo.get.reset_mock()
    await topics.close_topic(work, "g", "t")
    repo.get.assert_awaited_once_with("g", "t")
    repo.set_status.assert_awaited_once_with("g", "t", "CLOSED")
    work.commit.assert_awaited_once()


async def test_missing_topic_precedes_invalid_cursor_and_does_not_delete():
    repo = SimpleNamespace(get=AsyncMock(return_value=None), delete_data=AsyncMock())
    work = uow(topics=repo)
    with pytest.raises(NotFound, match="Topic not found"):
        await topics.get_topic_messages(work, "other-guild", "t", 50, "bad")
    with pytest.raises(NotFound):
        await topics.delete_topic(work, "other-guild", "t")
    repo.delete_data.assert_not_awaited()
    work.commit.assert_not_awaited()


async def test_topic_closed_transition_cursor_summary_and_delete():
    repo = SimpleNamespace(
        get=AsyncMock(return_value=topic("CLOSED")), set_status=AsyncMock(), delete_data=AsyncMock()
    )
    work = uow(topics=repo, summaries=SimpleNamespace(latest=AsyncMock(return_value=None)))
    with pytest.raises(Conflict):
        await topics.close_topic(work, "g", "t")
    with pytest.raises(InvalidTransition, match="ISO-8601"):
        await topics.get_topic_messages(work, "g", "t", 50, "bad")
    with pytest.raises(NotFound, match="Topic summary not found"):
        await topics.get_topic_summary(work, "g", "t")
    work.commit.assert_not_awaited()
    await topics.delete_topic(work, "g", "t")
    repo.delete_data.assert_awaited_once_with("g", "t")
    work.commit.assert_awaited_once()


async def test_claim_policy_owns_lease_deadline():
    repo = SimpleNamespace(claim_available=AsyncMock(return_value=[]))
    work = uow(actions=repo)
    assert await actions.claim_actions(work, "worker", 2, 30) == []
    owner, limit, now, deadline = repo.claim_available.call_args.args
    assert (owner, limit) == ("worker", 2)
    assert deadline - now == timedelta(seconds=30)
    work.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "state,error",
    [(None, NotFound), (action(lease_owner="other"), Conflict), (action(status="DEAD"), Conflict)],
)
async def test_action_rejects_missing_or_foreign_lease(state, error):
    repo = SimpleNamespace(
        get=AsyncMock(return_value=state), update_leased=AsyncMock(return_value=True)
    )
    work = uow(actions=repo)
    with pytest.raises(error):
        await actions.complete_action(work, "a", "worker", "thread", None)
    with pytest.raises(error):
        await actions.fail_action(work, "a", "worker", "Error", "failed", True)
    repo.update_leased.assert_not_awaited()
    work.commit.assert_not_awaited()


async def test_action_completion_requires_thread_and_consistent_topic_before_write():
    repo = SimpleNamespace(
        get=AsyncMock(return_value=action()), update_leased=AsyncMock(return_value=True)
    )
    work = uow(actions=repo, topics=SimpleNamespace(get=AsyncMock(return_value=None)))
    with pytest.raises(InvalidTransition):
        await actions.complete_action(work, "a", "worker", None, None)
    with pytest.raises(Conflict, match="inconsistent"):
        await actions.complete_action(work, "a", "worker", "thread", None)
    repo.update_leased.assert_not_awaited()
    work.commit.assert_not_awaited()


async def test_action_completion_updates_thread_and_repeats_without_commit():
    repo = SimpleNamespace(
        get=AsyncMock(return_value=action()), update_leased=AsyncMock(return_value=True)
    )
    topic_repo = SimpleNamespace(get=AsyncMock(return_value=topic()), set_thread=AsyncMock())
    work = uow(actions=repo, topics=topic_repo)
    result = await actions.complete_action(work, "a", "worker", "thread", None)
    assert result.status == "SUCCEEDED"
    topic_repo.set_thread.assert_awaited_once_with("g", "t", "thread")
    assert repo.update_leased.call_args.kwargs["lease_owner"] is None
    work.commit.assert_awaited_once()
    work.commit.reset_mock()
    repo.get.return_value = action(status="SUCCEEDED", discord_thread_id="thread")
    assert await actions.complete_action(work, "a", "other", "thread", None) == result
    with pytest.raises(Conflict, match="another result"):
        await actions.complete_action(work, "a", "worker", "different", None)
    work.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "attempts,retryable,expected",
    [(1, True, "PENDING"), (3, True, "DEAD"), (1, False, "DEAD"), (10, True, "PENDING")],
)
async def test_action_retry_budget_and_backoff(attempts, retryable, expected):
    repo = SimpleNamespace(
        get=AsyncMock(
            return_value=action(attempt_count=attempts, max_attempts=11 if attempts == 10 else 3)
        ),
        update_leased=AsyncMock(return_value=True),
    )
    work = uow(actions=repo)
    before = datetime.now(UTC)
    result = await actions.fail_action(work, "a", "worker", "Error", "failed", retryable)
    assert result.status == expected
    changes = repo.update_leased.call_args.kwargs
    assert changes["lease_owner"] is None and changes["lease_expires_at"] is None
    if expected == "PENDING":
        assert changes["available_at"] >= before + timedelta(seconds=min(300, 2**attempts))
    else:
        assert "available_at" not in changes
    work.commit.assert_awaited_once()


async def test_health_probe_failure_and_stale_worker():
    repo = SimpleNamespace(
        probe=AsyncMock(side_effect=RuntimeError("down")),
        has_recent_worker=AsyncMock(return_value=False),
    )
    work = uow(health=repo)
    assert (await health.get_health(work, 1)).database == "unavailable"
    repo.has_recent_worker.assert_not_awaited()
    repo.probe.side_effect = None
    assert (await health.get_health(work, 1)).worker == "unavailable"
    work.rollback.assert_awaited_once()
    repo.has_recent_worker.return_value = True
    assert (await health.get_health(work, 1)).status == "ok"


async def test_action_completion_rejects_inconsistent_topic_guild():
    foreign_topic = TopicReadModel("t", "other", "Title", "", "ACTIVE", datetime.now(UTC), 1, None)
    repo = SimpleNamespace(
        get=AsyncMock(return_value=action()), update_leased=AsyncMock(return_value=True)
    )
    work = uow(
        actions=repo,
        topics=SimpleNamespace(get=AsyncMock(return_value=foreign_topic), set_thread=AsyncMock()),
    )
    with pytest.raises(Conflict, match="inconsistent"):
        await actions.complete_action(work, "a", "worker", "thread", None)
    repo.update_leased.assert_not_awaited()
    work.topics.set_thread.assert_not_awaited()
    work.commit.assert_not_awaited()

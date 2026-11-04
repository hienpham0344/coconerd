from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.infrastructure.database.models import DiscordActionRecord, TopicRecord
from bot.main import BackendClient


async def test_bot_reads_saved_channel_configuration(api_client):
    response = await api_client.put(
        "/api/v1/admin/guilds/g/settings",
        headers={"X-Admin-API-Key": "admin-test-key"},
        json={
            "enabled": True,
            "allowed_channel_ids": ["input"],
            "output_channel_id": "output",
            "retention_days": 90,
        },
    )
    assert response.status_code == 200
    response = await api_client.get(
        "/api/v1/guilds/g/settings", headers={"X-API-Key": "bot-test-key"}
    )
    assert response.status_code == 200
    assert response.json()["output_channel_id"] == "output"
    assert response.json()["allowed_channel_ids"] == ["input"]


async def test_output_channel_cannot_be_an_input_channel(api_client):
    response = await api_client.put(
        "/api/v1/admin/guilds/g/settings",
        headers={"X-Admin-API-Key": "admin-test-key"},
        json={
            "enabled": True,
            "allowed_channel_ids": ["same"],
            "output_channel_id": "same",
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("operation", ["complete", "fail"])
async def test_bot_returns_current_lease_token_when_acknowledging_actions(operation):
    client = BackendClient("http://test", "bot-key")
    claim_response = MagicMock()
    claim_response.status = 200
    claim_response.json = AsyncMock(return_value=[{"action_id": "a", "lease_token": "lease"}])
    ack_response = MagicMock()
    ack_response.status = 200
    claim_context = MagicMock()
    claim_context.__aenter__ = AsyncMock(return_value=claim_response)
    claim_context.__aexit__ = AsyncMock(return_value=False)
    ack_context = MagicMock()
    ack_context.__aenter__ = AsyncMock(return_value=ack_response)
    ack_context.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post.side_effect = [claim_context, ack_context]
    client.get_session = AsyncMock(return_value=session)
    await client.claim_actions("worker", limit=1)
    if operation == "complete":
        assert await client.complete_action("a", "worker", discord_thread_id="thread")
    else:
        assert await client.fail_action("a", "worker", "DiscordError", "Failed")
    assert session.post.call_args.kwargs["json"]["lease_token"] == "lease"


@pytest.mark.parametrize("existing_thread", [None, "original-thread"])
async def test_leased_completion_persists_mapping_without_replacing_another_thread(
    api_client, database_factory, existing_thread
):
    async with database_factory() as session:
        session.add(
            TopicRecord(
                id="topic",
                guild_id="g",
                channel_id="input",
                title="Topic",
                discord_thread_id=existing_thread,
            )
        )
        await session.flush()
        session.add(
            DiscordActionRecord(
                id="action",
                guild_id="g",
                channel_id="input",
                topic_id="topic",
                action_type="CREATE_THREAD",
                status="PENDING",
                payload={},
            )
        )
        await session.commit()
    headers = {"X-API-Key": "bot-test-key"}
    claim = await api_client.post(
        "/api/v1/actions/claim", headers=headers, json={"worker_id": "worker", "limit": 1}
    )
    assert claim.status_code == 200
    action = claim.json()[0]
    response = await api_client.post(
        "/api/v1/actions/action/complete",
        headers=headers,
        json={
            "worker_id": "worker",
            "lease_token": action["lease_token"],
            "discord_thread_id": "new-thread",
        },
    )
    assert response.status_code == (409 if existing_thread else 200)
    async with database_factory() as session:
        topic = await session.get(TopicRecord, "topic")
        action = await session.get(DiscordActionRecord, "action")
        assert topic.discord_thread_id == (existing_thread or "new-thread")
        assert action.status == ("CLAIMED" if existing_thread else "SUCCEEDED")

from unittest.mock import AsyncMock

import pytest

from bot.delivery import DeliveryError, DeliveryReceipts


async def test_receipts_have_a_separate_rate_limit_from_message_ingest(
    api_client, database_factory
):
    import hashlib
    from datetime import UTC, datetime

    from backend.infrastructure.database.models import ApiRateLimitRecord

    async with database_factory() as session:
        session.add(
            ApiRateLimitRecord(
                client_fingerprint=hashlib.sha256(b"bot-test-key").hexdigest(),
                window_start=datetime.now(UTC).replace(second=0, microsecond=0),
                request_count=120,
            )
        )
        await session.commit()
    headers = {"X-API-Key": "bot-test-key"}
    response = await api_client.get("/api/v1/delivery-receipts/7:topic:2:thread", headers=headers)
    assert response.status_code == 404
    response = await api_client.get("/api/v1/guilds/g/settings", headers=headers)
    assert response.status_code == 429


async def test_receipt_api_persists_across_clients_and_updates(api_client):
    path = "/api/v1/delivery-receipts/7:topic:2:thread"
    headers = {"X-API-Key": "bot-test-key"}
    missing = await api_client.get(path, headers=headers)
    assert missing.status_code == 404
    saved = await api_client.put(path, headers=headers, json={"discord_id": "2000"})
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"discord_id": "2000"}
    loaded = await api_client.get(path, headers=headers)
    assert loaded.json() == {"discord_id": "2000"}
    await api_client.put(path, headers=headers, json={"discord_id": "3000"})
    assert (await api_client.get(path, headers=headers)).json() == {"discord_id": "3000"}


@pytest.mark.parametrize("method", ["get", "put"])
async def test_receipt_api_requires_bot_auth(api_client, method):
    kwargs = {"json": {"discord_id": "2000"}} if method == "put" else {}
    response = await getattr(api_client, method)(
        "/api/v1/delivery-receipts/7:topic:2:thread", **kwargs
    )
    assert response.status_code == 401


async def test_receipt_api_rejects_unbounded_keys_and_values(api_client):
    headers = {"X-API-Key": "bot-test-key"}
    for key, value in [("x" * 501, "1"), ("safe", "1" * 101)]:
        response = await api_client.put(
            f"/api/v1/delivery-receipts/{key}", headers=headers, json={"discord_id": value}
        )
        assert response.status_code == 422


async def test_bot_receipts_use_backend_and_propagate_failure():
    backend = AsyncMock()
    backend.get_delivery_receipt.return_value = "2000"
    receipts = DeliveryReceipts(backend)
    assert await receipts.get("7:topic:2:thread") == "2000"
    await receipts.put("7:topic:2:thread", "2000")
    backend.put_delivery_receipt.assert_awaited_once_with("7:topic:2:thread", "2000")
    backend.get_delivery_receipt.side_effect = DeliveryError("Backend unavailable", retryable=True)
    with pytest.raises(DeliveryError, match="Backend unavailable"):
        await receipts.get("7:topic:2:thread")

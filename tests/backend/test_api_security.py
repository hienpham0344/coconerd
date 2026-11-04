import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from backend.presentation.api.security import verify_key


@pytest.mark.parametrize("value", ["", " ", "\t"])
@pytest.mark.parametrize("label", ["Bot API", "Admin API"])
def test_blank_configured_credentials_fail_closed(value, label):
    with pytest.raises(HTTPException) as caught:
        verify_key(SecretStr(value), value, label)
    assert caught.value.status_code == 503


def test_nonempty_key_still_requires_exact_match():
    verify_key(SecretStr("test-key"), "test-key", "Bot API")
    with pytest.raises(HTTPException) as caught:
        verify_key(SecretStr("test-key"), "test-key ", "Bot API")
    assert caught.value.status_code == 401


def test_non_ascii_wrong_key_is_unauthorized_instead_of_server_error():
    with pytest.raises(HTTPException) as caught:
        verify_key(SecretStr("test-key"), "\u00ff", "Bot API")
    assert caught.value.status_code == 401


async def test_summary_reads_use_the_same_bot_rate_limit(api_client, database_factory, monkeypatch):
    import hashlib
    from datetime import UTC, datetime

    from backend.infrastructure.database.models import ApiRateLimitRecord
    from backend.presentation.api import rate_limit

    now = datetime(2026, 11, 4, 10, 20, 30, tzinfo=UTC)

    class FixedClock:
        @staticmethod
        def now(_timezone):
            return now

    monkeypatch.setattr(rate_limit, "datetime", FixedClock)
    async with database_factory() as session:
        session.add(
            ApiRateLimitRecord(
                client_fingerprint=hashlib.sha256(b"bot-test-key").hexdigest(),
                window_start=now.replace(second=0, microsecond=0),
                request_count=120,
            )
        )
        await session.commit()
    response = await api_client.get(
        "/api/v1/topics/any-topic/summary?guild_id=g", headers={"X-API-Key": "bot-test-key"}
    )
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0

"""Public HTTP contract and bounded, replayable request bodies."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient

from backend.config import Settings
from backend.presentation.api import app as api


def test_openapi_preserves_public_contract():
    expected = json.loads((Path(__file__).parent / "fixtures/openapi.json").read_text())
    assert api.create_app(Settings(_env_file=None)).openapi() == expected


async def test_ingest_receives_json_through_real_request_middleware(monkeypatch):
    async def no_rate_limit():
        pass

    monkeypatch.setattr(api, "rate_limit_dependency", lambda *args: no_rate_limit)
    operation = AsyncMock()
    monkeypatch.setattr(api.messages, "ingest_message", operation)
    application = api.create_app(Settings(_env_file=None, bot_api_key="bot-key"))
    payload = {
        "guild_id": "g",
        "channel_id": "c",
        "message_id": "m",
        "author_id": "u",
        "author_name": "Author",
        "content": "Release planning",
        "created_at": "2026-11-03T00:00:00Z",
    }
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/messages",
            json=payload,
            headers={"X-API-Key": "bot-key", "X-Request-ID": "request-test"},
        )
    assert response.status_code == 202, response.text
    assert response.json() == {"message_id": payload["message_id"], "status": "accepted"}
    assert response.headers["X-Request-ID"] == "request-test"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    operation.assert_awaited_once()
    assert operation.call_args.args[1].content == payload["content"]
    await application.state.session_factory.kw["bind"].dispose()


async def test_body_limit_checks_stream_even_without_content_length():
    application = api.create_app(Settings(_env_file=None, max_request_bytes=1024))

    async def chunks():
        yield b"a" * 600
        yield b"b" * 600

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/messages", content=chunks(), headers={"X-Request-ID": "oversize-test"}
        )
        invalid = await client.post(
            "/api/v1/messages", content=b"{}", headers={"Content-Length": "invalid"}
        )
    assert response.status_code == 413
    assert response.headers["X-Request-ID"] == "oversize-test"
    assert invalid.status_code == 400
    assert invalid.text == "Invalid Content-Length"
    await application.state.session_factory.kw["bind"].dispose()

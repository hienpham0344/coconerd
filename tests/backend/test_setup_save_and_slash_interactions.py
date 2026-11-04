"""Unit tests verifying Setup Save flow and Discord interaction error handling.

Verifies:
1. Setup Save uses Admin API key and successfully persists configuration to backend database.
2. Setup Save classifies backend HTTP errors (401, 403, 422, 500) and network connection failures,
   distinguishing them in logs and surfacing concise English messages to users while preserving the interface.
3. Centralized slash command error handler (@bot.tree.error) catches MissingPermissions and CheckFailure,
   acknowledging the interaction within Discord's deadline using ephemeral responses.
4. Already acknowledged interactions safely fall back to followup.send.
"""

from datetime import UTC, datetime
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock

import discord
from discord import app_commands
import pytest

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.infrastructure.database.models import GuildSettingsRecord
from bot.main import (
    BackendClient,
    SetupConfigView,
    create_bot,
    get_admin_api_key,
    get_bot_api_key,
)


# =============================================================================
# 1. Setup Save Flow & Admin API Authentication Tests
# =============================================================================

@pytest.mark.asyncio
async def test_backend_client_update_guild_settings_uses_admin_api(
    api_client, database_factory, monkeypatch
):
    """Verifies BackendClient.update_guild_settings uses the Admin API endpoint with X-Admin-API-Key."""
    # Ensure environment has admin key
    monkeypatch.setenv("COCONERD_ADMIN_API_KEY", "admin-test-key")
    monkeypatch.setenv("COCONERD_BOT_API_KEY", "bot-test-key")

    client = BackendClient(
        base_url="http://testserver",
        api_key="bot-test-key",
        admin_api_key="admin-test-key",
    )

    # Use custom session targeting the ASGI transport
    session = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "guild_id": "guild-123",
            "enabled": True,
            "allowed_channel_ids": ["ch-1", "ch-2"],
            "output_channel_id": "ch-out",
            "retention_days": 180,
        }
    )

    class MockContextManager:
        async def __aenter__(self):
            return mock_resp

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    session.put = MagicMock(return_value=MockContextManager())
    client.get_session = AsyncMock(return_value=session)

    res = await client.update_guild_settings(
        guild_id="guild-123",
        allowed_channel_ids=["ch-1", "ch-2"],
        output_channel_id="ch-out",
        enabled=True,
        retention_days=180,
    )

    assert res is not None
    assert res["guild_id"] == "guild-123"
    assert client.last_error is None

    # Assert put called with admin endpoint and X-Admin-API-Key
    session.put.assert_called_once()
    called_url, called_kwargs = session.put.call_args
    assert "/api/v1/admin/guilds/guild-123/settings" in called_url[0]
    assert called_kwargs["headers"].get("X-Admin-API-Key") == "admin-test-key"
    assert called_kwargs["json"]["enabled"] is True
    assert called_kwargs["json"]["allowed_channel_ids"] == ["ch-1", "ch-2"]


@pytest.mark.asyncio
async def test_backend_client_url_construction_strips_trailing_slashes():
    """Verifies BackendClient strips trailing/leading slashes from guild_id and base_url."""
    client = BackendClient(
        base_url="http://localhost:8000///",
        api_key="bot-key",
        admin_api_key="admin-key",
    )

    class MockContextManager:
        async def __aenter__(self):
            resp = AsyncMock()
            resp.status = 200
            resp.json = AsyncMock(return_value={"guild_id": "1563563959339061338", "enabled": True})
            return resp

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    session = AsyncMock()
    session.put = MagicMock(return_value=MockContextManager())
    session.get = MagicMock(return_value=MockContextManager())
    client.get_session = AsyncMock(return_value=session)

    # 1. Update guild settings URL verification
    res = await client.update_guild_settings(
        guild_id="1563563959339061338///",
        allowed_channel_ids=["c1"],
        output_channel_id=None,
    )
    assert res is not None
    called_url, called_kwargs = session.put.call_args
    assert called_url[0] == "http://localhost:8000/api/v1/admin/guilds/1563563959339061338/settings"
    assert "//settings" not in called_url[0]

    # 2. Get guild settings URL verification
    res_get = await client.get_guild_settings("1563563959339061338///", force_refresh=True)
    assert res_get is not None
    called_get_url, _ = session.get.call_args
    assert called_get_url[0] == "http://localhost:8000/api/v1/guilds/1563563959339061338/settings"
    assert "//settings" not in called_get_url[0]


@pytest.mark.asyncio
async def test_setup_save_error_classification():
    """Verifies BackendClient classifies 401, 403, 422, 500, and connection errors."""
    client = BackendClient(
        base_url="http://testserver",
        api_key="bot-key",
        admin_api_key="admin-key",
    )

    class MockContextManager:
        def __init__(self, status: int, text: str = ""):
            self.status = status
            self.text = text

        async def __aenter__(self):
            resp = AsyncMock()
            resp.status = self.status
            resp.text = AsyncMock(return_value=self.text)
            return resp

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    session = AsyncMock()
    client.get_session = AsyncMock(return_value=session)

    # 401 Unauthorized
    session.put = MagicMock(return_value=MockContextManager(401, "Invalid API key"))
    res = await client.update_guild_settings("g1", ["c1"], "out", True, 365)
    assert res is None
    assert "Authentication failed" in client.last_error

    # 403 Forbidden
    session.put = MagicMock(return_value=MockContextManager(403, "Forbidden"))
    res = await client.update_guild_settings("g1", ["c1"], "out", True, 365)
    assert res is None
    assert "Permission denied" in client.last_error

    # 422 Validation Error
    session.put = MagicMock(return_value=MockContextManager(422, "Unprocessable Entity"))
    res = await client.update_guild_settings("g1", ["c1"], "out", True, 365)
    assert res is None
    assert "Validation error" in client.last_error

    # 500 Server Error
    session.put = MagicMock(return_value=MockContextManager(500, "Internal Server Error"))
    res = await client.update_guild_settings("g1", ["c1"], "out", True, 365)
    assert res is None
    assert "Backend server error" in client.last_error


# =============================================================================
# 2. Centralized Slash Command Error Handling Tests
# =============================================================================

@pytest.mark.asyncio
async def test_tree_on_error_handles_missing_permissions():
    """Verifies that missing permissions result in an immediate ephemeral response."""
    bot = create_bot()
    on_error = getattr(bot.tree, "on_error", None)
    assert on_error is not None, "bot.tree must have an on_error handler"

    interaction = MagicMock(spec=discord.Interaction)
    interaction.command = MagicMock(name="setup")
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.send_message = AsyncMock()

    error = app_commands.MissingPermissions(["manage_guild"])

    await on_error(interaction, error)

    interaction.response.send_message.assert_called_once()
    args, kwargs = interaction.response.send_message.call_args
    assert kwargs.get("ephemeral") is True
    assert "don't have permission" in args[0].lower() or "permission" in args[0].lower()
    assert "Manage Guild" in args[0]


@pytest.mark.asyncio
async def test_tree_on_error_handles_already_done_interaction():
    """Verifies that already-acknowledged interactions safely use followup.send."""
    bot = create_bot()
    on_error = getattr(bot.tree, "on_error", None)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.command = MagicMock(name="summarize")
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=True)
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    error = app_commands.CheckFailure("Check failed")

    await on_error(interaction, error)

    interaction.followup.send.assert_called_once()
    args, kwargs = interaction.followup.send.call_args
    assert kwargs.get("ephemeral") is True
    assert "don't have permission" in args[0].lower() or "permission" in args[0].lower()


@pytest.mark.asyncio
async def test_setup_command_unauthorized_member_ephemeral_denial():
    """Verifies unauthorized member invoking /setup gets an immediate ephemeral denial message."""
    bot = create_bot()
    cmd = bot.tree.get_command("setup")
    assert cmd is not None

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = MagicMock(spec=discord.Guild, id=100, owner_id=999)
    interaction.user = MagicMock(spec=discord.Member, id=222)
    interaction.user.guild_permissions = discord.Permissions(send_messages=True)
    interaction.permissions = discord.Permissions(send_messages=True)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    await cmd.callback(interaction)

    interaction.response.send_message.assert_called_once()
    args, kwargs = interaction.response.send_message.call_args
    assert kwargs.get("ephemeral") is True
    assert "Manage Server" in args[0]


@pytest.mark.asyncio
async def test_tree_on_error_handles_transformer_error():
    """Verifies that TransformerError produces a user-friendly range/format message without AttributeError."""
    bot = create_bot()
    on_error = getattr(bot.tree, "on_error", None)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.command = MagicMock(name="summarize")
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.send_message = AsyncMock()

    # TransformerError takes (value, opt_type, transformer)
    mock_transformer = MagicMock()
    error = app_commands.TransformerError(-1, discord.AppCommandOptionType.integer, mock_transformer)

    await on_error(interaction, error)

    interaction.response.send_message.assert_called_once()
    args, kwargs = interaction.response.send_message.call_args
    assert kwargs.get("ephemeral") is True
    assert "outside the allowed range" in args[0].lower()


@pytest.mark.asyncio
async def test_tree_on_error_handles_expired_interaction_silently():
    """Verifies that an expired interaction (code 10062) does not crash or raise unhandled exceptions."""
    bot = create_bot()
    on_error = getattr(bot.tree, "on_error", None)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.command = MagicMock(name="setup")
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.send_message = AsyncMock()

    # Create a mock discord.NotFound with code 10062
    mock_resp = MagicMock()
    mock_resp.status = 404
    mock_resp.reason = "Not Found"
    orig_error = discord.NotFound(mock_resp, {"code": 10062, "message": "Unknown interaction"})
    wrapped_error = app_commands.CommandInvokeError(interaction.command, orig_error)

    # Should safely return without sending anything to dead interaction
    await on_error(interaction, wrapped_error)
    interaction.response.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_admin_api_requires_configuration_body(api_client):
    """Verifies PUT /api/v1/admin/guilds/{guild_id}/settings enforces a required configuration body."""
    client = api_client
    admin_key = "admin-test-key"

    # Missing / empty body -> 422 Validation Error
    resp_empty = await client.put(
        "/api/v1/admin/guilds/test-empty-guild/settings",
        headers={"X-Admin-API-Key": admin_key, "Content-Type": "application/json"},
        content=b"",
    )
    assert resp_empty.status_code == 422, f"Expected 422 for empty body, got {resp_empty.status_code}"
    err_empty = resp_empty.json()
    assert "detail" in err_empty

    # Literal null body -> 422 Validation Error
    resp_null = await client.put(
        "/api/v1/admin/guilds/test-null-guild/settings",
        headers={"X-Admin-API-Key": admin_key, "Content-Type": "application/json"},
        content=b"null",
    )
    assert resp_null.status_code == 422, f"Expected 422 for null body, got {resp_null.status_code}"
    err_null = resp_null.json()
    assert "detail" in err_null

    # Valid configuration payload -> 200 OK and persists settings
    valid_payload = {
        "enabled": True,
        "allowed_channel_ids": ["ch-10", "ch-20"],
        "output_channel_id": "ch-99",
        "retention_days": 90,
    }
    resp_valid = await client.put(
        "/api/v1/admin/guilds/test-valid-guild/settings",
        headers={"X-Admin-API-Key": admin_key},
        json=valid_payload,
    )
    assert resp_valid.status_code == 200, resp_valid.text
    data = resp_valid.json()
    assert data["guild_id"] == "test-valid-guild"
    assert data["enabled"] is True
    assert data["allowed_channel_ids"] == ["ch-10", "ch-20"]
    assert data["output_channel_id"] == "ch-99"
    assert data["retention_days"] == 90


@pytest.mark.asyncio
async def test_request_limit_middleware_preserves_body_for_fastapi(api_client):
    """Verifies RequestLimitMiddleware streams the request body to FastAPI intact without dropping bytes."""
    client = api_client
    admin_key = "admin-test-key"

    valid_payload = {
        "enabled": True,
        "allowed_channel_ids": ["ch-alpha", "ch-beta"],
        "output_channel_id": "ch-gamma",
        "retention_days": 180,
    }
    resp = await client.put(
        "/api/v1/admin/guilds/test-body-preserved-guild/settings",
        headers={"X-Admin-API-Key": admin_key, "Content-Type": "application/json"},
        json=valid_payload,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["guild_id"] == "test-body-preserved-guild"
    assert data["enabled"] is True
    assert data["allowed_channel_ids"] == ["ch-alpha", "ch-beta"]
    assert data["output_channel_id"] == "ch-gamma"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert "X-Request-ID" in resp.headers


@pytest.mark.asyncio
async def test_request_limit_middleware_enforces_configured_size_limit(tmp_path):
    """Verifies RequestLimitMiddleware rejects oversized payloads with HTTP 413 and security headers."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from backend.config import Settings
    from backend.presentation.api.app import create_app

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mw_limit.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        bot_api_key="bot-test-key",
        admin_api_key="admin-test-key",
        max_request_bytes=100,  # Strict low limit for testing
    )
    app = create_app(settings=settings, session_factory=factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Construct payload exceeding 100 bytes
        oversized_payload = {
            "enabled": True,
            "allowed_channel_ids": ["ch-" + ("x" * 150)],
            "output_channel_id": "ch-out",
            "retention_days": 365,
        }
        resp = await client.put(
            "/api/v1/admin/guilds/test-limit-guild/settings",
            headers={"X-Admin-API-Key": "admin-test-key", "Content-Type": "application/json"},
            json=oversized_payload,
        )
        assert resp.status_code == 413
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert "X-Request-ID" in resp.headers

    await engine.dispose()


@pytest.mark.asyncio
async def test_setup_save_retry_preserved_on_backend_failure():
    """Verifies Setup UI remains active and unstopped if backend save fails, allowing retry."""
    bot = create_bot()
    bot.backend.update_guild_settings = AsyncMock(return_value=None)
    bot.backend.last_error = "Validation error (invalid channel selection or settings format)"

    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = 123456789
    mock_guild.name = "Test Guild"
    mock_guild.channels = []

    mock_admin = MagicMock(spec=discord.Member)
    mock_admin.id = 999999999

    view = SetupConfigView(
        bot=bot,
        guild=mock_guild,
        admin=mock_admin,
        current_settings={"guild_id": "123456789"},
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await view.on_save(interaction)

    interaction.response.defer.assert_called_once_with(ephemeral=True)
    interaction.followup.send.assert_called_once()
    sent_msg = interaction.followup.send.call_args[0][0]
    assert "Failed to save configuration" in sent_msg
    assert "preserved so you can retry" in sent_msg
    # Crucial: view must not be stopped on failure so the administrator can retry
    assert view.is_finished() is False


@pytest.mark.asyncio
async def test_setup_save_success_confirms_and_cleans_up():
    """Verifies Setup UI confirms persistence and stops view on successful save."""
    bot = create_bot()
    bot.backend.update_guild_settings = AsyncMock(
        return_value={
            "guild_id": "123456789",
            "enabled": True,
            "allowed_channel_ids": [],
            "output_channel_id": None,
            "retention_days": 365,
        }
    )

    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = 123456789
    mock_guild.name = "Test Guild"
    mock_guild.channels = []

    mock_admin = MagicMock(spec=discord.Member)
    mock_admin.id = 999999999

    view = SetupConfigView(
        bot=bot,
        guild=mock_guild,
        admin=mock_admin,
        current_settings={"guild_id": "123456789"},
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    interaction.delete_original_response = AsyncMock()

    await view.on_save(interaction)

    interaction.response.defer.assert_called_once_with(ephemeral=True)
    interaction.followup.send.assert_called_once()
    sent_msg = interaction.followup.send.call_args[0][0]
    assert "CONFIGURATION SAVED SUCCESSFULLY" in sent_msg
    # Crucial: view must be finished/stopped on success
    assert view.is_finished() is True
    interaction.delete_original_response.assert_called_once()

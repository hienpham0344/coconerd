import os
from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
import discord
import httpx
import pytest
from pydantic import SecretStr

from backend.config import Settings
from backend.presentation.api.app import create_app
from bot.main import SetupConfigView, create_bot


@pytest.fixture
def test_settings():
    db_file = Path("./data/test_m1_2_1_sec.db")
    if db_file.exists():
        db_file.unlink()
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{db_file}",
        bot_api_key=SecretStr("test-bot-secret-key-123"),
        admin_api_key=SecretStr("test-admin-secret-key-456"),
    )
    yield settings
    for suffix in ("", "-wal", "-shm"):
        f = Path(f"./data/test_m1_2_1_sec.db{suffix}")
        if f.exists():
            try:
                f.unlink()
            except OSError:
                pass


@pytest.fixture
async def api_client(test_settings):
    app = create_app(test_settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, test_settings


# =============================================================================
# Task A Verification: Prevent Admin API Key Exposure in Dashboard HTML
# =============================================================================

@pytest.mark.asyncio
async def test_dashboard_html_does_not_expose_admin_key(api_client):
    client, settings = api_client
    admin_key_raw = settings.admin_api_key.get_secret_value()

    # 1. Normal GET request
    resp = await client.get("/setup/test-guild-001")
    assert resp.status_code == 200
    html = resp.text

    # The actual secret key must NOT appear anywhere in the rendered HTML
    assert admin_key_raw not in html

    # The password input must have value=""
    assert 'id="adminKey" name="admin_key" value=""' in html
    assert 'type="password"' in html

    # 2. GET request with query param attempt to inject
    resp_param = await client.get("/setup/test-guild-001?admin_key=attempted_query_key")
    assert resp_param.status_code == 200
    assert "attempted_query_key" not in resp_param.text
    assert 'id="adminKey" name="admin_key" value=""' in resp_param.text


@pytest.mark.asyncio
async def test_admin_settings_endpoint_authentication(api_client):
    client, settings = api_client
    admin_key_raw = settings.admin_api_key.get_secret_value()

    payload = {
        "enabled": True,
        "allowed_channel_ids": ["ch-1", "ch-2"],
        "output_channel_id": "ch-out",
        "retention_days": 180,
    }

    # 1. Reject invalid admin key
    resp_bad = await client.put(
        "/api/v1/admin/guilds/test-guild-001/settings",
        headers={"X-Admin-API-Key": "wrong-key"},
        json=payload,
    )
    assert resp_bad.status_code == 401

    # 2. Reject missing admin key
    resp_missing = await client.put(
        "/api/v1/admin/guilds/test-guild-001/settings",
        json=payload,
    )
    assert resp_missing.status_code == 401

    # 3. Accept valid admin key
    resp_ok = await client.put(
        "/api/v1/admin/guilds/test-guild-001/settings",
        headers={"X-Admin-API-Key": admin_key_raw},
        json=payload,
    )
    assert resp_ok.status_code == 200, resp_ok.text
    data = resp_ok.json()
    assert data["guild_id"] == "test-guild-001"
    assert data["allowed_channel_ids"] == ["ch-1", "ch-2"]
    assert data["output_channel_id"] == "ch-out"


@pytest.mark.asyncio
async def test_dashboard_form_post_fallback_authentication(api_client):
    client, settings = api_client
    admin_key_raw = settings.admin_api_key.get_secret_value()

    form_payload_invalid = "admin_key=wrong&enabled=true&allowed_channels=c1,c2&output_channel=c3"
    resp_invalid = await client.post(
        "/setup/test-guild-001",
        content=form_payload_invalid.encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp_invalid.status_code == 401

    form_payload_valid = f"admin_key={admin_key_raw}&enabled=true&allowed_channels=c1,c2&output_channel=c3"
    resp_valid = await client.post(
        "/setup/test-guild-001",
        content=form_payload_valid.encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp_valid.status_code == 200, resp_valid.text
    assert "đã lưu thành công" in resp_valid.text


# =============================================================================
# Task B Verification: Restrict /setup to Server Administrators
# =============================================================================

@pytest.mark.asyncio
async def test_setup_slash_command_permissions():
    bot = create_bot()
    cmd = bot.tree.get_command("setup")
    assert cmd is not None, "Slash command /setup must be registered"

    # Case 1: DM invocation (no guild)
    mock_dm_interaction = MagicMock(spec=discord.Interaction)
    mock_dm_interaction.guild = None
    mock_dm_interaction.response = MagicMock()
    mock_dm_interaction.response.send_message = AsyncMock()

    await cmd.callback(mock_dm_interaction)
    mock_dm_interaction.response.send_message.assert_called_once()
    dm_args, dm_kwargs = mock_dm_interaction.response.send_message.call_args
    assert dm_kwargs.get("ephemeral") is True
    assert "can only be used within a server" in dm_args[0].lower() or "chỉ có thể được sử dụng trong máy chủ Discord" in dm_args[0]
    assert "/setup/" not in dm_args[0]

    # Case 2: Normal member without manage_guild
    mock_member_interaction = MagicMock(spec=discord.Interaction)
    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = 123456789
    mock_guild.name = "Test Discord Server"
    mock_guild.owner_id = 999999999
    mock_member_interaction.guild = mock_guild

    mock_user = MagicMock(spec=discord.Member)
    mock_user.id = 111111111
    mock_user.guild_permissions = discord.Permissions(send_messages=True)
    mock_member_interaction.user = mock_user
    mock_member_interaction.permissions = discord.Permissions(send_messages=True)
    mock_member_interaction.response = MagicMock()
    mock_member_interaction.response.send_message = AsyncMock()

    await cmd.callback(mock_member_interaction)
    mock_member_interaction.response.send_message.assert_called_once()
    mem_args, mem_kwargs = mock_member_interaction.response.send_message.call_args
    assert mem_kwargs.get("ephemeral") is True
    assert "Manage Server" in mem_args[0]
    # Critical: No Dashboard URL must be exposed
    assert "/setup/" not in mem_args[0]

    mock_guild.channels = []
    bot.backend.get_guild_settings = AsyncMock(
        return_value={
            "guild_id": str(mock_guild.id),
            "enabled": False,
            "allowed_channel_ids": [],
            "output_channel_id": None,
            "retention_days": 365,
        }
    )

    # Case 3: Administrator with manage_guild=True
    mock_admin_interaction = MagicMock(spec=discord.Interaction)
    mock_admin_interaction.guild = mock_guild
    mock_admin_user = MagicMock(spec=discord.Member)
    mock_admin_user.id = 222222222
    mock_admin_user.guild_permissions = discord.Permissions(manage_guild=True)
    mock_admin_interaction.user = mock_admin_user
    mock_admin_interaction.permissions = discord.Permissions(manage_guild=True)
    mock_admin_interaction.response = MagicMock()
    mock_admin_interaction.response.is_done = MagicMock(return_value=False)
    mock_admin_interaction.response.defer = AsyncMock()
    mock_admin_interaction.followup = MagicMock()
    mock_admin_interaction.followup.send = AsyncMock()

    await cmd.callback(mock_admin_interaction)
    mock_admin_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_admin_interaction.followup.send.assert_called_once()
    _, admin_kwargs = mock_admin_interaction.followup.send.call_args
    assert admin_kwargs.get("ephemeral") is True
    assert isinstance(admin_kwargs.get("view"), SetupConfigView)
    assert isinstance(admin_kwargs.get("embed"), discord.Embed)
    assert "Coconerd Setup" in admin_kwargs["embed"].title or "Cài đặt Coconerd" in admin_kwargs["embed"].title
    assert "/setup/" not in (admin_kwargs.get("content") or "")

    # Case 4: Server Owner (owner_id matches user.id)
    mock_owner_interaction = MagicMock(spec=discord.Interaction)
    mock_owner_interaction.guild = mock_guild
    mock_owner_user = MagicMock(spec=discord.Member)
    mock_owner_user.id = mock_guild.owner_id
    mock_owner_user.guild_permissions = discord.Permissions.none()
    mock_owner_interaction.user = mock_owner_user
    mock_owner_interaction.permissions = discord.Permissions.none()
    mock_owner_interaction.response = MagicMock()
    mock_owner_interaction.response.is_done = MagicMock(return_value=False)
    mock_owner_interaction.response.defer = AsyncMock()
    mock_owner_interaction.followup = MagicMock()
    mock_owner_interaction.followup.send = AsyncMock()

    await cmd.callback(mock_owner_interaction)
    mock_owner_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_owner_interaction.followup.send.assert_called_once()
    _, owner_kwargs = mock_owner_interaction.followup.send.call_args
    assert owner_kwargs.get("ephemeral") is True
    assert isinstance(owner_kwargs.get("view"), SetupConfigView)
    assert isinstance(owner_kwargs.get("embed"), discord.Embed)
    assert "Coconerd Setup" in owner_kwargs["embed"].title or "Cài đặt Coconerd" in owner_kwargs["embed"].title
    assert "/setup/" not in (owner_kwargs.get("content") or "")


# =============================================================================
# Task C & Regression Verification: Channel Configuration Invariants
# =============================================================================

@pytest.mark.asyncio
async def test_channel_configuration_invariants(api_client):
    client, settings = api_client
    admin_key_raw = settings.admin_api_key.get_secret_value()
    bot_key_raw = settings.bot_api_key.get_secret_value()

    # 1. Update settings with multiple input channels and one output channel
    payload = {
        "enabled": True,
        "allowed_channel_ids": ["input-1", "input-2", "input-3"],
        "output_channel_id": "output-only",
        "retention_days": 365,
    }
    put_resp = await client.put(
        "/api/v1/admin/guilds/guild-regression/settings",
        headers={"X-Admin-API-Key": admin_key_raw},
        json=payload,
    )
    assert put_resp.status_code == 200, put_resp.text

    # 2. Verify Bot settings endpoint returns updated configuration
    bot_resp = await client.get(
        "/api/v1/guilds/guild-regression/settings",
        headers={"X-API-Key": bot_key_raw},
    )
    assert bot_resp.status_code == 200
    bot_data = bot_resp.json()
    assert bot_data["enabled"] is True
    assert bot_data["allowed_channel_ids"] == ["input-1", "input-2", "input-3"]
    assert bot_data["output_channel_id"] == "output-only"
    assert "output-only" not in bot_data["allowed_channel_ids"]


# =============================================================================
# Native Discord Setup UI & Bot Settings Verification
# =============================================================================

@pytest.mark.asyncio
async def test_bot_put_guild_settings_endpoint(api_client):
    client, settings = api_client
    bot_key_raw = settings.bot_api_key.get_secret_value()

    payload = {
        "enabled": True,
        "allowed_channel_ids": ["ch-bot-1", "ch-bot-2"],
        "output_channel_id": "ch-bot-out",
        "retention_days": 180,
    }

    # 1. Reject invalid bot key
    resp_bad = await client.put(
        "/api/v1/guilds/test-guild-bot/settings",
        headers={"X-API-Key": "wrong-key"},
        json=payload,
    )
    assert resp_bad.status_code == 401

    # 2. Reject missing bot key
    resp_missing = await client.put(
        "/api/v1/guilds/test-guild-bot/settings",
        json=payload,
    )
    assert resp_missing.status_code == 401

    # 3. Accept valid bot key
    resp_ok = await client.put(
        "/api/v1/guilds/test-guild-bot/settings",
        headers={"X-API-Key": bot_key_raw},
        json=payload,
    )
    assert resp_ok.status_code == 200, resp_ok.text
    data = resp_ok.json()
    assert data["guild_id"] == "test-guild-bot"
    assert data["allowed_channel_ids"] == ["ch-bot-1", "ch-bot-2"]
    assert data["output_channel_id"] == "ch-bot-out"

    # 4. GET verifies the updated settings
    resp_get = await client.get(
        "/api/v1/guilds/test-guild-bot/settings",
        headers={"X-API-Key": bot_key_raw},
    )
    assert resp_get.status_code == 200
    assert resp_get.json()["allowed_channel_ids"] == ["ch-bot-1", "ch-bot-2"]


@pytest.mark.asyncio
async def test_setup_config_view_behavior():
    bot = create_bot()

    # Create mock guild with 30 text channels
    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = 123456789
    mock_guild.name = "Big Test Guild"
    mock_guild.owner_id = 999999999

    channels = []
    for i in range(1, 31):
        ch = MagicMock(spec=discord.TextChannel)
        ch.id = 1000 + i
        ch.name = f"channel-{i}"
        ch.type = discord.ChannelType.text
        channels.append(ch)
    mock_guild.channels = channels

    mock_admin = MagicMock(spec=discord.Member)
    mock_admin.id = 222222222
    mock_admin.guild_permissions = discord.Permissions(manage_guild=True)

    # 1. Test initialization with >25 channels (limit handling)
    current_settings = {
        "guild_id": "123456789",
        "enabled": True,
        "allowed_channel_ids": [str(c.id) for c in channels],
        "output_channel_id": str(channels[0].id),
        "retention_days": 365,
    }
    view = SetupConfigView(
        bot=bot,
        guild=mock_guild,
        admin=mock_admin,
        current_settings=current_settings,
    )

    # ChannelSelect default_values max is 25
    assert len(view.input_select.default_values) == 25
    assert len(view.selected_input_ids) == 30
    assert view.selected_output_id == str(channels[0].id)

    # Embed should display warning for >25 channels
    embed = view.build_embed()
    field_names = [f.name for f in embed.fields]
    assert any("Channel Selection Limit" in name or "Giới hạn menu chọn" in name for name in field_names)

    # 2. Test interaction_check: non-admin or different user is rejected
    mock_intruder = MagicMock(spec=discord.Member)
    mock_intruder.id = 888888888
    mock_intruder_interaction = MagicMock(spec=discord.Interaction)
    mock_intruder_interaction.guild = mock_guild
    mock_intruder_interaction.user = mock_intruder
    mock_intruder_interaction.permissions = discord.Permissions(send_messages=True)
    mock_intruder_interaction.response = MagicMock()
    mock_intruder_interaction.response.send_message = AsyncMock()

    allowed = await view.interaction_check(mock_intruder_interaction)
    assert allowed is False
    mock_intruder_interaction.response.send_message.assert_called_once()

    # 3. Test on_cancel
    mock_cancel_interaction = MagicMock(spec=discord.Interaction)
    mock_cancel_interaction.guild = mock_guild
    mock_cancel_interaction.user = mock_admin
    mock_cancel_interaction.response = MagicMock()
    mock_cancel_interaction.response.send_message = AsyncMock()
    mock_cancel_interaction.delete_original_response = AsyncMock()

    await view.on_cancel(mock_cancel_interaction)
    assert view.is_finished()
    mock_cancel_interaction.response.send_message.assert_called_once()
    cancel_reply = mock_cancel_interaction.response.send_message.call_args[0][0]
    assert "cancelled" in cancel_reply.lower() or "đã hủy" in cancel_reply.lower()

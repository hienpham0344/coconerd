from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.main import SetupConfigView, create_bot


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
    assert (
        "can only be used within a server" in dm_args[0].lower()
        or "chỉ có thể được sử dụng trong máy chủ Discord" in dm_args[0]
    )
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
    assert (
        "Coconerd Setup" in admin_kwargs["embed"].title
        or "Cài đặt Coconerd" in admin_kwargs["embed"].title
    )
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
    assert (
        "Coconerd Setup" in owner_kwargs["embed"].title
        or "Cài đặt Coconerd" in owner_kwargs["embed"].title
    )
    assert "/setup/" not in (owner_kwargs.get("content") or "")


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
    assert any(
        "Channel Selection Limit" in name or "Giới hạn menu chọn" in name for name in field_names
    )

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

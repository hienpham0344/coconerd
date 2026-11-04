import os
from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from unittest.mock import AsyncMock, MagicMock
import discord
import pytest

from bot.main import (
    build_help_embed,
    build_welcome_embed,
    create_bot,
    find_welcome_channel,
    get_command_descriptions,
)


@pytest.mark.asyncio
async def test_help_slash_command_registration_and_execution():
    """Verifies that /help is registered, accessible to regular users, and returns a detailed ephemeral embed."""
    bot = create_bot()
    cmd = bot.tree.get_command("help")
    assert cmd is not None, "Slash command /help must be registered in bot.tree"

    # Regular user without manage_guild or administrator permissions
    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = 123456789
    mock_guild.name = "Community Server"

    mock_user = MagicMock(spec=discord.Member)
    mock_user.id = 999999
    mock_user.guild_permissions = discord.Permissions(send_messages=True)

    mock_interaction = MagicMock(spec=discord.Interaction)
    mock_interaction.guild = mock_guild
    mock_interaction.user = mock_user
    mock_interaction.permissions = discord.Permissions(send_messages=True)
    mock_interaction.response = MagicMock()
    mock_interaction.response.send_message = AsyncMock()

    # Invoke /help callback
    await cmd.callback(mock_interaction)

    mock_interaction.response.send_message.assert_called_once()
    _, kwargs = mock_interaction.response.send_message.call_args
    assert kwargs.get("ephemeral") is True, "/help must send an ephemeral response to avoid channel clutter"

    embed = kwargs.get("embed")
    assert isinstance(embed, discord.Embed), "/help must return a discord.Embed"
    assert "Coconerd" in embed.title

    # Verify all required architectural concepts are explained
    field_names = [f.name for f in embed.fields]
    field_values = "\n".join(f.value for f in embed.fields)

    # 1. Basic workflow
    assert any("Workflow" in name or "Luồng hoạt động" in name for name in field_names)
    assert "Topics" in field_values

    # 2. Distinction between Input Channels and Output Channel
    assert any("Input" in name and "Output" in name for name in field_names)
    assert "only reads" in field_values.lower() or "chỉ đọc" in field_values.lower()

    # 3. Channel isolation invariant
    assert any("độc lập" in name or "Channel Isolation" in name for name in field_names)
    assert "never" in field_values.lower() or "không bao giờ" in field_values.lower()

    # 4. Dynamic commands list
    assert any("lệnh" in name.lower() or "commands" in name.lower() for name in field_names)
    assert "/help" in field_values
    assert "/setup" in field_values
    assert "/summarize" in field_values
    assert "/ping" in field_values


def test_get_command_descriptions_dynamic():
    """Verifies that get_command_descriptions dynamically lists registered commands with clear descriptions."""
    bot = create_bot()
    commands_info = get_command_descriptions(bot)
    cmd_dict = dict(commands_info)

    assert "/help" in cmd_dict
    assert "/setup" in cmd_dict
    assert "/summarize" in cmd_dict
    assert "/ping" in cmd_dict

    # Verify /setup notes Manage Server requirement
    setup_desc = cmd_dict.get("/setup", cmd_dict.get("setup", ""))
    assert "Manage Server" in setup_desc


def test_find_welcome_channel_system_channel_priority():
    """Verifies that guild.system_channel is preferred when bot has sufficient permissions."""
    mock_guild = MagicMock(spec=discord.Guild)
    mock_sys_channel = MagicMock(spec=discord.TextChannel)
    mock_sys_channel.name = "general-system"

    # Bot member has permissions
    mock_bot_member = MagicMock(spec=discord.Member)
    mock_guild.me = mock_bot_member

    # sys_channel perms: send_messages=True, embed_links=True
    sys_perms = MagicMock()
    sys_perms.send_messages = True
    sys_perms.embed_links = True
    mock_sys_channel.permissions_for.return_value = sys_perms

    mock_guild.system_channel = mock_sys_channel

    selected = find_welcome_channel(mock_guild)
    assert selected == mock_sys_channel


def test_find_welcome_channel_fallback_to_first_permitted_channel():
    """Verifies fallback to first text channel with permissions when system_channel is None or lacks permissions."""
    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.system_channel = None

    mock_bot_member = MagicMock(spec=discord.Member)
    mock_guild.me = mock_bot_member

    # Channel 1: lacks embed_links
    ch1 = MagicMock(spec=discord.TextChannel)
    ch1.name = "announcements"
    perms1 = MagicMock(send_messages=True, embed_links=False)
    ch1.permissions_for.return_value = perms1

    # Channel 2: has both permissions
    ch2 = MagicMock(spec=discord.TextChannel)
    ch2.name = "chat"
    perms2 = MagicMock(send_messages=True, embed_links=True)
    ch2.permissions_for.return_value = perms2

    mock_guild.text_channels = [ch1, ch2]

    selected = find_welcome_channel(mock_guild)
    assert selected == ch2


def test_find_welcome_channel_returns_none_when_no_permissions():
    """Verifies that None is returned safely when no text channel has send/embed permissions."""
    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.system_channel = None

    mock_bot_member = MagicMock(spec=discord.Member)
    mock_guild.me = mock_bot_member

    ch1 = MagicMock(spec=discord.TextChannel)
    perms1 = MagicMock(send_messages=False, embed_links=False)
    ch1.permissions_for.return_value = perms1

    mock_guild.text_channels = [ch1]

    selected = find_welcome_channel(mock_guild)
    assert selected is None


@pytest.mark.asyncio
async def test_on_guild_join_welcome_flow():
    """Verifies on_guild_join event syncs commands and sends the structured welcome embed to suitable channel."""
    bot = create_bot()

    # Inspect the actual registered event handler on bot
    guild_join_handler = getattr(bot, "on_guild_join", None)
    assert guild_join_handler is not None, "on_guild_join event handler must be registered on bot"

    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = 777888999
    mock_guild.name = "Awesome New Guild"

    mock_channel = MagicMock(spec=discord.TextChannel)
    mock_channel.name = "welcome-room"
    mock_channel.send = AsyncMock()

    perms = MagicMock(send_messages=True, embed_links=True)
    mock_channel.permissions_for.return_value = perms
    mock_guild.system_channel = mock_channel
    mock_guild.me = MagicMock(spec=discord.Member)

    # Mock bot.tree.sync and copy_global_to
    bot.tree.copy_global_to = MagicMock()
    bot.tree.sync = AsyncMock(return_value=[])

    # Trigger on_guild_join
    await guild_join_handler(mock_guild)

    # 1. Guild commands synced
    bot.tree.copy_global_to.assert_called_once()
    bot.tree.sync.assert_called_once()

    # 2. Welcome message sent
    mock_channel.send.assert_called_once()
    _, send_kwargs = mock_channel.send.call_args
    welcome_embed = send_kwargs.get("embed")
    assert isinstance(welcome_embed, discord.Embed)
    assert "Awesome New Guild" in welcome_embed.description
    assert any("How to get started" in f.name or "bắt đầu" in f.name for f in welcome_embed.fields)
    cmd_field = next(
        (f for f in welcome_embed.fields if "available commands" in f.name.lower() or "lệnh" in f.name.lower()),
        None,
    )
    assert cmd_field is not None, "Welcome embed must contain an 'Available Commands' section"
    assert "/setup" in cmd_field.value
    assert "Manage Server" in cmd_field.value
    assert "/help" in cmd_field.value
    assert any("Need help later" in f.name or "help" in f.name.lower() or "trợ giúp" in f.name.lower() for f in welcome_embed.fields)


@pytest.mark.asyncio
async def test_on_guild_join_handles_missing_channel_safely():
    """Verifies on_guild_join exits gracefully without crashing when no channel has permissions."""
    bot = create_bot()
    guild_join_handler = getattr(bot, "on_guild_join", None)
    assert guild_join_handler is not None, "on_guild_join event handler must be registered on bot"

    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = 111222333
    mock_guild.name = "Locked Guild"
    mock_guild.system_channel = None
    mock_guild.text_channels = []
    mock_guild.me = MagicMock()

    bot.tree.copy_global_to = MagicMock()
    bot.tree.sync = AsyncMock(return_value=[])

    # Must complete cleanly without raising exception
    await guild_join_handler(mock_guild)


@pytest.mark.asyncio
async def test_on_guild_join_handles_forbidden_error_safely():
    """Verifies on_guild_join catches discord.errors.Forbidden without propagating exception."""
    bot = create_bot()
    guild_join_handler = getattr(bot, "on_guild_join", None)
    assert guild_join_handler is not None, "on_guild_join event handler must be registered on bot"

    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = 444555666
    mock_guild.name = "Forbidden Guild"

    mock_channel = MagicMock(spec=discord.TextChannel)
    mock_channel.name = "general"
    # Simulate Forbidden on send
    mock_response = MagicMock()
    mock_response.status = 403
    mock_response.reason = "Forbidden"
    mock_channel.send = AsyncMock(side_effect=discord.errors.Forbidden(mock_response, "Missing Permissions"))

    perms = MagicMock(send_messages=True, embed_links=True)
    mock_channel.permissions_for.return_value = perms
    mock_guild.system_channel = mock_channel
    mock_guild.me = MagicMock()

    bot.tree.copy_global_to = MagicMock()
    bot.tree.sync = AsyncMock(return_value=[])

    # Must catch Forbidden gracefully without crash
    await guild_join_handler(mock_guild)

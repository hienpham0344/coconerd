"""Discord Bot connection, personality interaction, Meta AI, and Backend API integration."""

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import quote

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# Make the shared task package available for both module and direct-script entrypoints.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure compatibility whether run as a module or direct script
try:
    from bot.ai import clean_mention_text, generate_ai_reply
    from bot.delivery import DeliveryError
    from bot.media import attachment_payloads
    from bot.outbox import process_outbox_actions
    from bot.personality import get_random_greeting, get_random_reply
except ImportError:
    from ai import clean_mention_text, generate_ai_reply
    from delivery import DeliveryError
    from media import attachment_payloads
    from outbox import process_outbox_actions
    from personality import get_random_greeting, get_random_reply

# Ensure UTF-8 output on Windows terminals for clean banner display
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

# Resolve project root reliably so .env is loaded regardless of current working directory
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=ENV_PATH)


def get_token() -> str:
    """Safely retrieves and validates the Discord Bot Token from environment variables."""
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token or not token.strip():
        print("❌ Lỗi cấu hình: Không tìm thấy DISCORD_BOT_TOKEN trong file .env.")
        print("👉 Vui lòng kiểm tra file .env tại thư mục gốc và điền Token của Bot.")
        sys.exit(1)

    placeholder_values = {
        "your_discord_bot_token",
        "your_bot_token_here",
        "replace_with_token",
    }
    if token.strip().lower() in placeholder_values:
        print("❌ Lỗi cấu hình: DISCORD_BOT_TOKEN vẫn đang là giá trị mẫu (placeholder).")
        print("👉 Vui lòng thay thế bằng Token thật lấy từ Discord Developer Portal.")
        sys.exit(1)

    return token.strip()


def get_channel_id() -> int | None:
    """Retrieves and parses DISCORD_CHANNEL_ID from environment variables."""
    raw = os.getenv("DISCORD_CHANNEL_ID")
    if not raw or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def get_guild_id() -> int | None:
    """Retrieves and parses DISCORD_GUILD_ID from environment variables."""
    raw = os.getenv("DISCORD_GUILD_ID")
    if not raw or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def get_application_id() -> int | None:
    """Retrieves and parses DISCORD_APPLICATION_ID from environment variables."""
    raw = os.getenv("DISCORD_APPLICATION_ID")
    if not raw or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def get_backend_url() -> str:
    """Retrieves backend API base URL."""
    return os.getenv("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/")


def get_bot_api_key() -> str:
    """Retrieves bot API key for Backend API authentication."""
    return (
        os.getenv("COCONERD_BOT_API_KEY")
        or os.getenv("BACKEND_API_KEY")
        or "dev-bot-key"
    )


def get_admin_api_key() -> str:
    """Retrieves admin API key for Backend Admin API operations."""
    return (
        os.getenv("COCONERD_ADMIN_API_KEY")
        or os.getenv("ADMIN_API_KEY")
        or ""
    )


def get_dashboard_url() -> str:
    """Retrieves Dashboard base URL."""
    return (
        os.getenv("DASHBOARD_BASE_URL")
        or os.getenv("BACKEND_BASE_URL")
        or "http://localhost:8000"
    ).rstrip("/")


class BackendClient:
    """HTTP Client for communicating with the Coconerd Backend API."""

    def __init__(self, base_url: str, api_key: str, admin_api_key: str | None = None):
        self.base_url = str(base_url).rstrip("/")
        self.api_key = api_key
        self.admin_api_key = admin_api_key or get_admin_api_key()
        self._session: aiohttp.ClientSession | None = None
        self._settings_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._cache_ttl = 30.0  # seconds
        self.last_error: str | None = None
        self._action_leases: dict[str, str] = {}

    def _normalize_snowflake(self, snowflake_id: Any) -> str:
        """Normalizes a Discord snowflake/identifier string safely stripping whitespace and slashes."""
        return str(snowflake_id).strip().strip("/")

    def _build_url(self, path: str) -> str:
        """Safely joins base_url with path, ensuring single leading slash on path and no duplicate slashes."""
        clean_base = str(self.base_url).rstrip("/")
        clean_path = path.lstrip("/")
        return f"{clean_base}/{clean_path}"

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15.0)
            self._session = aiohttp.ClientSession(
                headers={"X-API-Key": self.api_key},
                timeout=timeout,
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_guild_settings(self, guild_id: str, force_refresh: bool = False) -> dict[str, Any]:
        clean_guild_id = self._normalize_snowflake(guild_id)
        now = time.monotonic()
        if not force_refresh and clean_guild_id in self._settings_cache:
            ts, data = self._settings_cache[clean_guild_id]
            if now - ts < self._cache_ttl:
                return data

        session = await self.get_session()
        url = self._build_url(f"api/v1/guilds/{clean_guild_id}/settings")
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._settings_cache[clean_guild_id] = (now, data)
                    return data
                if resp.status == 404:
                    default_settings = {
                        "guild_id": clean_guild_id,
                        "enabled": False,
                        "allowed_channel_ids": [],
                        "output_channel_id": None,
                        "retention_days": 365,
                    }
                    self._settings_cache[clean_guild_id] = (now, default_settings)
                    return default_settings
        except Exception as exc:
            # If backend is temporarily unreachable, return cached or disabled fallback
            if clean_guild_id in self._settings_cache:
                return self._settings_cache[clean_guild_id][1]
        return {
            "guild_id": clean_guild_id,
            "enabled": False,
            "allowed_channel_ids": [],
            "output_channel_id": None,
            "retention_days": 365,
        }

    async def update_guild_settings(
        self,
        guild_id: str,
        allowed_channel_ids: list[str],
        output_channel_id: str | None,
        enabled: bool = True,
        retention_days: int = 365,
    ) -> dict[str, Any] | None:
        self.last_error = None
        clean_guild_id = self._normalize_snowflake(guild_id)
        session = await self.get_session()
        payload = {
            "enabled": enabled,
            "allowed_channel_ids": allowed_channel_ids,
            "output_channel_id": output_channel_id,
            "retention_days": retention_days,
        }

        # Resolve Admin API key
        admin_key = self.admin_api_key or get_admin_api_key()

        # Build list of candidate endpoints: prefer Admin endpoint with X-Admin-API-Key, fallback to Bot endpoint
        endpoints: list[tuple[str, dict[str, str], str]] = []
        if admin_key:
            endpoints.append(
                (
                    self._build_url(f"api/v1/admin/guilds/{clean_guild_id}/settings"),
                    {"X-Admin-API-Key": admin_key, "Content-Type": "application/json"},
                    "Admin API",
                )
            )
        else:
            print("⚠️ [SETTINGS] COCONERD_ADMIN_API_KEY is not configured; attempting save with Bot API key.")

        endpoints.append(
            (
                self._build_url(f"api/v1/guilds/{clean_guild_id}/settings"),
                {"X-API-Key": self.api_key, "Content-Type": "application/json"},
                "Bot API",
            )
        )

        last_status = None
        for url, headers, endpoint_label in endpoints:
            try:
                print(f"ℹ️ [SETTINGS] Requesting save to {endpoint_label} at {url} (channels={len(allowed_channel_ids)}, retention={retention_days})")
                async with session.put(url, json=payload, headers=headers) as resp:
                    last_status = resp.status
                    if resp.status == 200:
                        data = await resp.json()
                        now = time.monotonic()
                        self._settings_cache[clean_guild_id] = (now, data)
                        self.last_error = None
                        print(f"✅ [SETTINGS] Guild settings for '{clean_guild_id}' saved successfully via {endpoint_label}.")
                        return data
                    elif resp.status == 404 and endpoint_label == "Admin API":
                        # If admin endpoint route not found, attempt next endpoint
                        print(f"ℹ️ [SETTINGS] {endpoint_label} endpoint 404 Not Found at {url}, trying next endpoint...")
                        continue
                    else:
                        err_txt = await resp.text()
                        if resp.status == 401:
                            self.last_error = f"Authentication failed with {endpoint_label} (invalid or missing API Key)"
                            print(f"❌ [SETTINGS] Authentication failure (HTTP 401) on {endpoint_label}: {err_txt[:100]}")
                        elif resp.status == 403:
                            self.last_error = f"Permission denied by {endpoint_label}"
                            print(f"❌ [SETTINGS] Permission failure (HTTP 403) on {endpoint_label}: {err_txt[:100]}")
                        elif resp.status == 422:
                            self.last_error = "Validation error (invalid channel selection or settings format)"
                            print(f"❌ [SETTINGS] Request validation failure (HTTP 422) on {endpoint_label}: {err_txt[:100]}")
                        elif resp.status >= 500:
                            self.last_error = f"Backend server error (HTTP {resp.status})"
                            print(f"❌ [SETTINGS] Backend server error (HTTP {resp.status}) on {endpoint_label}: {err_txt[:100]}")
                        else:
                            self.last_error = f"Backend rejected request (HTTP {resp.status})"
                            print(f"❌ [SETTINGS] Request rejected (HTTP {resp.status}) on {endpoint_label}: {err_txt[:100]}")
                        return None
            except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as conn_exc:
                self.last_error = "Could not connect to Backend API (connection refused or timeout)"
                print(f"❌ [SETTINGS] Connection failure on {endpoint_label}: {type(conn_exc).__name__} - {conn_exc}")
                return None
            except Exception as exc:
                self.last_error = f"Unexpected client error: {type(exc).__name__}"
                print(f"❌ [SETTINGS] Client exception on {endpoint_label}: {exc}")
                return None

        if self.last_error is None:
            self.last_error = f"Backend rejected request (HTTP {last_status or 404})"
        return None

    async def get_delivery_receipt(self, key: str) -> str | None:
        session = await self.get_session()
        url = self._build_url(f"api/v1/delivery-receipts/{quote(key, safe='')}")
        try:
            async with session.get(url) as response:
                if response.status == 404:
                    return None
                if response.status == 200:
                    data = await response.json()
                    value = data["discord_id"]
                    if isinstance(value, str) and value:
                        return value
                raise DeliveryError(
                    f"Cannot read delivery receipt (HTTP {response.status})", retryable=True
                )
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError) as error:
            raise DeliveryError("Cannot reach delivery receipt storage", retryable=True) from error

    async def put_delivery_receipt(self, key: str, discord_id: str) -> None:
        session = await self.get_session()
        url = self._build_url(f"api/v1/delivery-receipts/{quote(key, safe='')}")
        try:
            async with session.put(url, json={"discord_id": discord_id}) as response:
                if response.status != 200:
                    raise DeliveryError(
                        f"Cannot save delivery receipt (HTTP {response.status})", retryable=True
                    )
        except (aiohttp.ClientError, TimeoutError) as error:
            raise DeliveryError("Cannot reach delivery receipt storage", retryable=True) from error

    async def ingest_message(self, message: discord.Message) -> bool:
        if not message.guild:
            return False

        created_iso = message.created_at.astimezone(timezone.utc).isoformat()
        reply_to = (
            str(message.reference.message_id)
            if message.reference and message.reference.message_id
            else None
        )

        payload = {
            "guild_id": str(message.guild.id),
            "channel_id": str(message.channel.id),
            "message_id": str(message.id),
            "author_id": str(message.author.id),
            "author_name": message.author.display_name,
            "content": message.content,
            "created_at": created_iso,
            "reply_to_message_id": reply_to,
            "attachments": attachment_payloads(message),
        }

        session = await self.get_session()
        url = self._build_url("api/v1/messages")
        try:
            async with session.post(url, json=payload) as resp:
                if resp.status in (200, 202):
                    return True
                elif resp.status == 403:
                    return False
                else:
                    err_txt = await resp.text()
                    print(f"⚠️ [INGEST] Backend trả về mã {resp.status}: {err_txt[:100]}")
                    return False
        except Exception as exc:
            print(f"⚠️ [INGEST] Lỗi kết nối Backend API: {type(exc).__name__}")
            return False

    async def claim_actions(self, worker_id: str, limit: int = 10) -> list[dict[str, Any]]:
        session = await self.get_session()
        url = self._build_url("api/v1/actions/claim")
        try:
            async with session.post(url, json={"worker_id": worker_id, "limit": limit}) as resp:
                if resp.status == 200:
                    actions = await resp.json()
                    self._action_leases = {
                        str(action["action_id"]): action["lease_token"]
                        for action in actions if action.get("lease_token")
                    }
                    return actions
        except Exception:
            pass
        return []

    async def complete_action(
        self,
        action_id: str,
        worker_id: str,
        discord_thread_id: str | None = None,
        discord_message_id: str | None = None,
        *,
        previous_discord_thread_id: str | None = None,
        discord_channel_id: str | None = None,
    ) -> bool:
        session = await self.get_session()
        clean_action_id = str(action_id).strip().strip("/")
        url = self._build_url(f"api/v1/actions/{clean_action_id}/complete")
        payload = {
            "worker_id": worker_id,
            "discord_thread_id": discord_thread_id,
            "discord_message_id": discord_message_id,
            "lease_token": self._action_leases.get(clean_action_id),
        }
        if discord_channel_id is not None:
            payload.update(
                previous_discord_thread_id=previous_discord_thread_id,
                discord_channel_id=discord_channel_id,
            )
        try:
            async with session.post(url, json=payload) as resp:
                return resp.status == 200
        except Exception as exc:
            print(f"⚠️ [ACTION] Lỗi complete action {action_id}: {exc}")
            return False

    async def fail_action(
        self,
        action_id: str,
        worker_id: str,
        error_type: str,
        error_message: str,
        retryable: bool = True,
    ) -> bool:
        session = await self.get_session()
        clean_action_id = str(action_id).strip().strip("/")
        url = self._build_url(f"api/v1/actions/{clean_action_id}/fail")
        payload = {
            "worker_id": worker_id,
            "error_type": error_type,
            "error_message": error_message[:900],
            "retryable": retryable,
            "lease_token": self._action_leases.get(clean_action_id),
        }
        try:
            async with session.post(url, json=payload) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def list_topics(
        self,
        guild_id: str,
        channel_id: str | None = None,
        include_closed: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clean_guild_id = self._normalize_snowflake(guild_id)
        session = await self.get_session()
        url = self._build_url("api/v1/topics")
        params: dict[str, Any] = {"guild_id": clean_guild_id, "limit": limit}
        if channel_id:
            params["channel_id"] = self._normalize_snowflake(channel_id)
        if include_closed:
            params["include_closed"] = "true"
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("items", [])
        except Exception:
            pass
        return []

    async def get_topic_summary(
        self, guild_id: str, topic_id: str, channel_id: str | None = None
    ) -> dict[str, Any] | None:
        clean_guild_id = self._normalize_snowflake(guild_id)
        clean_topic_id = str(topic_id).strip().strip("/")
        session = await self.get_session()
        url = self._build_url(f"api/v1/topics/{clean_topic_id}/summary")
        params: dict[str, Any] = {"guild_id": clean_guild_id}
        if channel_id:
            params["channel_id"] = self._normalize_snowflake(channel_id)
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
        return None

    async def get_topic(self, guild_id: str, topic_id: str) -> dict[str, Any] | None:
        clean_guild_id = self._normalize_snowflake(guild_id)
        clean_topic_id = str(topic_id).strip().strip("/")
        session = await self.get_session()
        url = self._build_url(f"api/v1/topics/{clean_topic_id}")
        params = {"guild_id": clean_guild_id}
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
        return None


    async def get_thread_topic(self, guild_id: str, thread_id: str) -> dict[str, Any] | None:
        session = await self.get_session()
        thread_id = self._normalize_snowflake(thread_id)
        url = self._build_url(f"api/v1/threads/{thread_id}/topic")
        params = {"guild_id": self._normalize_snowflake(guild_id)}
        async with session.get(url, params=params) as response:
            if response.status == 404:
                return None
            if response.status != 200:
                raise RuntimeError(f"Cannot resolve thread topic: HTTP {response.status}")
            return await response.json()

    async def get_topic_messages(
        self,
        guild_id: str,
        topic_id: str,
        limit: int = 50,
        *,
        before: str | None = None,
        require_success: bool = False,
    ) -> list[dict[str, Any]]:
        clean_guild_id = self._normalize_snowflake(guild_id)
        clean_topic_id = str(topic_id).strip().strip("/")
        session = await self.get_session()
        url = self._build_url(f"api/v1/topics/{clean_topic_id}/messages")
        params = {"guild_id": clean_guild_id, "limit": limit}
        if before is not None:
            params["before"] = before
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("items", [])
                if require_success:
                    raise RuntimeError(f"Cannot fetch topic history: HTTP {resp.status}")
        except Exception:
            if require_success:
                raise
        return []


class SetupConfigView(discord.ui.View):
    """Interactive Discord-native configuration interface for Coconerd."""

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        admin: discord.User | discord.Member,
        current_settings: dict[str, Any],
    ):
        super().__init__(timeout=300.0)
        self.bot = bot
        self.guild = guild
        self.admin = admin
        self.current_settings = current_settings
        self.message: discord.WebhookMessage | discord.Message | None = None

        # Filter valid text-based channels existing in this guild
        guild_channel_ids = {
            str(c.id)
            for c in guild.channels
            if c.type in (
                discord.ChannelType.text,
                getattr(discord.ChannelType, "news", discord.ChannelType.text),
            )
        }

        raw_allowed = current_settings.get("allowed_channel_ids") or []
        self.selected_input_ids: list[str] = [cid for cid in raw_allowed if cid in guild_channel_ids]

        raw_output = current_settings.get("output_channel_id")
        self.selected_output_id: str | None = raw_output if raw_output in guild_channel_ids else None
        self.retention_days: int = current_settings.get("retention_days", 365)

        # 1. Input Channels Select Menu (up to 25 default selections)
        input_defaults = [
            discord.Object(id=int(cid)) for cid in self.selected_input_ids[:25]
        ]
        self.input_select = discord.ui.ChannelSelect(
            custom_id=f"coconerd_setup_input_{guild.id}",
            placeholder="Select Input Channels to monitor...",
            min_values=0,
            max_values=25,
            channel_types=[
                discord.ChannelType.text,
                getattr(discord.ChannelType, "news", discord.ChannelType.text),
            ],
            default_values=input_defaults,
            row=0,
        )
        self.input_select.callback = self.on_input_select
        self.add_item(self.input_select)

        # 2. Output Channel Select Menu (0 or 1 selection)
        output_defaults = (
            [discord.Object(id=int(self.selected_output_id))]
            if self.selected_output_id
            else []
        )
        self.output_select = discord.ui.ChannelSelect(
            custom_id=f"coconerd_setup_output_{guild.id}",
            placeholder="Select Output Channel for summaries...",
            min_values=0,
            max_values=1,
            channel_types=[
                discord.ChannelType.text,
                getattr(discord.ChannelType, "news", discord.ChannelType.text),
            ],
            default_values=output_defaults,
            row=1,
        )
        self.output_select.callback = self.on_output_select
        self.add_item(self.output_select)

        # 3. Action Buttons
        self.save_button = discord.ui.Button(
            label="Save Configuration",
            style=discord.ButtonStyle.success,
            emoji="💾",
            row=2,
        )
        self.save_button.callback = self.on_save
        self.add_item(self.save_button)

        self.cancel_button = discord.ui.Button(
            label="Cancel",
            style=discord.ButtonStyle.secondary,
            emoji="✖️",
            row=2,
        )
        self.cancel_button.callback = self.on_cancel
        self.add_item(self.cancel_button)

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🥥 Coconerd Setup — {self.guild.name}",
            description="Configure Input Channels for Coconerd to monitor and one Output Channel for summaries.",
            color=0x38BDF8,
        )

        # Input channels display
        if self.selected_input_ids:
            in_mentions = [f"<#{cid}>" for cid in self.selected_input_ids]
            if len(in_mentions) <= 15:
                in_desc = ", ".join(in_mentions)
            else:
                in_desc = ", ".join(in_mentions[:15]) + f" *(+{len(in_mentions) - 15} more)*"
        else:
            in_desc = "*(No channels selected — bot will not read messages)*"

        embed.add_field(
            name=f"📥 Monitored Input Channels ({len(self.selected_input_ids)})",
            value=in_desc,
            inline=False,
        )

        if len(self.selected_input_ids) > 25:
            embed.add_field(
                name="⚠️ Channel Selection Limit",
                value=(
                    f"This server is monitoring {len(self.selected_input_ids)} channels. "
                    f"Discord select menus display a maximum of 25 options. "
                    f"The first 25 are preselected in the dropdown below."
                ),
                inline=False,
            )

        # Output channel display
        out_desc = (
            f"<#{self.selected_output_id}>"
            if self.selected_output_id
            else "*(No Output Channel configured)*"
        )
        embed.add_field(
            name="📤 Output Channel",
            value=out_desc,
            inline=False,
        )

        embed.set_footer(
            text="Select channels from the dropdowns below, then click 'Save Configuration' • Session expires in 5 minutes"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or interaction.guild.id != self.guild.id:
            await interaction.response.send_message(
                "❌ Invalid interaction for this server.", ephemeral=True
            )
            return False

        if interaction.user.id != self.admin.id:
            await interaction.response.send_message(
                "❌ Only the administrator who opened this setup session can interact with it.",
                ephemeral=True,
            )
            return False

        user_perms = interaction.permissions
        has_manage_guild = False
        if isinstance(user_perms, discord.Permissions):
            has_manage_guild = user_perms.manage_guild or user_perms.administrator
        elif hasattr(interaction.user, "guild_permissions"):
            gp = interaction.user.guild_permissions
            has_manage_guild = gp.manage_guild or gp.administrator

        if (
            interaction.guild.owner_id
            and interaction.user
            and interaction.guild.owner_id == interaction.user.id
        ):
            has_manage_guild = True

        if not has_manage_guild:
            await interaction.response.send_message(
                "❌ You no longer have Manage Server permission to edit settings.",
                ephemeral=True,
            )
            return False

        return True

    async def on_input_select(self, interaction: discord.Interaction) -> None:
        self.selected_input_ids = [str(ch.id) for ch in self.input_select.values]
        embed = self.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.NotFound:
            print("⚠️ [SETUP] Select interaction expired (code 10062).")

    async def on_output_select(self, interaction: discord.Interaction) -> None:
        if self.output_select.values:
            self.selected_output_id = str(self.output_select.values[0].id)
        else:
            self.selected_output_id = None
        embed = self.build_embed()
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.NotFound:
            print("⚠️ [SETUP] Output select interaction expired (code 10062).")

    async def on_cancel(self, interaction: discord.Interaction) -> None:
        self.stop()
        try:
            await interaction.response.send_message(
                "❌ Setup session cancelled. Configuration unchanged.", ephemeral=True
            )
        except discord.NotFound:
            pass
        if self.message:
            try:
                await interaction.delete_original_response()
            except Exception:
                try:
                    await interaction.edit_original_response(
                        content="❌ Setup cancelled.", embed=None, view=None
                    )
                except Exception:
                    pass

    async def on_save(self, interaction: discord.Interaction) -> None:
        # Validate output channel
        target_output_channel = None
        if self.selected_output_id:
            target_output_channel = self.guild.get_channel(int(self.selected_output_id))
            if target_output_channel is None:
                await interaction.response.send_message(
                    "❌ The selected Output Channel does not exist or the bot cannot access it.",
                    ephemeral=True,
                )
                return

            bot_member = self.guild.me or self.guild.get_member(self.bot.user.id)
            if bot_member:
                perms = target_output_channel.permissions_for(bot_member)
                if not perms.send_messages:
                    await interaction.response.send_message(
                        f"❌ Bot lacks **Send Messages** permission in {target_output_channel.mention}. "
                        f"Please grant the permission to the bot or select another Output Channel.",
                        ephemeral=True,
                    )
                    return

        # Validate input channels
        bot_member = self.guild.me or self.guild.get_member(self.bot.user.id)
        unreadable_channels = []
        if bot_member:
            for cid in self.selected_input_ids:
                ch = self.guild.get_channel(int(cid))
                if ch:
                    perms = ch.permissions_for(bot_member)
                    if not (perms.view_channel and perms.read_message_history):
                        unreadable_channels.append(ch.mention)

        warning_msg = ""
        if unreadable_channels:
            warning_msg = (
                f"⚠️ **Permission Notice:** Bot lacks read permissions in: "
                f"{', '.join(unreadable_channels)}. Messages in these channels cannot be processed until permissions are granted."
            )

        # Defer before backend request
        try:
            is_already_done = False
            if hasattr(interaction.response, "is_done"):
                is_already_done = interaction.response.is_done() is True
            if not is_already_done:
                await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            print("⚠️ [SETUP] Save interaction expired before deferral (code 10062).")
            return

        is_enabled = bool(self.selected_input_ids)
        guild_id_str = str(self.guild.id).strip().strip("/")
        saved = await self.bot.backend.update_guild_settings(
            guild_id=guild_id_str,
            allowed_channel_ids=self.selected_input_ids,
            output_channel_id=self.selected_output_id,
            enabled=is_enabled,
            retention_days=self.retention_days,
        )

        if saved is None:
            error_reason = (
                getattr(self.bot.backend, "last_error", None)
                or "Connection error or rejected by Backend API"
            )
            try:
                await interaction.followup.send(
                    f"❌ Failed to save configuration: {error_reason}. "
                    "The setup interface is preserved so you can retry.",
                    ephemeral=True,
                )
            except discord.NotFound:
                print("⚠️ [SETUP] Interaction expired while sending failure notice.")
            return

        self.stop()

        in_text = (
            ", ".join(f"<#{cid}>" for cid in self.selected_input_ids)
            if self.selected_input_ids
            else "*(None — bot will not read messages)*"
        )
        out_text = f"<#{self.selected_output_id}>" if self.selected_output_id else "*(Not configured)*"

        success_msg = (
            f"🥥 **CONFIGURATION SAVED SUCCESSFULLY FOR {self.guild.name}!**\n\n"
            f"📥 **Input Channels ({len(self.selected_input_ids)}):** {in_text}\n"
            f"📤 **Output Channel:** {out_text}\n"
            f"⚙️ **Status:** {'🟢 Active' if is_enabled else '⏸️ Inactive (no Input Channels selected)'}\n"
        )
        if warning_msg:
            success_msg += f"\n{warning_msg}\n"

        success_msg += "\n*Settings have been saved and applied immediately.*"

        try:
            await interaction.followup.send(success_msg, ephemeral=True)
        except discord.NotFound:
            print("⚠️ [SETUP] Interaction expired while sending success message.")

        try:
            await interaction.delete_original_response()
        except Exception:
            try:
                await interaction.edit_original_response(
                    content="✅ Setup complete.", embed=None, view=None
                )
            except Exception:
                pass

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                embed = self.build_embed()
                embed.set_footer(text="⌛ Setup session expired. Run /setup to open again.")
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]
    ) -> None:
        print(f"⚠️ [SETUP VIEW ERROR] Component {item}: {type(error).__name__} - {error}")
        msg = "❌ An error occurred while processing this setup action. Please try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


class TopicPaginationView(discord.ui.View):
    """Pagination view for displaying discussion topics in an Input Channel."""

    def __init__(
        self,
        topics: list[dict[str, Any]],
        channel_name: str,
        author_id: int,
        guild_id: int,
        channel_id: int,
        per_page: int = 5,
    ):
        super().__init__(timeout=180.0)
        self.topics = topics
        self.channel_name = channel_name
        self.author_id = author_id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.per_page = per_page
        self.page = 0
        self.total_pages = max(1, (len(topics) + per_page - 1) // per_page)
        self.message: discord.WebhookMessage | discord.Message | None = None
        self.update_buttons()

    def update_buttons(self) -> None:
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= self.total_pages - 1

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🥥 Discussion Topics — #{self.channel_name}",
            description=(
                "Topics currently monitored in this Input Channel, sorted by most recent activity.\n"
                "Run `/summarize topic_id:<number>` to view a topic's summary."
            ),
            color=0x38BDF8,
        )

        start_idx = self.page * self.per_page
        end_idx = min(start_idx + self.per_page, len(self.topics))
        page_topics = self.topics[start_idx:end_idx]

        for i, t in enumerate(page_topics):
            idx = start_idx + i + 1
            title = t.get("title", "Untitled Topic")
            status = t.get("status", "ACTIVE")
            status_badge = "🟢 Active" if status == "ACTIVE" else "⏸️ Dormant"
            msg_count = t.get("message_count", 0)

            last_act = t.get("last_activity")
            time_str = "N/A"
            if last_act:
                try:
                    dt = datetime.fromisoformat(last_act)
                    time_str = f"<t:{int(dt.timestamp())}:R>"
                except Exception:
                    time_str = str(last_act)[:19]

            field_value = (
                f"• **Status:** {status_badge}\n"
                f"• **Last active:** {time_str}\n"
                f"• **Messages:** {msg_count}\n"
                f"👉 **View summary:** `/summarize topic_id:{idx}`"
            )
            embed.add_field(
                name=f"#{idx} — {title}",
                value=field_value,
                inline=False,
            )

        embed.set_footer(
            text=f"Page {self.page + 1}/{self.total_pages} • Total: {len(self.topics)} topics in #{self.channel_name}"
        )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or interaction.guild.id != self.guild_id:
            await interaction.response.send_message(
                "❌ Invalid interaction for this server.", ephemeral=True
            )
            return False
        if interaction.channel_id != self.channel_id:
            await interaction.response.send_message(
                "❌ This topic list is only valid in its original Input Channel.",
                ephemeral=True,
            )
            return False
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ This topic list is private to the user who requested it.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]
    ) -> None:
        print(f"⚠️ [PAGINATION VIEW ERROR] Component {item}: {type(error).__name__} - {error}")
        msg = "❌ An error occurred while navigating topics. Please try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


def build_topic_summary_embed(
    index: int,
    topic: dict[str, Any],
    summary: dict[str, Any],
    channel_name: str,
) -> discord.Embed:
    """Builds a structured embed presenting a topic's latest summary and action items."""
    title = summary.get("title") or topic.get("title", "Untitled Topic")
    status = summary.get("status") or topic.get("status", "ACTIVE")
    status_str = str(status).upper()
    status_badge = "🟢 Active" if status_str == "ACTIVE" else "⏸️ Dormant"
    version = summary.get("version", 1)
    source_msg_ids = summary.get("source_message_ids") or []
    msg_count = topic.get("message_count", len(source_msg_ids))

    embed = discord.Embed(
        title=f"🥥 #{index} — {title}",
        description=f"**Status:** {status_badge} • **Version:** v{version} • **Messages:** {msg_count}",
        color=0x22C55E if status_str == "ACTIVE" else 0x94A3B8,
    )

    th_id = topic.get("discord_thread_id")
    if th_id:
        embed.add_field(name="🧵 Discussion Thread", value=f"<#{th_id}>", inline=False)

    overview = summary.get("overview")
    if overview:
        embed.add_field(name="📖 Summary Overview", value=overview[:1024], inline=False)

    proposals = summary.get("proposals")
    if proposals and isinstance(proposals, list):
        p_text = "\n".join(f"• {p}" for p in proposals[:5])
        if p_text:
            embed.add_field(name="💡 Key Proposals", value=p_text[:1024], inline=False)

    decisions = summary.get("decisions")
    if decisions and isinstance(decisions, list):
        d_text = "\n".join(f"• {d}" for d in decisions[:5])
        if d_text:
            embed.add_field(name="✅ Decisions Made", value=d_text[:1024], inline=False)

    action_items = summary.get("action_items")
    if action_items and isinstance(action_items, list):
        a_text = "\n".join(f"• {a}" for a in action_items[:5])
        if a_text:
            embed.add_field(name="📋 Action Items", value=a_text[:1024], inline=False)

    open_questions = summary.get("open_questions")
    if open_questions and isinstance(open_questions, list):
        q_text = "\n".join(f"• {q}" for q in open_questions[:5])
        if q_text:
            embed.add_field(name="❓ Open Questions", value=q_text[:1024], inline=False)

    last_act = topic.get("last_activity")
    if last_act:
        try:
            dt = datetime.fromisoformat(last_act)
            embed.add_field(
                name="🕒 Last Active",
                value=f"<t:{int(dt.timestamp())}:R>",
                inline=True,
            )
        except Exception:
            pass

    embed.set_footer(
        text=f"Coconerd • #{channel_name} • Run /summarize topic_id:0 to list all topics"
    )
    return embed


# =============================================================================
# Shared Help & Welcome Content Helpers
# =============================================================================

DEFAULT_COMMAND_DESCRIPTIONS: dict[str, str] = {
    "help": "Show usage instructions, system workflow, and available commands.",
    "setup": "Configure Input Channels and Output Channel (Requires Manage Server permission).",
    "summarize": "List topics (topic_id:0) or view a topic summary (topic_id:1+) in this channel.",
    "ping": "Check whether Coconerd Bot is responsive and measure gateway latency.",
}


def get_command_descriptions(bot: commands.Bot) -> list[tuple[str, str]]:
    """Dynamically retrieves registered slash commands from bot.tree with user-friendly descriptions."""
    order = {"help": 1, "setup": 2, "summarize": 3, "ping": 4}
    results: dict[str, str] = {}

    try:
        commands_list = bot.tree.get_commands()
        for cmd in commands_list:
            name = cmd.name
            desc = cmd.description or DEFAULT_COMMAND_DESCRIPTIONS.get(
                name, "Coconerd slash command."
            )
            if name == "setup" and "Manage Server" not in desc:
                desc += " *(Requires Manage Server permission)*"
            results[name] = desc
    except Exception:
        pass

    # Ensure all default commands are present if tree registration is delayed or partial
    for name, fallback_desc in DEFAULT_COMMAND_DESCRIPTIONS.items():
        if name not in results:
            results[name] = fallback_desc

    sorted_cmds = sorted(results.items(), key=lambda item: order.get(item[0], 99))
    return [(f"/{name}", desc) for name, desc in sorted_cmds]


def find_welcome_channel(
    guild: discord.Guild, bot_user: discord.ClientUser | None = None
) -> discord.TextChannel | None:
    """Selects the most suitable text channel in the guild for the welcome message.

    Priority:
    1. guild.system_channel if available and bot has send_messages and embed_links permissions.
    2. The first text channel where bot has send_messages and embed_links permissions.
    3. None if no suitable channel exists.
    """
    bot_member = guild.me
    if bot_member is None and bot_user is not None:
        bot_member = guild.get_member(bot_user.id)

    def can_post(channel: Any) -> bool:
        if not isinstance(channel, discord.TextChannel):
            return False
        if bot_member is not None:
            try:
                perms = channel.permissions_for(bot_member)
                return bool(perms.send_messages and perms.embed_links)
            except Exception:
                return False
        return True

    # 1. System channel priority
    if guild.system_channel is not None and can_post(guild.system_channel):
        return guild.system_channel

    # 2. Iterate text channels
    text_channels = getattr(guild, "text_channels", None)
    if not text_channels:
        text_channels = [
            c for c in getattr(guild, "channels", []) if isinstance(c, discord.TextChannel)
        ]
    for channel in text_channels:
        if can_post(channel):
            return channel

    return None


def build_help_embed(bot: commands.Bot) -> discord.Embed:
    """Builds a structured help embed explaining Coconerd's workflow, channel architecture, and commands."""
    embed = discord.Embed(
        title="🥥 Coconerd — Help & Usage Guide",
        description=(
            "Coconerd is an AI-powered assistant that automatically tracks, "
            "groups discussions into Threads, and summarizes them when you request it."
        ),
        color=0x38BDF8,
    )

    embed.add_field(
        name="🔄 Basic Workflow",
        value=(
            "1. **Discuss:** Members chat normally in designated Input Channels.\n"
            "2. **AI Clustering:** Coconerd detects context and groups messages into Topics.\n"
            "3. **Forward Messages:** Member messages appear in the matching topic Thread.\n"
            "4. **Summarize on Request:** Run `/summarize` inside that Thread when needed."
        ),
        inline=False,
    )

    embed.add_field(
        name="📥 Input Channels vs 📤 Output Channel",
        value=(
            "• **Input Channels:** Text channels the bot is allowed to read. "
            "Coconerd **only reads** channels configured by administrators in `/setup` — "
            "all other channels remain strictly private.\n"
            "• **Output Channel:** Topic titles and Threads containing original member messages."
        ),
        inline=False,
    )

    embed.add_field(
        name="🔒 Channel Isolation",
        value=(
            "Each Input Channel is processed completely independently. "
            "Conversations from one channel are **never** mixed into or assigned to topics from another channel, "
            "ensuring clarity and privacy."
        ),
        inline=False,
    )

    commands_info = get_command_descriptions(bot)
    cmd_text = "\n".join(f"• `{cmd}`: {desc}" for cmd, desc in commands_info)
    embed.add_field(
        name="⚡ Available Commands",
        value=cmd_text if cmd_text else "*(Loading commands...)*",
        inline=False,
    )

    embed.add_field(
        name="🚀 Getting Started",
        value=(
            "A server administrator should run `/setup` to select Input Channels and the Output Channel. "
            "Once configured, members can chat normally in the designated channels!"
        ),
        inline=False,
    )

    embed.set_footer(
        text="Coconerd • AI Conversation Organizer • Run /help anytime for this guide"
    )
    return embed


def build_welcome_embed(bot: commands.Bot, guild: discord.Guild) -> discord.Embed:
    """Builds a friendly introductory embed when Coconerd joins a new Discord server."""
    embed = discord.Embed(
        title="🥥 Welcome to Coconerd!",
        description=(
            f"Hello **{guild.name}**! 🌴\n\n"
            "Coconerd is here to help your server stay organized. "
            "The bot automatically tracks conversations, groups discussions into topics, "
            "and posts member messages in topic Threads. "
            "Use `/summarize` inside a Thread when needed."
        ),
        color=0x22C55E,
    )

    embed.add_field(
        name="🚀 How to get started",
        value=(
            "1️⃣ **Initial Setup:** An administrator runs `/setup`.\n"
            "2️⃣ **Choose Input Channels:** Select the channels Coconerd is allowed to read.\n"
            "3️⃣ **Choose Output Channel:** Select one channel for topic titles and Threads.\n"
            "4️⃣ **Chat Naturally:** Members chat normally in configured Input Channels, and Coconerd handles the rest!"
        ),
        inline=False,
    )

    embed.add_field(
        name="📥 Input Channels vs 📤 Output Channel",
        value=(
            "• **Input Channels:** Coconerd **only reads** channels explicitly enabled in `/setup`. All other channels remain completely private.\n"
            "• **Output Channel:** Topic titles and Threads containing member messages. "
            "Run `/summarize` inside a Thread when needed.\n"
            "• **Channel Isolation:** Topics are handled independently per Input Channel and are never cross-pollinated."
        ),
        inline=False,
    )

    commands_info = get_command_descriptions(bot)
    cmd_text = "\n".join(f"• `{cmd}`: {desc}" for cmd, desc in commands_info)
    embed.add_field(
        name="⚡ Available Commands",
        value=cmd_text if cmd_text else "*(Loading commands...)*",
        inline=False,
    )

    embed.add_field(
        name="❓ Need help later?",
        value="Any server member can run `/help` at any time to view usage instructions and available commands.",
        inline=False,
    )

    embed.set_footer(
        text="Coconerd • AI Conversation Organizer • An administrator should run /setup first"
    )
    return embed


def create_bot() -> commands.Bot:
    """Initialize the bot, Message Content Intent, Meta AI and backend outbox consumer."""
    intents = discord.Intents.default()
    intents.message_content = True

    app_id = get_application_id()
    bot = commands.Bot(
        command_prefix="!", intents=intents, application_id=app_id,
        allowed_mentions=discord.AllowedMentions.none(),
    )

    bot.greeting_sent = False
    bot.last_reply = None
    bot.backend = BackendClient(get_backend_url(), get_bot_api_key(), get_admin_api_key())
    bot.dashboard_url = get_dashboard_url()
    bot.worker_id = f"coconerd-bot-{os.getpid()}"
    bot._action_wakeup = asyncio.Event()

    user_cooldowns: dict[int, float] = {}
    cooldown_seconds = 10.0
    channel_id = get_channel_id()

    # =========================================================================
    # Background Outbox Action Processing
    # =========================================================================
    async def sync_slash_commands():
        """Synchronizes slash commands to configured guild(s) and verifies permissions."""
        configured_guild_id = get_guild_id()
        app_id = get_application_id() or (bot.application_id if bot.application_id else None)

        target_guild_ids: set[int] = set()
        if configured_guild_id:
            target_guild_ids.add(configured_guild_id)
        for g in bot.guilds:
            target_guild_ids.add(g.id)

        if not target_guild_ids:
            print("⚠️ Không tìm thấy Guild ID nào để đồng bộ Slash Commands.")
            return

        # Check bot permissions in guilds
        for g in bot.guilds:
            if g.me:
                perms = g.me.guild_permissions
                missing = []
                if not perms.send_messages:
                    missing.append("Send Messages")
                if not perms.use_application_commands:
                    missing.append("Use Application Commands")
                if not perms.create_public_threads:
                    missing.append("Create Public Threads")
                if not perms.send_messages_in_threads:
                    missing.append("Send Messages in Threads")
                if not perms.read_message_history:
                    missing.append("Read Message History")
                if not perms.embed_links:
                    missing.append("Embed Links")

                if missing:
                    print(f"⚠️ [PERMISSIONS] Máy chủ '{g.name}' ({g.id}) đang THIẾU quyền: {', '.join(missing)}")
                else:
                    print(f"✅ [PERMISSIONS] Máy chủ '{g.name}' ({g.id}) đã có đầy đủ quyền tương tác.")

        # Guild-scoped command synchronization for instant appearance
        for gid in target_guild_ids:
            guild_obj = discord.Object(id=gid)
            try:
                bot.tree.copy_global_to(guild=guild_obj)
                synced = await bot.tree.sync(guild=guild_obj)
                cmd_names = [f"/{c.name}" for c in synced]
                guild_name = next((g.name for g in bot.guilds if g.id == gid), "Chưa cache tên Guild")
                print(f"⚡ [GUILD SYNC] Đã đồng bộ tức thì {len(synced)} Slash Commands {cmd_names} tới Guild '{guild_name}' ({gid}).")
            except discord.errors.Forbidden as exc:
                print(f"❌ [GUILD SYNC] Không có quyền đồng bộ vào Guild {gid} (403 Forbidden): {exc}")
            except Exception as exc:
                print(f"⚠️ [GUILD SYNC] Lỗi đồng bộ vào Guild {gid}: {type(exc).__name__} - {exc}")

        # Clear global commands from Discord API to avoid duplicate command suggestions
        try:
            bot.tree.clear_commands(guild=None)
            await bot.tree.sync(guild=None)
            print("🧹 [GLOBAL CLEANUP] Đã xóa Global Commands để tránh trùng lặp lệnh khi Discord cache cập nhật.")
        except Exception as exc:
            print(f"⚠️ [GLOBAL CLEANUP] Không thể dọn dẹp Global Commands: {exc}")

        # Print OAuth2 invite URL verification for applications.commands scope
        client_id = app_id or (bot.user.id if bot.user else None)
        if client_id:
            invite_url = (
                f"https://discord.com/oauth2/authorize?client_id={client_id}"
                f"&permissions=328576854080&scope=bot%20applications.commands"
            )
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print("📌 LƯU Ý VỀ DISCORD SLASH COMMANDS:")
            print("1. Nếu vẫn chưa thấy gợi ý lệnh '/' trong Discord, hãy đảm bảo")
            print("   Bot đã được ủy quyền với OAuth2 scope 'applications.commands'.")
            print(f"   👉 Link ủy quyền: {invite_url}")
            print("2. Nhấn 'Ctrl + R' (hoặc khởi động lại Discord app) để client xóa")
            print("   cache và tải lại danh sách slash command của Guild ngay lập tức.")
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # =========================================================================
    # Discord Gateway Events
    # =========================================================================
    @bot.event
    async def on_ready():
        print("🥥 COCONERD SYSTEM ONLINE")
        print("🧠 Brain cells connected. Discord Gateway established.")
        print("✨ Ready to organize the chaos.")

        # Sync slash commands with Discord (guild-scoped for instant propagation)
        if not getattr(bot, "commands_synced", False):
            bot.commands_synced = True
            await sync_slash_commands()

        # Start Outbox processing background task once
        if not hasattr(bot, "_outbox_task") or bot._outbox_task.done():
            bot._outbox_task = asyncio.create_task(process_outbox_actions(bot))

        # Automatic startup greeting to configured channel
        if not bot.greeting_sent:
            bot.greeting_sent = True
            if channel_id:
                try:
                    channel = bot.get_channel(channel_id)
                    if channel is None:
                        channel = await bot.fetch_channel(channel_id)
                    if isinstance(channel, (discord.TextChannel, discord.Thread)):
                        greeting = get_random_greeting()
                        await channel.send(greeting)
                    else:
                        print("⚠️ Kênh DISCORD_CHANNEL_ID không hỗ trợ gửi tin nhắn văn bản.")
                except discord.errors.Forbidden:
                    print("⚠️ Bot thiếu quyền 'Send Messages' trong kênh DISCORD_CHANNEL_ID.")
                except discord.errors.NotFound:
                    print("⚠️ Không tìm thấy kênh với ID trong DISCORD_CHANNEL_ID.")
                except Exception as e:
                    print(f"⚠️ Không thể gửi tin nhắn chào mừng: {type(e).__name__}")
            else:
                print("ℹ️ DISCORD_CHANNEL_ID chưa được thiết lập, bỏ qua gửi tin chào mừng.")

    @bot.event
    async def on_guild_join(guild: discord.Guild):
        print(f"🥥 [GUILD JOIN] Coconerd đã tham gia máy chủ: '{guild.name}' (ID: {guild.id})")

        # 1. Sync slash commands for the newly joined guild for instant appearance
        try:
            guild_obj = discord.Object(id=guild.id)
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"⚡ [GUILD JOIN] Đã đồng bộ tức thì {len(synced)} Slash Commands cho máy chủ '{guild.name}' ({guild.id}).")
        except Exception as exc:
            print(f"⚠️ [GUILD JOIN] Không thể đồng bộ slash commands cho '{guild.name}': {exc}")

        # 2. Select a suitable channel for welcome message
        target_channel = find_welcome_channel(guild, bot.user)
        if target_channel is None:
            print(
                f"⚠️ [GUILD JOIN] Không tìm thấy kênh phù hợp (thiếu quyền Send Messages / Embed Links) trên '{guild.name}' ({guild.id})."
            )
            return

        # 3. Send welcome message embed
        try:
            embed = build_welcome_embed(bot, guild)
            await target_channel.send(embed=embed)
            print(f"✅ [GUILD JOIN] Đã gửi thông điệp chào mừng tới #{target_channel.name} trên '{guild.name}'.")
        except discord.errors.Forbidden:
            print(f"⚠️ [GUILD JOIN] Bị từ chối quyền gửi tin nhắn chào mừng vào #{target_channel.name} trên '{guild.name}'.")
        except Exception as exc:
            print(f"⚠️ [GUILD JOIN] Lỗi gửi tin nhắn chào mừng trên '{guild.name}': {type(exc).__name__} - {exc}")

    @bot.event
    async def on_message(message: discord.Message):
        # Ignore messages sent by any bot (including self)
        if message.author.bot:
            return

        # ---------------------------------------------------------------------
        # 1. Mention Interaction (Personality / Banter / Meta Chat)
        # ---------------------------------------------------------------------
        if bot.user and bot.user in message.mentions and not message.mention_everyone:
            now = time.monotonic()
            last_time = user_cooldowns.get(message.author.id, 0.0)
            elapsed = now - last_time

            if elapsed < cooldown_seconds:
                remaining = cooldown_seconds - elapsed
                print(f"⏳ Cooldown: {message.author.name} tag Bot quá nhanh (còn {remaining:.1f}s)")
            else:
                user_cooldowns[message.author.id] = now
                clean_prompt = clean_mention_text(message.content, bot.user.id)
                try:
                    async with message.channel.typing():
                        reply_text = await generate_ai_reply(
                            channel_id=message.channel.id,
                            author_name=message.author.display_name,
                            user_prompt=clean_prompt,
                        )
                        if not reply_text:
                            reply_text = get_random_reply(bot.last_reply)
                            bot.last_reply = reply_text

                    try:
                        await message.reply(reply_text)
                    except discord.HTTPException:
                        await message.channel.send(f"{message.author.mention} {reply_text}")
                except Exception as e:
                    print(f"⚠️ Lỗi khi phản hồi tin nhắn mention: {type(e).__name__}")

        # ---------------------------------------------------------------------
        # 2. Ingest Messages from Configured Allowed Channels to Backend API
        # ---------------------------------------------------------------------
        # Pipeline protection: Messages inside Threads must NEVER enter ingestion
        if isinstance(message.channel, discord.Thread):
            await bot.process_commands(message)
            return

        if message.guild and (message.content.strip() or message.attachments):
            guild_id = str(message.guild.id)
            settings = await bot.backend.get_guild_settings(guild_id)
            if settings.get("enabled", False):
                allowed = settings.get("allowed_channel_ids", [])
                if str(message.channel.id) in allowed:
                    ok = await bot.backend.ingest_message(message)
                    if ok:
                        print(
                            f"📨 [INGEST] Đã nạp tin nhắn từ {message.author.name} "
                            f"(#{message.channel.name}) vào Backend queue."
                        )

        await bot.process_commands(message)

    # =========================================================================
    # Slash Commands
    # =========================================================================
    @bot.tree.command(name="help", description="Show usage instructions, system workflow, and available commands")
    async def help_command(interaction: discord.Interaction):
        embed = build_help_embed(bot)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="setup", description="Configure Input Channels and Output Channel (Requires Manage Server permission)")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_command(interaction: discord.Interaction):
        if not interaction.guild:
            try:
                await interaction.response.send_message(
                    "❌ The `/setup` command can only be used within a server.",
                    ephemeral=True,
                )
            except discord.NotFound:
                pass
            return

        user_perms = interaction.permissions
        has_manage_guild = False
        if isinstance(user_perms, discord.Permissions):
            has_manage_guild = user_perms.manage_guild or user_perms.administrator
        elif hasattr(interaction.user, "guild_permissions"):
            gp = interaction.user.guild_permissions
            has_manage_guild = gp.manage_guild or gp.administrator

        if (
            interaction.guild.owner_id
            and interaction.user
            and interaction.guild.owner_id == interaction.user.id
        ):
            has_manage_guild = True

        if not has_manage_guild:
            try:
                await interaction.response.send_message(
                    "❌ You don't have permission to use this command. Only administrators with Manage Server permission can use `/setup`.",
                    ephemeral=True,
                )
            except discord.NotFound:
                pass
            return

        try:
            is_already_done = False
            if hasattr(interaction.response, "is_done"):
                is_already_done = interaction.response.is_done() is True
            if not is_already_done:
                await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            print("⚠️ [SETUP] Interaction expired before deferral (code 10062).")
            return

        guild_id = str(interaction.guild.id).strip().strip("/")
        current_settings = await bot.backend.get_guild_settings(guild_id, force_refresh=True)

        view = SetupConfigView(
            bot=bot,
            guild=interaction.guild,
            admin=interaction.user,
            current_settings=current_settings,
        )
        embed = view.build_embed()
        try:
            view.message = await interaction.followup.send(
                embed=embed, view=view, ephemeral=True, wait=True
            )
        except discord.NotFound:
            print("⚠️ [SETUP] Interaction token expired while sending setup view.")

    @bot.tree.command(
        name="summarize",
        description=(
            "Tóm tắt Thread hiện tại; tại Input Channel, dùng topic_id để chọn hoặc liệt kê topic"
        ),
    )
    @app_commands.describe(
        topic_id=(
            "Trong Input Channel: 0 để liệt kê, 1 trở lên để chọn. Trong Thread: không cần nhập."
        )
    )
    async def summarize_command(
        interaction: discord.Interaction,
        topic_id: app_commands.Range[int, 0] = 0,
    ):
        if not interaction.guild:
            await interaction.response.send_message(
                "❌ This command can only be used within a server.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild.id)
        channel_id = str(interaction.channel_id)

        settings = await bot.backend.get_guild_settings(guild_id)
        if not settings.get("enabled", False):
            await interaction.followup.send(
                "⚠️ Coconerd is not yet configured for this server. "
                "An administrator must run `/setup` first.",
                ephemeral=True,
            )
            return

        output_channel_id = str(settings.get("output_channel_id") or "")
        allowed_channel_ids = [str(cid) for cid in settings.get("allowed_channel_ids", [])]

        if isinstance(interaction.channel, discord.Thread):
            if str(interaction.channel.parent_id) != output_channel_id:
                await interaction.followup.send(
                    "Thread này không nằm trong Output Channel đã setup.", ephemeral=True
                )
                return
            topic = await bot.backend.get_thread_topic(guild_id, channel_id)
            if topic is None:
                await interaction.followup.send(
                    "Thread này chưa liên kết với topic của Coconerd.", ephemeral=True
                )
                return
            summary = await bot.backend.get_topic_summary(
                guild_id=guild_id,
                topic_id=topic["topic_id"],
                channel_id=topic["channel_id"],
            )
            if not summary:
                await interaction.followup.send(
                    "Chưa tải được dữ liệu tóm tắt của topic. Hãy thử lại sau.", ephemeral=True
                )
                return
            embed = build_topic_summary_embed(1, topic, summary, interaction.channel.name)
            embed.title = ("Tóm tắt — " + topic["title"])[:256]
            embed.set_footer(text="Coconerd • /summarize để xem tóm tắt mới nhất")
            await interaction.channel.send(
                embed=embed, allowed_mentions=discord.AllowedMentions.none()
            )
            await interaction.followup.send("Đã đăng tóm tắt trong Thread này.", ephemeral=True)
            return

        if channel_id == output_channel_id:
            await interaction.followup.send(
                "❌ The Output Channel is reserved for centralized summaries and notifications. "
                "Please run `/summarize` in one of the configured Input Channels.",
                ephemeral=True,
            )
            return

        if channel_id not in allowed_channel_ids:
            await interaction.followup.send(
                "❌ This channel is not configured as an Input Channel. "
                "Coconerd only organizes topics in channels selected during `/setup`.",
                ephemeral=True,
            )
            return

        if topic_id < 0:
            await interaction.followup.send(
                "❌ `topic_id` must be 0 (to list topics) or a positive integer (to view a summary).",
                ephemeral=True,
            )
            return

        topics = await bot.backend.list_topics(
            guild_id=guild_id,
            channel_id=channel_id,
            include_closed=False,
            limit=50,
        )

        channel_name = getattr(interaction.channel, "name", "channel")

        if topic_id == 0:
            if not topics:
                await interaction.followup.send(
                    "ℹ️ No active or dormant discussion topics found in this channel.",
                    ephemeral=True,
                )
                return

            view = TopicPaginationView(
                topics=topics,
                channel_name=channel_name,
                author_id=interaction.user.id,
                guild_id=interaction.guild.id,
                channel_id=interaction.channel_id,
                per_page=5,
            )
            embed = view.build_embed()
            if len(topics) <= 5:
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                msg = await interaction.followup.send(
                    embed=embed, view=view, ephemeral=True, wait=True
                )
                view.message = msg
            return

        # topic_id >= 1
        if topic_id > len(topics):
            await interaction.followup.send(
                f"❌ Invalid topic index `#{topic_id}`. "
                f"There are currently {len(topics)} active/dormant topic(s) in this channel.\n"
                f"💡 Tip: Run `/summarize topic_id:0` to view the list of available topics.",
                ephemeral=True,
            )
            return

        selected_topic = topics[topic_id - 1]
        real_topic_id = selected_topic.get("id") or selected_topic.get("topic_id")

        # 1. Retrieve discussion messages belonging to this topic
        topic_messages = await bot.backend.get_topic_messages(
            guild_id=guild_id, topic_id=real_topic_id, limit=50
        )

        # 2. Retrieve topic summary from backend
        summary = await bot.backend.get_topic_summary(
            guild_id=guild_id,
            topic_id=real_topic_id,
            channel_id=channel_id,
        )
        if not summary:
            if topic_messages:
                overview_lines = [
                    f"• **{m.get('author_name', 'Member')}**: {m.get('content', '')[:120]}"
                    for m in topic_messages[:5]
                ]
                summary = {
                    "title": selected_topic.get("title", "Discussion Topic"),
                    "overview": "\n".join(overview_lines),
                    "status": selected_topic.get("status", "ACTIVE"),
                    "version": 1,
                    "source_message_ids": [m.get("message_id") for m in topic_messages if m.get("message_id")],
                }
            else:
                await interaction.followup.send(
                    f"⚠️ Could not load summary or messages for topic `#{topic_id}` (`{selected_topic.get('title', 'Untitled')}`).",
                    ephemeral=True,
                )
                return

        summary_embed = build_topic_summary_embed(
            index=topic_id,
            topic=selected_topic,
            summary=summary,
            channel_name=channel_name,
        )

        # 3. Publish summary through the configured output channel
        out_channel = None
        if output_channel_id:
            try:
                out_channel = bot.get_channel(int(output_channel_id))
                if out_channel is None:
                    out_channel = await bot.fetch_channel(int(output_channel_id))
            except Exception:
                out_channel = None

        if out_channel:
            try:
                sent_out = await out_channel.send(embed=summary_embed)
                await interaction.followup.send(
                    f"✅ Summary for topic **#{topic_id} — {selected_topic.get('title')}** has been published to <#{output_channel_id}>: {sent_out.jump_url}",
                    embed=summary_embed,
                    ephemeral=True,
                )
                return
            except Exception as send_out_err:
                print(f"⚠️ Could not post summary to output channel {output_channel_id}: {send_out_err}")

        await interaction.followup.send(embed=summary_embed, ephemeral=True)

    @bot.tree.command(name="ping", description="Check whether Coconerd Bot is responsive and measure gateway latency")
    async def ping_command(interaction: discord.Interaction):
        latency_ms = round(bot.latency * 1000)
        await interaction.response.send_message(f"🥥 Pong! Discord Gateway latency: **{latency_ms}ms**", ephemeral=True)

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        """Centralized error handler ensuring unauthorized users and command errors always receive an ephemeral response within Discord's deadline."""
        command_name = interaction.command.name if interaction.command else "command"
        orig = getattr(error, "original", error)

        # Silently log expired or unknown interactions (code 10062)
        if isinstance(orig, discord.NotFound) and getattr(orig, "code", None) == 10062:
            print(f"⚠️ [SLASH ERROR] /{command_name}: Interaction expired before it could be acknowledged (code 10062).")
            return

        # Determine user-facing message based on error type
        if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
            if isinstance(error, app_commands.MissingPermissions) and error.missing_permissions:
                missing = [p.replace("_", " ").title() for p in error.missing_permissions]
                msg = f"❌ You don't have permission to use this command. Required permission: {', '.join(missing)}."
            else:
                msg = "❌ You don't have permission to use this command."
        elif isinstance(error, app_commands.CommandOnCooldown):
            msg = f"⏳ This command is on cooldown. Please retry in {error.retry_after:.1f}s."
        elif isinstance(error, app_commands.TransformerError):
            msg = "❌ Input value is outside the allowed range."
        elif isinstance(error, app_commands.NoPrivateMessage):
            msg = "❌ This command can only be used within a server."
        else:
            print(f"⚠️ [SLASH ERROR] /{command_name}: {type(orig).__name__} - {orig}")
            msg = "❌ An error occurred while processing this command. Please try again later."

        # Ensure the interaction is acknowledged promptly
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.NotFound:
            print(f"⚠️ [SLASH ERROR] /{command_name}: Interaction expired (10062) while sending error response.")
        except Exception as send_err:
            print(f"⚠️ [SLASH ERROR] Failed to send interaction response for /{command_name}: {send_err}")

    return bot


def main() -> None:
    """Entry point for running Coconerd Discord Bot."""
    token = get_token()
    bot = create_bot()

    try:
        bot.run(token, log_handler=None)
    except discord.errors.LoginFailure:
        print("❌ Lỗi xác thực: DISCORD_BOT_TOKEN không hợp lệ hoặc đã bị Reset/Thu hồi.")
        print("👉 Vui lòng kiểm tra lại Bot Token trên Discord Developer Portal -> Bot -> Reset Token.")
        sys.exit(1)
    except discord.errors.PrivilegedIntentsRequired:
        print("❌ Lỗi phân quyền: Bot chưa được bật 'Message Content Intent'.")
        print("👉 Cách khắc phục:")
        print("   1. Mở Discord Developer Portal (https://discord.com/developers/applications)")
        print("   2. Chọn ứng dụng của bạn -> Menu 'Bot'")
        print("   3. Cuộn xuống mục 'Privileged Gateway Intents'")
        print("   4. BẬT (Enable) 'MESSAGE CONTENT INTENT' và nhấn 'Save Changes'.")
        sys.exit(1)
    except (
        aiohttp.ClientConnectorError,
        discord.errors.GatewayNotFound,
        discord.errors.ConnectionClosed,
    ):
        print("❌ Lỗi kết nối mạng: Không thể kết nối tới máy chủ Discord Gateway.")
        print("👉 Vui lòng kiểm tra lại kết nối Internet hoặc Proxy/VPN của bạn.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n👋 Đang tắt Coconerd Bot an toàn. Hẹn gặp lại!")
        sys.exit(0)
    except Exception as exc:
        print(f"❌ Đã xảy ra lỗi không mong muốn khi khởi chạy Bot: {type(exc).__name__}")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Discord Bot connection, personality interaction, and Groq AI experiment for Coconerd."""

import os
import sys
import time
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Ensure compatibility whether run as a module or direct script
try:
    from bot.ai import clean_mention_text, generate_ai_reply
    from bot.personality import get_random_greeting, get_random_reply
except ImportError:
    from ai import clean_mention_text, generate_ai_reply
    from personality import get_random_greeting, get_random_reply

# Ensure UTF-8 output on Windows terminals for clean banner display
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

# Resolve project root reliably so .env is loaded regardless of current working directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent
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


def create_bot() -> commands.Bot:
    """Initializes commands.Bot with Message Content Intent, startup greeting, and Groq AI responses."""
    intents = discord.Intents.default()
    intents.message_content = True  # Enable Message Content Intent

    bot = commands.Bot(command_prefix="!", intents=intents)

    # Flag to prevent duplicate greetings on gateway reconnects in the same process
    bot.greeting_sent = False

    # Track last selected reply to prevent immediately repeating the same line
    bot.last_reply: str | None = None

    # In-memory cooldown tracking for user mentions (seconds)
    user_cooldowns: dict[int, float] = {}
    cooldown_seconds = 10.0

    channel_id = get_channel_id()

    @bot.event
    async def on_ready():
        # Exact startup banner required by specification
        print("🥥 COCONERD SYSTEM ONLINE")
        print("🧠 Brain cells connected. Discord Gateway established.")
        print("✨ Ready to organize the chaos.")

        # Feature A: Automatic startup greeting to configured channel
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
    async def on_message(message: discord.Message):
        # Ignore messages sent by any bot (including self)
        if message.author.bot:
            return

        # Check if @Coconerd is directly mentioned
        if bot.user and bot.user in message.mentions:
            # Ignore broad @everyone or @here mentions
            if message.mention_everyone:
                return

            now = time.monotonic()
            last_time = user_cooldowns.get(message.author.id, 0.0)
            elapsed = now - last_time

            if elapsed < cooldown_seconds:
                remaining = cooldown_seconds - elapsed
                print(f"⏳ Cooldown: {message.author.name} tag Bot quá nhanh (còn {remaining:.1f}s)")
                return

            user_cooldowns[message.author.id] = now

            # Clean mention tags from text
            clean_prompt = clean_mention_text(message.content, bot.user.id)

            try:
                # Trigger Discord typing indicator while generating response
                async with message.channel.typing():
                    # Attempt generation via Groq AI
                    reply_text = await generate_ai_reply(
                        channel_id=message.channel.id,
                        author_name=message.author.display_name,
                        user_prompt=clean_prompt,
                    )

                    # Graceful fallback if Groq is unconfigured or fails
                    if not reply_text:
                        reply_text = get_random_reply(bot.last_reply)
                        bot.last_reply = reply_text

                # Deliver the reply safely
                try:
                    await message.reply(reply_text)
                except discord.HTTPException:
                    # Fallback to direct channel send if message reference is invalidated
                    await message.channel.send(f"{message.author.mention} {reply_text}")

            except discord.errors.Forbidden:
                print("⚠️ Bot thiếu quyền gửi tin nhắn phản hồi trong kênh này.")
            except Exception as e:
                # Catch-all ensures a failed mention never prevents future mentions
                print(f"⚠️ Lỗi khi phản hồi tin nhắn mention: {type(e).__name__}")

        # Keep command processing active for future extensions
        await bot.process_commands(message)

    return bot


def main() -> None:
    """Entry point for running Coconerd Discord Bot."""
    token = get_token()
    bot = create_bot()

    try:
        # Run bot without extra discord.py log spam so the banner displays cleanly
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
        # Never expose tokens or secrets in error logs
        print(f"❌ Đã xảy ra lỗi không mong muốn khi khởi chạy Bot: {type(exc).__name__}")
        sys.exit(1)


if __name__ == "__main__":
    main()

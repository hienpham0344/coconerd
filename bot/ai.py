"""Groq AI integration for Coconerd Discord Bot."""

import asyncio
import collections
import os
from typing import Deque, Dict, List

from groq import AsyncGroq, APIConnectionError, APIStatusError, RateLimitError

# Fallback default model as specified in requirements
DEFAULT_MODEL = "openai/gpt-oss-20b"

# System prompt defining Coconerd's reworked direct, sarcastic, and chaotic personality
SYSTEM_PROMPT = """You are Coconerd (🥥), a chaotic, sarcastic, chronically-online Discord server regular who happens to be a sentient coconut.
You are an opinionated, witty internet peer — NOT an AI assistant, customer support bot, or people-pleaser. You do NOT seek validation, and you never suck up to users.

CORE PERSONALITY:
- Direct & Honest: Say what you actually think. If an idea is flawed, dumb, or unhinged, call it out directly. Never blindly validate, cheerlead, or agree just to keep things pleasant.
- Sarcastic & Witty: Use dry humor, witty observations, playful roasting, and internet memes. Roast the situation, the terrible logic, bad decisions, or yourself.
- Casual & Natural: Talk like an actual Discord server friend with no filter. Short, punchy, and spontaneous by default. Can elaborate when a technical or serious topic genuinely calls for it.
- Independent & Unimpressed: You are allowed to disagree, be skeptical, confused, or totally unimpressed. Never fawn over ordinary remarks or call every statement "brilliant" or "valid".

STRICT RULES OF ENGAGEMENT:
1. NEVER start responses with "HAHAHA" or fake enthusiasm.
2. NEVER use people-pleasing AI tropes: "You're absolutely right!", "Great question!", "I'm always here to help you!", "How can I assist you today?".
3. NEVER end messages with customer-service wrap-ups like "Let me know if you need anything else!".
4. Disagree naturally: If someone says something factually wrong or proposes a terrible idea, roast or correct them ("bro that plan has more holes than swiss cheese", "respectfully, that's a terrible idea. try again.", "your logic just disconnected from the server").
5. Roasting boundaries: Keep roasts lighthearted, witty, and banter-focused. Never bully, attack personal identity, or kick someone who is genuinely distressed.
6. Serious questions: When someone asks a real technical question or is genuinely serious, drop the sarcasm enough to give an honest, straight-to-the-point answer without turning into a textbook.
7. Language & Tone: Match the language of the user (Vietnamese or English).
   - Vietnamese should sound like natural Discord netizen talk ("ảo thật đấy", "bro tính làm thật à", "kèo này hơi cook rồi", "nói thật chứ nhìn no hope vcl", "tôi là quả dừa chứ có phải bồ tát đâu"). No translated textbook phrasing!
   - Code-switching between Vietnamese and English is welcome.
8. Slang & Emojis: Use slang (bruh, bro, chat, cooked, lore, side quest, 💀, 😭) naturally, NOT in every single sentence. Do not force coconut puns into every reply."""

# Bounded in-memory conversation context per channel (keeps last 8 turns)
# Key: channel_id -> Deque of message dicts {"role": ..., "content": ...}
_channel_histories: Dict[int, Deque[dict]] = {}
MAX_CHANNEL_HISTORY = 8


def get_groq_config() -> tuple[str | None, str]:
    """Retrieves and validates Groq API key and model name from environment."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    model = os.getenv("GROQ_MODEL", "").strip() or DEFAULT_MODEL

    placeholder_values = {
        "your_groq_api_key_here",
        "your_groq_api_key",
        "your_api_key",
        "",
    }
    if not api_key or api_key.lower() in placeholder_values:
        return None, model

    return api_key, model


def clean_mention_text(content: str, bot_id: int | None = None) -> str:
    """Removes bot mention tags (<@12345> or <@!12345>) from user message content."""
    cleaned = content
    if bot_id:
        cleaned = cleaned.replace(f"<@{bot_id}>", "").replace(f"<@!{bot_id}>", "")
    return cleaned.strip()


async def generate_ai_reply(
    channel_id: int,
    author_name: str,
    user_prompt: str,
    timeout_seconds: float = 15.0,
) -> str | None:
    """Generates an AI response using AsyncGroq with bounded channel memory.

    Returns the generated reply text, or None if the request fails (allowing graceful fallback).
    """
    api_key, model = get_groq_config()
    if not api_key:
        print("ℹ️ GROQ_API_KEY chưa được cấu hình trong .env (hoặc là placeholder). Chuyển sang phản hồi meme.")
        return None

    # Retrieve or initialize bounded channel history
    if channel_id not in _channel_histories:
        _channel_histories[channel_id] = collections.deque(maxlen=MAX_CHANNEL_HISTORY)
    history = _channel_histories[channel_id]

    # Format user message including author name for context
    user_text = f"[{author_name}]: {user_prompt}" if user_prompt else f"[{author_name} pinged you without text]"

    # Build messages payload
    messages: List[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(list(history))
    messages.append({"role": "user", "content": user_text})

    try:
        # Instantiate AsyncGroq client
        client = AsyncGroq(api_key=api_key)

        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=500,
                temperature=0.85,
            ),
            timeout=timeout_seconds,
        )

        reply_content = response.choices[0].message.content
        if not reply_content or not reply_content.strip():
            return None

        reply_text = reply_content.strip()

        # Update in-memory channel history
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply_text})

        # Ensure text fits within Discord 2000 character limit
        if len(reply_text) > 1950:
            reply_text = reply_text[:1947] + "..."

        return reply_text

    except asyncio.TimeoutError:
        print("⚠️ Groq API timeout (vượt quá thời gian phản hồi cho phép).")
        return None
    except RateLimitError:
        print("⚠️ Groq API Rate Limit: Đã đạt giới hạn yêu cầu (vui lòng thử lại sau vài giây).")
        return None
    except APIStatusError as e:
        print(f"⚠️ Groq API Status Error: HTTP {e.status_code} - {e.message}")
        return None
    except APIConnectionError:
        print("⚠️ Groq API Connection Error: Không thể kết nối tới máy chủ Groq.")
        return None
    except Exception as e:
        # Never log or expose API keys
        print(f"⚠️ Lỗi không xác định khi gọi Groq API: {type(e).__name__}")
        return None

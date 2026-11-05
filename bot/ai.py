"""Meta Model API integration for Coconerd Discord Bot."""

import collections
import os
from dataclasses import dataclass, field

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError
from openai.types.chat import ChatCompletion

from coconerd_ai.task_routing import (
    META_API_BASE,
    TaskInvocation,
    TaskKind,
    TaskOutputError,
    TaskRouter,
    validate_meta_endpoint,
)

DEFAULT_API_BASE = META_API_BASE
DEFAULT_MODEL = "muse-spark-1.3"

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

# Bounded in-memory conversation context per channel (keeps last 8 messages)
# Key: channel_id -> Deque of message dicts {"role": ..., "content": ...}
_channel_histories: dict[int, collections.deque[dict]] = {}
MAX_CHANNEL_HISTORY = 8


@dataclass(frozen=True)
class MetaConfig:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    max_tokens: int
    reasoning_effort: str
    router: TaskRouter


def _env_value(*names: str, default: str = "") -> str:
    for name in names:
        if name in os.environ:
            return os.environ[name].strip()
    return default


def get_meta_config() -> MetaConfig | None:
    """Use the worker's Meta configuration without requiring backend dependencies."""
    api_key = _env_value(
        "COCONERD_MODEL_API_KEY", "MODEL_API_KEY", "COCONERD_META_API_KEY", "META_API_KEY"
    )
    if not api_key or api_key.lower().startswith(("your_", "replace_")):
        print("ℹ️ Chưa cấu hình COCONERD_MODEL_API_KEY hợp lệ; dùng phản hồi meme có sẵn.")
        return None

    try:
        base_url = validate_meta_endpoint(
            _env_value("COCONERD_META_API_BASE", "META_API_BASE") or DEFAULT_API_BASE
        )
        model = _env_value("COCONERD_META_MODEL_NAME", "META_MODEL_NAME") or DEFAULT_MODEL
        reasoning_effort = _env_value(
            "COCONERD_LLM_REASONING_EFFORT", "LLM_REASONING_EFFORT", default="low"
        )
        max_tokens = int(_env_value("COCONERD_LLM_MAX_TOKENS", "LLM_MAX_TOKENS", default="2048"))
        router = TaskRouter(
            model=model,
            max_tokens=max_tokens,
            temperature=float(_env_value("LLM_TEMPERATURE", default="0.85")),
            reasoning_effort=reasoning_effort,
            mode=_env_value("COCONERD_AGENT_MODE", default="task"),
            profiles_json=_env_value("COCONERD_TASK_PROFILES", default="{}"),
        )
    except ValueError:
        print("⚠️ Cấu hình Meta/task không hợp lệ; kiểm tra endpoint và các task profile.")
        return None
    return MetaConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        router=router,
    )


def _validate_chat_response(response: ChatCompletion) -> str:
    if not response.choices or response.choices[0].finish_reason != "stop":
        raise TaskOutputError("Meta chat response is incomplete")
    message = response.choices[0].message
    if message.refusal or not message.content or not message.content.strip():
        raise TaskOutputError("Meta chat response has no usable content")
    return message.content.strip()


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
    timeout_seconds: float | None = None,
) -> str | None:
    """Generates a Meta response with bounded channel memory.

    Returns the generated reply text, or None if the request fails (allowing graceful fallback).
    """
    config = get_meta_config()
    if config is None:
        return None

    # Retrieve or initialize bounded channel history
    if channel_id not in _channel_histories:
        _channel_histories[channel_id] = collections.deque(maxlen=MAX_CHANNEL_HISTORY)
    history = _channel_histories[channel_id]

    # Format user message including author name for context
    user_text = (
        f"[{author_name}]: {user_prompt}"
        if user_prompt
        else f"[{author_name} pinged you without text]"
    )

    profile = config.router.resolve(TaskKind.CHAT)
    context_messages = list(history)
    input_chars = (
        len(SYSTEM_PROMPT) + len(user_text) + sum(len(item["content"]) for item in context_messages)
    )
    # Drop complete old turns; never truncate the current user's request.
    while context_messages and input_chars > profile.max_input_chars:
        input_chars -= sum(len(item["content"]) for item in context_messages[:2])
        del context_messages[:2]

    # Build messages payload
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(context_messages)
    messages.append({"role": "user", "content": user_text})

    try:
        invocation = TaskInvocation(profile)
        deadline = (
            profile.timeout_seconds
            if timeout_seconds is None
            else min(profile.timeout_seconds, timeout_seconds)
        )
        # The OpenAI-compatible SDK is only a transport; requests always target Meta.
        async with AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=profile.timeout_seconds,
            max_retries=0,
        ) as client:
            reply_text = await invocation.run(
                lambda: client.chat.completions.create(
                    model=profile.model,
                    messages=messages,
                    max_tokens=profile.max_tokens,
                    reasoning_effort=profile.reasoning_effort,
                    temperature=profile.temperature,
                    timeout=deadline,
                ),
                input_chars=sum(len(item["content"]) for item in messages),
                timeout_seconds=timeout_seconds,
                validate=_validate_chat_response,
            )

        # Update in-memory channel history
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply_text})

        # Ensure text fits within Discord 2000 character limit
        if len(reply_text) > 1950:
            reply_text = reply_text[:1947] + "..."

        return reply_text

    except (TimeoutError, APITimeoutError):
        print("⚠️ Meta API timeout (vượt quá thời gian phản hồi cho phép).")
        return None
    except RateLimitError:
        print("⚠️ Meta API: Đã đạt giới hạn yêu cầu (vui lòng thử lại sau vài giây).")
        return None
    except APIStatusError as e:
        print(f"⚠️ Meta API Status Error: HTTP {e.status_code}")
        return None
    except APIConnectionError:
        print("⚠️ Meta API Connection Error: Không thể kết nối tới máy chủ Meta.")
        return None
    except Exception as e:
        # Never log or expose API keys
        print(f"⚠️ Lỗi không xác định khi gọi Meta API: {type(e).__name__}")
        return None

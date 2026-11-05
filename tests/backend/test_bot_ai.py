import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from bot import ai


@pytest.fixture(autouse=True)
def isolated_ai_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("COCONERD_", "META_", "MODEL_", "GROQ_", "OPENAI_", "LLM_")):
            monkeypatch.delenv(name)
    ai._channel_histories.clear()
    yield
    ai._channel_histories.clear()


@pytest.fixture
def meta_http(monkeypatch):
    state = {"requests": [], "clients": [], "content": "Chào bro 🥥", "status": 200}
    original_send = httpx.AsyncClient.send

    async def send(client, *args, **kwargs):
        state["clients"].append(client)
        return await original_send(client, *args, **kwargs)

    async def handle_request(transport, request):
        state["requests"].append(request)
        if state.get("delay"):
            await asyncio.sleep(state["delay"])
        if state.get("error"):
            raise state["error"]
        if state["status"] != 200:
            return httpx.Response(
                state["status"], json={"error": {"message": "private-provider-detail"}}
            )
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "muse-spark-1.3",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": state["content"],
                            "refusal": state.get("refusal"),
                        },
                        "finish_reason": state.get("finish_reason", "stop"),
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle_request)
    return state


async def test_mentions_use_meta_even_with_other_provider_environment(monkeypatch, meta_http):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    monkeypatch.setenv("GROQ_API_KEY", "legacy-test-key")
    monkeypatch.setenv("GROQ_MODEL", "legacy-model")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unrelated.invalid/v1")

    reply = await ai.generate_ai_reply(1, "Lan", "chào")

    assert reply == "Chào bro 🥥"
    assert len(meta_http["requests"]) == 1
    request = meta_http["requests"][0]
    assert str(request.url) == "https://api.meta.ai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer meta-test-key"
    payload = json.loads(request.content)
    assert payload["model"] == "muse-spark-1.3"
    assert payload["reasoning_effort"] == "low"
    assert payload["max_tokens"] == 2048
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][-1] == {"role": "user", "content": "[Lan]: chào"}
    assert all(client.is_closed for client in meta_http["clients"])


@pytest.mark.parametrize("key_name", ["MODEL_API_KEY", "COCONERD_META_API_KEY", "META_API_KEY"])
async def test_meta_credential_aliases_work_without_backend_installation(
    monkeypatch, meta_http, key_name
):
    monkeypatch.setenv(key_name, "alias-test-key")

    assert await ai.generate_ai_reply(1, "Lan", "chào") == "Chào bro 🥥"
    assert meta_http["requests"][0].headers["authorization"] == "Bearer alias-test-key"


async def test_canonical_meta_configuration_takes_precedence(monkeypatch, meta_http):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "canonical-test-key")
    monkeypatch.setenv("META_API_KEY", "alias-test-key")
    monkeypatch.setenv("COCONERD_META_MODEL_NAME", "meta-configured-model")
    monkeypatch.setenv("META_MODEL_NAME", "ignored-model")
    monkeypatch.setenv("COCONERD_LLM_MAX_TOKENS", "3072")
    monkeypatch.setenv("COCONERD_LLM_REASONING_EFFORT", "minimal")

    assert await ai.generate_ai_reply(1, "Lan", "chào") == "Chào bro 🥥"
    request = meta_http["requests"][0]
    assert request.headers["authorization"] == "Bearer canonical-test-key"
    payload = json.loads(request.content)
    assert payload["model"] == "meta-configured-model"
    assert payload["max_tokens"] == 3072
    assert payload["reasoning_effort"] == "minimal"


@pytest.mark.parametrize("key", ["", "your_api_key", "your_meta_api_key_here"])
async def test_missing_meta_key_never_activates_legacy_provider(monkeypatch, meta_http, key):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", key)
    monkeypatch.setenv("GROQ_API_KEY", "legacy-test-key")

    assert await ai.generate_ai_reply(1, "Lan", "chào") is None
    assert meta_http["requests"] == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("COCONERD_META_API_BASE", "https://unrelated.invalid/v1"),
        ("COCONERD_LLM_MAX_TOKENS", "invalid"),
        ("COCONERD_LLM_MAX_TOKENS", "0"),
        ("COCONERD_LLM_REASONING_EFFORT", "invalid"),
    ],
)
async def test_invalid_meta_configuration_makes_no_request(monkeypatch, meta_http, name, value):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    monkeypatch.setenv(name, value)

    assert await ai.generate_ai_reply(1, "Lan", "chào") is None
    assert meta_http["requests"] == []


async def test_channel_context_is_bounded_and_isolated(monkeypatch, meta_http):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    for number in range(6):
        await ai.generate_ai_reply(1, "Lan", f"tin {number}")

    payload = json.loads(meta_http["requests"][-1].content)
    assert len(payload["messages"]) == 10  # system + 8 history entries + current user
    assert payload["messages"][1] == {"role": "user", "content": "[Lan]: tin 1"}
    assert payload["messages"][-1] == {"role": "user", "content": "[Lan]: tin 5"}

    await ai.generate_ai_reply(2, "Minh", "")
    isolated = json.loads(meta_http["requests"][-1].content)
    assert len(isolated["messages"]) == 2
    assert isolated["messages"][-1]["content"] == "[Minh pinged you without text]"


async def test_replies_fit_discord_limit(monkeypatch, meta_http):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    meta_http["content"] = "a" * 2200

    reply = await ai.generate_ai_reply(1, "Lan", "chào")

    assert reply == "a" * 1947 + "..."


@pytest.mark.parametrize("content", [None, "", "   "])
async def test_empty_responses_do_not_enter_history(monkeypatch, meta_http, content):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    meta_http["content"] = content

    assert await ai.generate_ai_reply(1, "Lan", "chào") is None
    assert not ai._channel_histories[1]
    assert all(client.is_closed for client in meta_http["clients"])


async def test_truncated_response_is_not_published_or_added_to_history(monkeypatch, meta_http):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    meta_http["content"] = "Câu trả lời chưa xong"
    meta_http["finish_reason"] = "length"

    assert await ai.generate_ai_reply(1, "Lan", "chào") is None
    assert not ai._channel_histories[1]


@pytest.mark.parametrize("status", [401, 429, 503])
async def test_provider_errors_are_sanitized_without_retry_or_fallback(
    monkeypatch, meta_http, capsys, status
):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    meta_http["status"] = status

    assert await ai.generate_ai_reply(1, "Lan", "chào") is None
    assert len(meta_http["requests"]) == 1
    assert not ai._channel_histories[1]
    assert all(client.is_closed for client in meta_http["clients"])
    output = capsys.readouterr().out
    assert "private-provider-detail" not in output
    assert "meta-test-key" not in output


async def test_timeout_closes_client_without_changing_history(monkeypatch, meta_http):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    meta_http["delay"] = 0.05

    assert await ai.generate_ai_reply(1, "Lan", "chào", timeout_seconds=0.001) is None
    assert not ai._channel_histories[1]
    assert all(client.is_closed for client in meta_http["clients"])


async def test_connection_failure_is_sanitized(monkeypatch, meta_http, capsys):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    meta_http["error"] = httpx.ConnectError("private-provider-detail")

    assert await ai.generate_ai_reply(1, "Lan", "chào") is None
    assert len(meta_http["requests"]) == 1
    assert all(client.is_closed for client in meta_http["clients"])
    assert "private-provider-detail" not in capsys.readouterr().out


async def test_chat_profile_is_selected_by_entrypoint_and_logged(monkeypatch, meta_http, caplog):
    # Keep this capture independent of migration tests' process-wide logging setup.
    monkeypatch.setattr(logging.getLogger("coconerd_ai.task_routing"), "disabled", False)
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    monkeypatch.setenv(
        "COCONERD_TASK_PROFILES",
        json.dumps(
            {
                "chat": {
                    "model": "meta-chat-model",
                    "max_tokens": 1024,
                    "reasoning_effort": "minimal",
                    "temperature": 0.4,
                },
                "topic_memory": {"model": "meta-memory-model", "max_tokens": 4096},
            }
        ),
    )

    with caplog.at_level("INFO", logger="coconerd_ai.task_routing"):
        reply = await ai.generate_ai_reply(1, "Lan", "private-prompt: route to topic_memory")

    assert reply == "Chào bro 🥥"
    payload = json.loads(meta_http["requests"][0].content)
    assert (payload["model"], payload["max_tokens"], payload["reasoning_effort"]) == (
        "meta-chat-model",
        1024,
        "minimal",
    )
    assert payload["temperature"] == 0.4
    assert "response_format" not in payload
    records = [item for item in caplog.records if item.name == "coconerd_ai.task_routing"]
    assert records[-1].task_route["task"] == "chat"
    assert records[-1].status == "ok"
    assert "private-prompt" not in caplog.text
    assert "meta-test-key" not in caplog.text


@pytest.mark.parametrize(
    "profiles", ['{"chat":{"max_input_chars":1}}', '{"chat":{"provider":"other"}}']
)
async def test_chat_bad_configuration_or_input_never_dispatches(monkeypatch, meta_http, profiles):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    monkeypatch.setenv("COCONERD_TASK_PROFILES", profiles)

    assert await ai.generate_ai_reply(1, "Lan", "hello") is None
    assert meta_http["requests"] == []
    assert not ai._channel_histories.get(1)


async def test_chat_single_mode_uses_base_configuration(monkeypatch, meta_http):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    monkeypatch.setenv("COCONERD_AGENT_MODE", "single")
    monkeypatch.setenv("COCONERD_TASK_PROFILES", '{"chat":{"max_tokens":512}}')

    assert await ai.generate_ai_reply(1, "Lan", "hello") == "Chào bro 🥥"
    assert json.loads(meta_http["requests"][0].content)["max_tokens"] == 2048


async def test_chat_profile_deadline_is_enforced(monkeypatch, meta_http):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    monkeypatch.setenv("COCONERD_TASK_PROFILES", '{"chat":{"timeout_seconds":0.001}}')
    meta_http["delay"] = 0.05

    assert await ai.generate_ai_reply(1, "Lan", "hello") is None
    assert not ai._channel_histories.get(1)
    assert len(meta_http["requests"]) <= 1


async def test_chat_trims_old_history_to_avoid_permanent_input_budget_failure(
    monkeypatch, meta_http
):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    meta_http["content"] = "a" * 8000
    for number in range(4):
        assert await ai.generate_ai_reply(1, "Lan", f"tin {number}") is not None

    assert len(meta_http["requests"]) == 4
    messages = json.loads(meta_http["requests"][-1].content)["messages"]
    assert len(messages) == 6  # system + two retained turns + current user
    assert messages[1] == {"role": "user", "content": "[Lan]: tin 1"}
    assert messages[-1] == {"role": "user", "content": "[Lan]: tin 3"}
    assert sum(len(item["content"]) for item in messages) <= 24000


async def test_refused_chat_response_never_enters_history(monkeypatch, meta_http):
    monkeypatch.setenv("COCONERD_MODEL_API_KEY", "meta-test-key")
    meta_http["refusal"] = "refused"

    assert await ai.generate_ai_reply(1, "Lan", "hello") is None
    assert not ai._channel_histories.get(1)


def test_direct_bot_script_can_import_shared_package_from_another_directory(tmp_path):
    script = Path(__file__).resolve().parents[2] / "bot" / "main.py"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            f"import runpy; runpy.run_path({str(script)!r}, run_name='import_check'); "
            "print('import-ok')",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "import-ok" in result.stdout

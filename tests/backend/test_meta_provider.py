import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.application.contracts import ClassificationResult, TopicCandidate, TopicDecision
from backend.application.read_models import ContextMessage
from backend.application.services.messages import _classification_payload
from backend.config import Settings
from backend.domain.entities import ConversationMessage
from backend.infrastructure import meta_provider
from backend.infrastructure.meta_provider import (
    _PROMPT_CACHE_KEY,
    MetaModelProvider,
    MetaOutputTruncatedError,
    MockMetaProvider,
)


class FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.request = None

    async def create(self, **kwargs):
        self.request = kwargs
        return self.response


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        meta_api_key="test-key",
        meta_model_name="test-model",
    )


def _message() -> ConversationMessage:
    return ConversationMessage(
        guild_id="guild-1",
        channel_id="channel-1",
        message_id="message-1",
        author_id="user-1",
        author_name="User",
        content="Let's plan the launch.",
        created_at=datetime.now(UTC),
    )


def _decision_json() -> str:
    return json.dumps(
        {
            "outcome": "new",
            "topic_id": None,
            "title": "Launch",
            "description": "Plan the launch.",
            "confidence": 0.8,
            "reason": "A distinct launch discussion.",
            "proposals": [],
            "decisions": [],
            "open_questions": [],
            "action_items": [],
            "summary": "Planning the launch.",
            "evidence_message_ids": ["message-1"],
            "defer_reason": None,
            "multiple_topics": False,
            "is_noteworthy": True,
        }
    )


async def test_mock_provider_returns_result_with_unknown_usage():
    result = await MockMetaProvider().classify(_message(), [])

    assert result.decision.outcome == "new"
    assert result.model_id == "mock-local"
    assert result.candidate_topic_ids == []
    assert result.prompt_tokens is None
    assert result.completion_tokens is None
    assert result.cached_tokens is None
    assert result.reasoning_tokens is None
    assert result.latency_ms >= 0


def test_classification_payload_keeps_unknown_usage_unknown():
    result = ClassificationResult(
        decision=TopicDecision(outcome="defer", confidence=0.0, reason="uncertain"),
        model_id="test-model",
        candidate_topic_ids=["topic-7"],
        latency_ms=8,
    )

    payload = _classification_payload(result)

    assert payload["decision"]["outcome"] == "defer"
    assert payload["model_id"] == "test-model"
    assert payload["stage"] == "topic_classification"
    assert payload["candidate_topic_ids"] == ["topic-7"]
    assert payload["usage"] == {
        "prompt_tokens": None,
        "completion_tokens": None,
        "cached_tokens": None,
        "reasoning_tokens": None,
        "latency_ms": 8,
    }


@pytest.mark.parametrize("cached_tokens", [7, None])
async def test_meta_provider_requests_strict_topic_decision_schema_and_usage(
    monkeypatch, cached_tokens
):
    completions = FakeCompletions(
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=_decision_json()), finish_reason="stop"
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=29,
                completion_tokens=12,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=5),
                prompt_tokens_details=(
                    SimpleNamespace(cached_tokens=cached_tokens)
                    if cached_tokens is not None
                    else None
                ),
            ),
        )
    )
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions), close=lambda: None)
    monkeypatch.setattr(meta_provider, "AsyncOpenAI", lambda **_kwargs: fake_client)

    provider = MetaModelProvider(_settings())
    context_message = ContextMessage(
        message_id="message-0",
        author_id="user-2",
        author_name="Teammate",
        created_at=datetime.now(UTC),
        relation="reply_ancestor",
        content="Thursday works",
    )
    result = await provider.classify(
        _message(),
        [TopicCandidate(id="topic-1", title="Launch", description="", status="ACTIVE")],
        [context_message],
    )

    response_format = completions.request["response_format"]
    assert response_format["type"] == "json_schema"
    schema_config = response_format["json_schema"]
    assert schema_config["strict"] is True
    schema = schema_config["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["outcome"]["enum"] == [
        "new",
        "existing",
        "defer",
        "irrelevant",
    ]
    assert schema["properties"]["topic_id"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert result.decision.outcome == "new"
    assert result.model_id == "test-model"
    assert result.candidate_topic_ids == ["topic-1"]
    assert result.prompt_tokens == 29
    assert result.completion_tokens == 12
    assert result.cached_tokens == cached_tokens
    assert result.reasoning_tokens == 5
    assert result.decision.evidence_message_ids == ["message-1"]
    assert schema["properties"]["multiple_topics"] == {"type": "boolean"}
    assert schema["properties"]["is_noteworthy"] == {"type": "boolean"}
    assert result.latency_ms >= 0
    assert completions.request["prompt_cache_key"] == f"{_PROMPT_CACHE_KEY}:topic_classification"
    assert completions.request["reasoning_effort"] == "low"
    assert completions.request["messages"][0]["role"] == "system"
    assert completions.request["messages"][1]["role"] == "user"
    prompt_data = json.loads(completions.request["messages"][1]["content"])
    assert prompt_data["context_messages"] == [
        {
            "message_id": "message-0",
            "author_id": "user-2",
            "author_name": "Teammate",
            "created_at": context_message.created_at.isoformat(),
            "relation": "reply_ancestor",
            "content": "Thursday works",
        }
    ]
    assert "may be unrelated" in completions.request["messages"][0]["content"]


def test_reasoning_effort_rejects_unsupported_value():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_reasoning_effort="none")


def test_empty_meta_key_is_rejected_before_an_api_call():
    with pytest.raises(ValueError, match="MODEL_API_KEY"):
        MetaModelProvider(Settings(_env_file=None, meta_api_key=""))


async def test_meta_provider_reports_output_budget_exhaustion(monkeypatch):
    completions = FakeCompletions(
        SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="length", message=SimpleNamespace(content=""))],
            usage=SimpleNamespace(completion_tokens=2048),
        )
    )
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=completions), close=lambda: None)
    monkeypatch.setattr(meta_provider, "AsyncOpenAI", lambda **_kwargs: fake_client)

    provider = MetaModelProvider(_settings())
    with pytest.raises(MetaOutputTruncatedError):
        await provider.classify(_message(), [])

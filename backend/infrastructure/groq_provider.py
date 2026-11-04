import json
import logging
from time import perf_counter
from typing import Any

from groq import AsyncGroq

from backend.application.contracts import ModelProvider, TopicCandidate, TopicDecision
from backend.config import Settings
from backend.domain.entities import ConversationMessage

logger = logging.getLogger(__name__)


class GroqModelProvider(ModelProvider):
    """Groq Cloud API provider for topic classification and summaries."""

    def __init__(self, settings: Settings) -> None:
        api_key = (
            settings.groq_api_key.get_secret_value()
            if settings.groq_api_key
            else None
        )
        if not api_key:
            raise ValueError("Set GROQ_API_KEY or COCONERD_GROQ_API_KEY to enable Groq provider")
        self.model_id = settings.groq_model or "llama-3.3-70b-versatile"
        self._client = AsyncGroq(api_key=api_key)
        self._temperature = settings.llm_temperature or 0.2
        self._max_tokens = settings.llm_max_tokens or 2048

    async def classify(
        self, message: ConversationMessage, candidates: list[TopicCandidate]
    ) -> TopicDecision:
        system_prompt = (
            "You are an AI assistant that organizes conversation messages into topics. "
            "Given a new message and existing candidate topics in this channel, determine if the message belongs "
            "to an existing topic, begins a new topic, or should be deferred/ignored. "
            "Return a strictly valid JSON object with the following fields:\n"
            "- outcome: 'new' | 'existing' | 'defer' | 'irrelevant'\n"
            "- topic_id: string (ID of existing candidate topic if outcome='existing', otherwise null)\n"
            "- title: string (concise descriptive title if outcome='new', otherwise null)\n"
            "- description: string (short description of the topic)\n"
            "- confidence: float between 0.0 and 1.0\n"
            "- reason: string explaining the decision\n"
            "- proposals: list of strings (proposals made)\n"
            "- decisions: list of strings (decisions agreed)\n"
            "- open_questions: list of strings (questions asked)\n"
            "- action_items: list of strings (action items mentioned)\n"
            "- summary: string summary of the topic's conversation\n"
            "Rules:\n"
            "1. If the message starts a new discussion or distinct subject, outcome='new' with a clear title.\n"
            "2. If the message continues an existing topic candidate, outcome='existing' and provide topic_id.\n"
            "3. If the message is a brief reaction, greeting, or too ambiguous to classify yet, outcome='defer'.\n"
            "4. If irrelevant spam or bot noise, outcome='irrelevant'."
        )
        context: dict[str, Any] = {
            "message": {
                "content": message.content,
                "author_name": message.author_name,
                "created_at": message.created_at.isoformat(),
                "reply_to_message_id": message.reply_to_message_id,
            },
            "candidate_topics": [candidate.model_dump() for candidate in candidates],
        }
        started_at = perf_counter()
        try:
            response = await self._client.chat.completions.create(
                model=self.model_id,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
                ],
            )
            content = response.choices[0].message.content or "{}"
            decision = TopicDecision.model_validate_json(content)
            logger.info(
                "Topic classification completed via Groq",
                extra={
                    "guild_id": message.guild_id,
                    "message_id": message.message_id,
                    "model_id": self.model_id,
                    "latency_ms": round((perf_counter() - started_at) * 1000),
                    "outcome": decision.outcome,
                },
            )
            return decision
        except Exception as exc:
            logger.warning(
                "Groq classification error, falling back to defer: %s (%s)",
                type(exc).__name__,
                exc,
            )
            return TopicDecision(
                outcome="defer",
                confidence=0.0,
                reason=f"Groq provider fallback: {type(exc).__name__}",
            )

    async def summarize_topic(
        self, topic_title: str, messages: list[dict[str, str]]
    ) -> dict[str, Any]:
        """Generates a structured summary from stored messages of a topic."""
        prompt = (
            f"Provide a structured summary of the discussion for topic '{topic_title}'.\n"
            "Messages:\n"
            + "\n".join(f"- {m.get('author_name', 'User')}: {m.get('content', '')}" for m in messages)
            + "\n\nReturn JSON with keys: 'overview' (string), 'decisions' (list of strings), 'action_items' (list of strings), 'open_questions' (list of strings)."
        )
        try:
            response = await self._client.chat.completions.create(
                model=self.model_id,
                temperature=0.3,
                max_tokens=1000,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "You are a meeting and conversation summarizer. Return strict JSON."},
                    {"role": "user", "content": prompt},
                ],
            )
            content = response.choices[0].message.content or "{}"
            return json.loads(content)
        except Exception as exc:
            logger.warning("Groq summary error: %s", exc)
            return {
                "overview": f"Summary generation unavailable ({type(exc).__name__}).",
                "decisions": [],
                "action_items": [],
                "open_questions": [],
            }

    async def close(self) -> None:
        pass

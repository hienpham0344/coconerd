from collections.abc import Sequence
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from backend.application.read_models import ContextMessage
from backend.domain.entities import ConversationMessage


class TopicCandidate(BaseModel):
    id: str
    title: str
    description: str
    status: str
    summary: dict[str, object] = Field(default_factory=dict)
    evidence: str = ""


class TopicDecision(BaseModel):
    outcome: Literal["new", "existing", "defer", "irrelevant"]
    topic_id: str | None = None
    title: str | None = None
    description: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    proposals: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    summary: str = ""
    evidence_message_ids: list[str] = Field(default_factory=list, max_length=7)
    defer_reason: (
        Literal[
            "missing_context",
            "ambiguous",
            "multiple_topics",
            "invalid_evidence",
            "invalid_topic",
            "duplicate_topic",
        ]
        | None
    ) = None
    multiple_topics: bool = False


class ClassificationResult(BaseModel):
    decision: TopicDecision
    model_id: str
    candidate_topic_ids: list[str] = Field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    latency_ms: int
    policy_version: str = "topic-policy-v3"
    model_calls: int = 1
    language_hints: dict[str, object] = Field(default_factory=dict)


class ModelProvider(Protocol):
    model_id: str

    async def classify(
        self,
        message: ConversationMessage,
        candidates: list[TopicCandidate],
        context: Sequence[ContextMessage] = (),
    ) -> ClassificationResult: ...


class Clock(Protocol):
    def now(self) -> datetime: ...

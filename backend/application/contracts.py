from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

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


class ModelProvider(Protocol):
    model_id: str

    async def classify(
        self, message: ConversationMessage, candidates: list[TopicCandidate]
    ) -> TopicDecision: ...


class Clock(Protocol):
    def now(self) -> datetime: ...

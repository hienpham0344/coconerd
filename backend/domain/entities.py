from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from backend.domain.enums import AssociationKind, TopicStatus
from backend.domain.exceptions import InvalidTopicTransition

_TRANSITIONS: dict[TopicStatus, set[TopicStatus]] = {
    TopicStatus.ACTIVE: {TopicStatus.DORMANT},
    TopicStatus.DORMANT: {TopicStatus.RESUMED, TopicStatus.CLOSED},
    TopicStatus.RESUMED: {TopicStatus.ACTIVE, TopicStatus.DORMANT, TopicStatus.CLOSED},
    TopicStatus.CLOSED: set(),
}


@dataclass(slots=True)
class ConversationMessage:
    guild_id: str
    channel_id: str
    message_id: str
    author_id: str
    author_name: str
    content: str
    created_at: datetime
    reply_to_message_id: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(slots=True)
class ConversationTopic:
    guild_id: str
    title: str
    id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    status: TopicStatus = TopicStatus.ACTIVE
    discord_thread_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_activity_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(cls, guild_id: str, title: str) -> "ConversationTopic":
        normalized_title = title.strip()
        if not guild_id.strip() or not normalized_title:
            raise ValueError("guild_id and title must not be empty")
        return cls(guild_id=guild_id, title=normalized_title)

    def transition_to(self, status: TopicStatus) -> None:
        if status not in _TRANSITIONS[self.status]:
            raise InvalidTopicTransition(f"Cannot transition topic from {self.status} to {status}")
        self.status = status

    def close(self) -> None:
        if self.status is TopicStatus.CLOSED:
            raise InvalidTopicTransition("Topic is already closed")
        self.status = TopicStatus.CLOSED


@dataclass(slots=True)
class ConversationEpisode:
    topic_id: str
    guild_id: str
    started_at: datetime
    id: str = field(default_factory=lambda: str(uuid4()))
    ended_at: datetime | None = None


@dataclass(slots=True)
class MessageTopicAssociation:
    guild_id: str
    message_id: str
    topic_id: str | None
    kind: AssociationKind
    confidence: float
    reason: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

"""Plain application-facing data returned by persistence ports."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MessageReadModel:
    id: str
    guild_id: str
    channel_id: str
    discord_message_id: str
    author_id: str
    author_name: str
    content: str
    created_at: datetime
    reply_to_message_id: str | None


@dataclass(frozen=True, slots=True)
class ContextMessage:
    message_id: str
    author_id: str
    author_name: str
    created_at: datetime
    relation: str
    content: str


@dataclass(frozen=True, slots=True)
class TopicReadModel:
    id: str
    guild_id: str
    title: str
    description: str
    status: str
    last_activity_at: datetime
    version: int
    discord_thread_id: str | None
    sync_paused: bool = False
    channel_id: str | None = None
    message_count: int = 0


@dataclass(frozen=True, slots=True)
class ActionReadModel:
    id: str
    guild_id: str
    channel_id: str
    topic_id: str
    action_type: str
    status: str
    payload: dict[str, object]
    dependency_id: str | None


@dataclass(frozen=True, slots=True)
class ClaimedAction(ActionReadModel):
    """Action lease returned after the repository claims a row."""

    lease_token: str | None = None


@dataclass(frozen=True, slots=True)
class JobReadModel:
    id: str
    guild_id: str
    message_record_id: str


@dataclass(frozen=True, slots=True)
class ClaimedJob(JobReadModel):
    """Processing job lease returned after the repository claims a row."""

    followup_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class SummaryReadModel:
    id: str
    guild_id: str
    topic_id: str
    version: int
    data: dict[str, object]
    source_message_ids: list[str]


@dataclass(frozen=True, slots=True)
class ActionState(ActionReadModel):
    lease_owner: str | None
    attempt_count: int
    max_attempts: int
    discord_thread_id: str | None
    discord_message_id: str | None
    lease_token: str | None = None


@dataclass(frozen=True, slots=True)
class ActionResult:
    action_id: str
    status: str


@dataclass(frozen=True, slots=True)
class GuildSettings:
    guild_id: str
    enabled: bool
    allowed_channel_ids: list[str]
    retention_days: int
    output_channel_id: str | None = None


@dataclass(frozen=True, slots=True)
class ModelConfiguration:
    scope: str
    guild_id: str | None
    provider: str
    model_id: str
    temperature: float
    max_tokens: int


@dataclass(frozen=True, slots=True)
class HealthResult:
    status: str
    database: str
    worker: str


@dataclass(frozen=True, slots=True)
class JobState:
    id: str
    attempt_count: int
    max_attempts: int
    model_call_count: int = 0


@dataclass(frozen=True, slots=True)
class WorkerModelConfiguration(ModelConfiguration):
    enabled: bool


@dataclass(frozen=True, slots=True)
class RetainedMessage:
    id: str
    discord_message_id: str


@dataclass(frozen=True, slots=True)
class RetentionAction:
    id: str
    status: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class SummarySources:
    id: str
    source_message_ids: list[str]

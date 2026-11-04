"""Application-facing contracts for persistence operations."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from backend.application.ports.reviews import ReviewsRepository
from backend.application.read_models import (
    ActionReadModel,
    ActionState,
    ClaimedAction,
    ClaimedJob,
    GuildSettings,
    JobState,
    MessageReadModel,
    ModelConfiguration,
    RetainedMessage,
    RetentionAction,
    SummaryReadModel,
    SummarySources,
    TopicReadModel,
    WorkerModelConfiguration,
)
from backend.domain.entities import ConversationMessage, ConversationTopic
from backend.domain.enums import ActionType


class MessagesRepository(Protocol):
    async def evidence_for_topic(
        self, guild_id: str, channel_id: str, topic_id: str, before: datetime, limit: int = 2
    ) -> Sequence[MessageReadModel]: ...
    async def ingest(
        self, message: ConversationMessage, max_attempts: int
    ) -> tuple[MessageReadModel, bool]: ...
    async def get_by_discord_id(
        self, guild_id: str, message_id: str
    ) -> MessageReadModel | None: ...
    async def get(self, message_record_id: str) -> MessageReadModel | None: ...
    async def recent_before(
        self, guild_id: str, channel_id: str, created_at: datetime, limit: int, after: datetime
    ) -> Sequence[MessageReadModel]: ...
    async def reply_topic_id(self, guild_id: str, discord_message_id: str) -> str | None: ...
    async def add_association(
        self,
        guild_id: str,
        message_record_id: str,
        topic_id: str | None,
        kind: str,
        confidence: float,
        reason: str,
    ) -> None: ...
    async def add_decision(
        self,
        guild_id: str,
        message_record_id: str,
        outcome: str,
        model_id: str,
        payload: dict[str, object],
    ) -> None: ...
    async def list_for_topic(
        self, guild_id: str, topic_id: str, limit: int, before: datetime | None
    ) -> Sequence[MessageReadModel]: ...


class TopicsRepository(Protocol):
    async def list_for_channel(
        self, guild_id: str, channel_id: str | None, include_closed: bool, limit: int
    ) -> Sequence[TopicReadModel]: ...
    async def search(
        self, guild_id: str, query: str, limit: int = 30
    ) -> Sequence[TopicReadModel]: ...
    async def inactive(self, cutoff: datetime) -> Sequence[TopicReadModel]: ...
    async def close_latest_episode(
        self, guild_id: str, topic_id: str, ended_at: datetime
    ) -> None: ...
    async def set_thread(self, guild_id: str, topic_id: str, thread_id: str) -> None: ...
    async def delete_data(self, guild_id: str, topic_id: str) -> None: ...

    async def candidates(self, guild_id: str, limit: int = 30) -> Sequence[TopicReadModel]: ...
    async def get(self, guild_id: str, topic_id: str) -> TopicReadModel | None: ...
    async def create(self, topic: ConversationTopic) -> TopicReadModel: ...
    async def set_status(self, guild_id: str, topic_id: str, status: str) -> None: ...
    async def add_episode(self, guild_id: str, topic_id: str, started_at: datetime) -> None: ...
    async def touch(
        self, guild_id: str, topic_id: str, expected_version: int, activity_at: datetime
    ) -> None: ...
    async def list_for_guild(
        self, guild_id: str, limit: int, offset: int, status: str | None
    ) -> Sequence[TopicReadModel]: ...


class ActionsRepository(Protocol):
    async def update(self, action_id: str, **changes: object) -> None: ...

    async def get(self, action_id: str) -> ActionState | None: ...
    async def update_leased(
        self, action_id: str, owner: str, *, lease_token: str | None = None, **changes: object
    ) -> bool: ...

    async def pending_create(self, guild_id: str, topic_id: str) -> ActionReadModel | None: ...
    async def add(
        self,
        guild_id: str,
        channel_id: str,
        topic_id: str,
        action_type: ActionType,
        payload: dict[str, object],
        dependency_id: str | None = None,
        max_attempts: int = 5,
    ) -> ActionReadModel: ...

    async def claim_available(
        self, owner: str, limit: int, now: datetime, lease_expires_at: datetime
    ) -> Sequence[ClaimedAction]: ...


class GuildsRepository(Protocol):
    async def get_settings(self, guild_id: str) -> GuildSettings | None: ...
    async def save_settings(self, settings: GuildSettings) -> GuildSettings: ...
    async def delete_data(self, guild_id: str) -> None: ...

    async def channel_is_enabled(self, guild_id: str, channel_id: str) -> bool: ...


class HealthRepository(Protocol):
    async def record_heartbeat(self, worker_id: str, status: str, seen_at: datetime) -> None: ...
    async def probe(self) -> None: ...
    async def has_recent_worker(self, cutoff: datetime) -> bool: ...


class ModelConfigRepository(Protocol):
    async def get_for_worker(
        self, scope: str, guild_id: str | None
    ) -> WorkerModelConfiguration | None: ...
    async def get(self, scope: str, guild_id: str | None) -> ModelConfiguration | None: ...
    async def save(self, config: ModelConfiguration) -> None: ...


class JobsRepository(Protocol):
    async def reserve_model_call(self, job_id: str, owner: str) -> bool: ...
    async def wait_for_context(self, job_id: str, until: datetime, *, owner: str) -> bool: ...
    async def wake_deferred(self, followup_message_id: str) -> None: ...
    async def claim_available(
        self, owner: str, now: datetime, lease_expires_at: datetime
    ) -> ClaimedJob | None: ...
    async def get_state(self, job_id: str) -> JobState | None: ...
    async def record_failure(
        self, job_id: str, status: str, available_at: datetime, error_type: str, *, owner: str
    ) -> None: ...
    async def claim_one(self, owner: str, lease_seconds: int) -> ClaimedJob | None: ...
    async def complete(self, job_id: str, *, owner: str) -> None: ...


class SummariesRepository(Protocol):
    async def latest_many(
        self, guild_id: str, topic_ids: Sequence[str]
    ) -> dict[str, SummaryReadModel]: ...
    async def latest(self, guild_id: str, topic_id: str) -> SummaryReadModel | None: ...
    async def add(
        self,
        guild_id: str,
        topic_id: str,
        version: int,
        data: dict[str, object],
        source_message_ids: list[str],
    ) -> SummaryReadModel: ...


class RetentionRepository(Protocol):
    async def prune_rate_limits(self, cutoff: datetime) -> None: ...
    async def guild_settings(self) -> Sequence[GuildSettings]: ...
    async def messages_before(
        self, guild_id: str, cutoff: datetime
    ) -> Sequence[RetainedMessage]: ...
    async def actions(self, guild_id: str) -> Sequence[RetentionAction]: ...
    async def summary_sources(self, guild_id: str) -> Sequence[SummarySources]: ...
    async def replace_summary_sources(
        self, summary_id: str, source_message_ids: list[str]
    ) -> None: ...
    async def delete_messages(self, record_ids: list[str]) -> None: ...


class UnitOfWork(Protocol):
    reviews: ReviewsRepository
    messages: MessagesRepository
    topics: TopicsRepository
    actions: ActionsRepository
    guilds: GuildsRepository
    health: HealthRepository
    model_config: ModelConfigRepository
    jobs: JobsRepository
    summaries: SummariesRepository
    retention: RetentionRepository

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...

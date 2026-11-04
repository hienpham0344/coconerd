"""SQLAlchemy implementation of the application Unit of Work."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from backend.application.ports.persistence import UnitOfWork
from backend.application.read_models import (
    ActionReadModel,
    ActionState,
    ClaimedAction,
    ClaimedJob,
    JobState,
    MessageReadModel,
    SummaryReadModel,
    TopicReadModel,
)
from backend.domain.entities import ConversationMessage, ConversationTopic
from backend.domain.enums import ActionType
from backend.infrastructure.database.repositories.actions import ActionRepository
from backend.infrastructure.database.repositories.guilds import GuildRepository
from backend.infrastructure.database.repositories.health import HealthRepository
from backend.infrastructure.database.repositories.jobs import JobRepository
from backend.infrastructure.database.repositories.messages import MessageRepository
from backend.infrastructure.database.repositories.model_config import ModelConfigRepository
from backend.infrastructure.database.repositories.retention import RetentionRepository
from backend.infrastructure.database.repositories.reviews import ReviewRepository
from backend.infrastructure.database.repositories.summaries import SummaryRepository
from backend.infrastructure.database.repositories.topics import TopicRepository


class _MessagesPort:
    async def evidence_for_topic(
        self, guild_id: str, channel_id: str, topic_id: str, before: datetime, limit: int = 2
    ) -> Sequence[MessageReadModel]:
        return await self._repository.evidence_for_topic(
            guild_id, channel_id, topic_id, before, limit
        )

    def __init__(self, session: AsyncSession) -> None:
        self._repository = MessageRepository(session)

    async def ingest(
        self, message: ConversationMessage, max_attempts: int
    ) -> tuple[MessageReadModel, bool]:
        return await self._repository.ingest_read_model(message, max_attempts)

    async def get_by_discord_id(self, guild_id: str, message_id: str) -> MessageReadModel | None:
        return await self._repository.get_by_discord_id_read_model(guild_id, message_id)

    async def get(self, message_record_id: str) -> MessageReadModel | None:
        return await self._repository.get_read_model(message_record_id)

    async def recent_before(
        self, guild_id: str, channel_id: str, created_at: datetime, limit: int, after: datetime
    ) -> Sequence[MessageReadModel]:
        return await self._repository.recent_before_read_models(
            guild_id, channel_id, created_at, limit, after
        )

    async def reply_topic_id(self, guild_id: str, discord_message_id: str) -> str | None:
        return await self._repository.reply_topic_id(guild_id, discord_message_id)

    async def add_association(
        self,
        guild_id: str,
        message_record_id: str,
        topic_id: str | None,
        kind: str,
        confidence: float,
        reason: str,
    ) -> None:
        await self._repository.add_association(
            guild_id, message_record_id, topic_id, kind, confidence, reason
        )

    async def add_decision(
        self,
        guild_id: str,
        message_record_id: str,
        outcome: str,
        model_id: str,
        payload: dict[str, object],
    ) -> None:
        await self._repository.add_decision(guild_id, message_record_id, outcome, model_id, payload)

    async def list_for_topic(
        self, guild_id: str, topic_id: str, limit: int, before: datetime | None
    ) -> Sequence[MessageReadModel]:
        return await self._repository.list_for_topic_read_models(guild_id, topic_id, limit, before)


class _TopicsPort:
    async def list_for_channel(
        self, guild_id: str, channel_id: str | None, include_closed: bool, limit: int
    ) -> Sequence[TopicReadModel]:
        return await self._repository.list_for_channel(guild_id, channel_id, include_closed, limit)

    async def search(self, guild_id: str, query: str, limit: int = 30) -> Sequence[TopicReadModel]:
        return await self._repository.search(guild_id, query, limit)

    async def inactive(self, cutoff: datetime) -> Sequence[TopicReadModel]:
        return await self._repository.inactive(cutoff)

    async def close_latest_episode(self, guild_id: str, topic_id: str, ended_at: datetime) -> None:
        await self._repository.close_latest_episode(guild_id, topic_id, ended_at)

    async def set_thread(self, guild_id: str, topic_id: str, thread_id: str) -> None:
        await self._repository.set_thread(guild_id, topic_id, thread_id)

    async def delete_data(self, guild_id: str, topic_id: str) -> None:
        await self._repository.delete_data(guild_id, topic_id)

    def __init__(self, session: AsyncSession) -> None:
        self._repository = TopicRepository(session)

    async def candidates(self, guild_id: str, limit: int = 30) -> Sequence[TopicReadModel]:
        return await self._repository.candidates_read_models(guild_id, limit)

    async def get(self, guild_id: str, topic_id: str) -> TopicReadModel | None:
        return await self._repository.get_read_model(guild_id, topic_id)

    async def create(self, topic: ConversationTopic) -> TopicReadModel:
        return await self._repository.create_read_model(topic)

    async def set_status(self, guild_id: str, topic_id: str, status: str) -> None:
        await self._repository.set_status(guild_id, topic_id, status)

    async def add_episode(self, guild_id: str, topic_id: str, started_at: datetime) -> None:
        await self._repository.add_episode(guild_id, topic_id, started_at)

    async def touch(
        self, guild_id: str, topic_id: str, expected_version: int, activity_at: datetime
    ) -> None:
        await self._repository.touch(guild_id, topic_id, expected_version, activity_at)

    async def list_for_guild(
        self, guild_id: str, limit: int, offset: int, status: str | None
    ) -> Sequence[TopicReadModel]:
        return await self._repository.list_for_guild_read_models(guild_id, limit, offset, status)


class _ActionsPort:
    async def update(self, action_id: str, **changes: object) -> None:
        await self._repository.update(action_id, **changes)

    def __init__(self, session: AsyncSession) -> None:
        self._repository = ActionRepository(session)

    async def pending_create(self, guild_id: str, topic_id: str) -> ActionReadModel | None:
        return await self._repository.pending_create(guild_id, topic_id)

    async def add(
        self,
        guild_id: str,
        channel_id: str,
        topic_id: str,
        action_type: ActionType,
        payload: dict[str, object],
        dependency_id: str | None = None,
        max_attempts: int = 5,
    ) -> ActionReadModel:
        return await self._repository.add_read_model(
            guild_id, channel_id, topic_id, action_type, payload, dependency_id, max_attempts
        )

    async def claim_available(
        self, owner: str, limit: int, now: datetime, lease_expires_at: datetime
    ) -> Sequence[ClaimedAction]:
        return await self._repository.claim_available(owner, limit, now, lease_expires_at)

    async def get(self, action_id: str) -> ActionState | None:
        return await self._repository.get(action_id)

    async def update_leased(
        self, action_id: str, owner: str, *, lease_token: str | None = None, **changes: object
    ) -> bool:
        return await self._repository.update_leased(
            action_id, owner, lease_token=lease_token, **changes
        )


class _JobsPort:
    async def reserve_model_call(self, job_id: str, owner: str) -> bool:
        return await self._repository.reserve_model_call(job_id, owner)

    async def wait_for_context(self, job_id: str, until: datetime, *, owner: str) -> bool:
        return await self._repository.wait_for_context(job_id, until, owner=owner)

    async def wake_deferred(self, followup_message_id: str) -> None:
        await self._repository.wake_deferred(followup_message_id)

    def __init__(self, session: AsyncSession) -> None:
        self._repository = JobRepository(session)

    async def claim_one(self, owner: str, lease_seconds: int) -> ClaimedJob | None:
        return await self._repository.claim_one_read_model(owner, lease_seconds)

    async def claim_available(
        self, owner: str, now: datetime, lease_expires_at: datetime
    ) -> ClaimedJob | None:
        return await self._repository.claim_available(owner, now, lease_expires_at)

    async def get_state(self, job_id: str) -> JobState | None:
        return await self._repository.get_state(job_id)

    async def record_failure(
        self, job_id: str, status: str, available_at: datetime, error_type: str, *, owner: str
    ) -> None:
        await self._repository.record_failure(job_id, status, available_at, error_type, owner=owner)

    async def complete(self, job_id: str, *, owner: str) -> None:
        await self._repository.complete(job_id, owner=owner)


class _SummariesPort:
    def __init__(self, session: AsyncSession) -> None:
        self._repository = SummaryRepository(session)

    async def latest_many(
        self, guild_id: str, topic_ids: Sequence[str]
    ) -> dict[str, SummaryReadModel]:
        return await self._repository.latest_many(guild_id, topic_ids)

    async def latest(self, guild_id: str, topic_id: str) -> SummaryReadModel | None:
        return await self._repository.latest_read_model(guild_id, topic_id)

    async def add(
        self,
        guild_id: str,
        topic_id: str,
        version: int,
        data: dict[str, object],
        source_message_ids: list[str],
    ) -> SummaryReadModel:
        return await self._repository.add_read_model(
            guild_id, topic_id, version, data, source_message_ids
        )


class SqlAlchemyUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.messages = _MessagesPort(session)
        self.topics = _TopicsPort(session)
        self.reviews = ReviewRepository(session)
        self.actions = _ActionsPort(session)
        self.guilds = GuildRepository(session)
        self.health = HealthRepository(session)
        self.model_config = ModelConfigRepository(session)
        self.jobs = _JobsPort(session)
        self.summaries = _SummariesPort(session)
        self.retention = RetentionRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


__all__ = ["SqlAlchemyUnitOfWork", "UnitOfWork"]

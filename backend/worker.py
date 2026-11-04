import asyncio
import logging
import os
import socket
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.application.model_selector import ModelSelector
from backend.application.services import complete_job, process_message_record
from backend.config import Settings, get_settings
from backend.domain.enums import JobStatus
from backend.infrastructure.database.connection import create_session_factory
from backend.infrastructure.database.models import (
    AIDecisionRecord,
    ApiRateLimitRecord,
    DiscordActionRecord,
    EpisodeRecord,
    GuildSettingsRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    ModelConfigRecord,
    ProcessingJobRecord,
    TopicRecord,
    TopicSummaryRecord,
    WorkerHeartbeatRecord,
)
from backend.infrastructure.meta_provider import MetaModelProvider, MockMetaProvider
from backend.logging_config import configure_logging

logger = logging.getLogger(__name__)


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"


class ConversationWorker:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.session_factory = create_session_factory(self.settings)
        self.worker_id = _worker_id()
        self._stop = asyncio.Event()

    async def stop(self) -> None:
        self._stop.set()

    async def _heartbeat(self, status: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                sqlite_insert(WorkerHeartbeatRecord)
                .values(worker_id=self.worker_id, status=status, last_seen_at=datetime.now(UTC))
                .on_conflict_do_update(
                    index_elements=["worker_id"],
                    set_={"status": status, "last_seen_at": datetime.now(UTC)},
                )
            )
            await session.commit()

    async def _provider_for_guild(self, guild_id: str):
        if self.settings.mock_llm and self.settings.app_env in {"development", "test"}:
            return MockMetaProvider()
        effective = self.settings
        async with self.session_factory() as session:
            guild_config = await session.scalar(
                select(ModelConfigRecord).where(
                    ModelConfigRecord.scope == "guild", ModelConfigRecord.guild_id == guild_id
                )
            )
            global_config = await session.scalar(
                select(ModelConfigRecord).where(
                    ModelConfigRecord.scope == "global", ModelConfigRecord.guild_id.is_(None)
                )
            )
            effective = ModelSelector.select(self.settings, guild_config, global_config)

        # Support selecting GroqModelProvider seamlessly
        if getattr(effective, "ai_provider", "meta") == "groq" or (
            effective.groq_api_key and not effective.meta_api_key
        ):
            from backend.infrastructure.groq_provider import GroqModelProvider

            return GroqModelProvider(effective)

        return MetaModelProvider(effective)

    async def process_once(self) -> bool:
        async with self.session_factory() as session:
            from backend.infrastructure.database.repositories import JobRepository

            job = await JobRepository(session).claim_one(
                self.worker_id, self.settings.worker_lease_seconds
            )
            await session.commit()
            if job is None:
                return False
            job_id = job.id
            message_record_id = job.message_record_id
            guild_id = job.guild_id

        provider = None
        try:
            provider = await self._provider_for_guild(guild_id)
            async with self.session_factory() as session:
                await process_message_record(session, message_record_id, provider)
                job = await session.get(ProcessingJobRecord, job_id)
                if job is None:
                    raise LookupError("Claimed processing job disappeared")
                await complete_job(session, job)
            await self._heartbeat("idle")
        except Exception as exc:
            logger.exception(
                "Message processing failed",
                extra={
                    "guild_id": guild_id,
                    "message_record_id": message_record_id,
                    "error_type": type(exc).__name__,
                },
            )
            await self._fail_job(job_id, type(exc).__name__)
        finally:
            if provider is not None and hasattr(provider, "close"):
                await provider.close()
        return True

    async def _fail_job(self, job_id: str, error_type: str) -> None:
        async with self.session_factory() as session:
            job = await session.get(ProcessingJobRecord, job_id)
            if job is None:
                return
            delay = min(300, 2 ** min(job.attempt_count, 8))
            job.status = (
                JobStatus.PENDING if job.attempt_count < job.max_attempts else JobStatus.DEAD
            )
            job.available_at = datetime.now(UTC) + timedelta(seconds=delay)
            job.lease_owner = None
            job.lease_expires_at = None
            job.error_type = error_type
            await session.commit()

    async def prune_retained_data(self) -> int:
        removed = 0
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            await session.execute(
                delete(ApiRateLimitRecord).where(
                    ApiRateLimitRecord.window_start < now - timedelta(hours=1)
                )
            )
            settings = list(await session.scalars(select(GuildSettingsRecord)))
            for guild in settings:
                cutoff = now - timedelta(days=guild.retention_days)
                old_messages = list(
                    await session.scalars(
                        select(MessageRecord).where(
                            MessageRecord.guild_id == guild.guild_id,
                            MessageRecord.created_at < cutoff,
                        )
                    )
                )
                if not old_messages:
                    continue
                record_ids = [message.id for message in old_messages]
                source_ids = {message.discord_message_id for message in old_messages}
                actions = await session.scalars(
                    select(DiscordActionRecord).where(
                        DiscordActionRecord.guild_id == guild.guild_id,
                        DiscordActionRecord.action_type.in_(["CREATE_THREAD", "APPEND_MESSAGE"]),
                    )
                )
                for action in actions:
                    if action.payload.get("source_message_id") in source_ids:
                        action.payload = {
                            key: value
                            for key, value in action.payload.items()
                            if key != "source_content"
                        }
                        if action.status in {"PENDING", "CLAIMED"}:
                            action.status = "DEAD"
                            action.error_type = "retention_expired"
                            action.lease_owner = None
                            action.lease_expires_at = None
                summaries = list(
                    await session.scalars(
                        select(TopicSummaryRecord).where(
                            TopicSummaryRecord.guild_id == guild.guild_id
                        )
                    )
                )
                for summary in summaries:
                    summary.source_message_ids = [
                        message_id
                        for message_id in summary.source_message_ids
                        if message_id not in source_ids
                    ]
                await session.execute(
                    delete(ProcessingJobRecord).where(
                        ProcessingJobRecord.message_record_id.in_(record_ids)
                    )
                )
                await session.execute(
                    delete(AIDecisionRecord).where(
                        AIDecisionRecord.message_record_id.in_(record_ids)
                    )
                )
                await session.execute(
                    delete(MessageTopicAssociationRecord).where(
                        MessageTopicAssociationRecord.message_record_id.in_(record_ids)
                    )
                )
                await session.execute(delete(MessageRecord).where(MessageRecord.id.in_(record_ids)))
                removed += len(record_ids)
            await session.commit()
        return removed

    async def mark_dormant_topics(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=self.settings.topic_dormant_after_days)
        changed = 0
        async with self.session_factory() as session:
            topics = list(
                await session.scalars(
                    select(TopicRecord).where(
                        TopicRecord.status == "ACTIVE", TopicRecord.last_activity_at < cutoff
                    )
                )
            )
            for topic in topics:
                topic.status = "DORMANT"
                episode = await session.scalar(
                    select(EpisodeRecord)
                    .where(
                        EpisodeRecord.guild_id == topic.guild_id,
                        EpisodeRecord.topic_id == topic.id,
                        EpisodeRecord.ended_at.is_(None),
                    )
                    .order_by(EpisodeRecord.started_at.desc())
                    .limit(1)
                )
                if episode:
                    episode.ended_at = topic.last_activity_at
                changed += 1
            await session.commit()
        return changed

    async def run(self) -> None:
        await self._heartbeat("running")
        next_retention_run = datetime.now(UTC)
        try:
            while not self._stop.is_set():
                if datetime.now(UTC) >= next_retention_run:
                    removed = await self.prune_retained_data()
                    dormant = await self.mark_dormant_topics()
                    if removed:
                        logger.info(
                            "Retention removed expired messages", extra={"status": "complete"}
                        )
                    if dormant:
                        logger.info(
                            "Inactive topics moved to dormant state",
                            extra={"status": "complete"},
                        )
                    next_retention_run = datetime.now(UTC) + timedelta(minutes=15)
                found = await self.process_once()
                if not found:
                    await self._heartbeat("idle")
                    with suppress(TimeoutError):
                        await asyncio.wait_for(
                            self._stop.wait(), timeout=self.settings.worker_poll_seconds
                        )
        finally:
            await self._heartbeat("stopped")
            await self.session_factory.kw["bind"].dispose()


async def run_worker() -> None:
    await ConversationWorker().run()


def main() -> None:
    configure_logging(get_settings().log_level)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()

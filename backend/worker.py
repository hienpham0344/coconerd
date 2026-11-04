import asyncio
import logging
import os
import socket
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from backend.application.budgeted_provider import BudgetedProvider, ModelCallBudgetExceeded
from backend.application.services.health import record_heartbeat
from backend.application.services.jobs import claim_job, complete_job, fail_job
from backend.application.services.messages import process_message_record
from backend.application.services.model_config import select_worker_settings
from backend.application.services.retention import prune_retained_data
from backend.application.services.topics import mark_dormant_topics
from backend.config import Settings, get_settings
from backend.infrastructure.database.connection import create_session_factory
from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from backend.infrastructure.meta_provider import (
    MetaModelProvider,
    MetaOutputTruncatedError,
    MockMetaProvider,
)
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
            await record_heartbeat(SqlAlchemyUnitOfWork(session), self.worker_id, status)

    async def _provider_for_guild(self, guild_id: str):
        if self.settings.mock_llm and self.settings.app_env in {"development", "test"}:
            return MockMetaProvider()
        async with self.session_factory() as session:
            effective = await select_worker_settings(
                SqlAlchemyUnitOfWork(session), self.settings, guild_id
            )
        return MetaModelProvider(effective)

    async def process_once(self) -> bool:
        async with self.session_factory() as session:
            unit_of_work = SqlAlchemyUnitOfWork(session)
            job = await claim_job(unit_of_work, self.worker_id, self.settings.worker_lease_seconds)
            if job is None:
                return False
            job_id = job.id
            message_record_id = job.message_record_id
            guild_id = job.guild_id

        provider = None
        try:
            provider = BudgetedProvider(
                lambda: self._provider_for_guild(guild_id),
                lambda: self._reserve_model_call(job_id),
            )
            async with self.session_factory() as session:
                unit_of_work = SqlAlchemyUnitOfWork(session)
                result = await process_message_record(
                    unit_of_work,
                    message_record_id,
                    provider,
                    followup_message_id=job.followup_message_id,
                )
                await complete_job(unit_of_work, job_id, result)
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
            await self._fail_job(
                job_id,
                type(exc).__name__,
                retryable=not isinstance(exc, (MetaOutputTruncatedError, ModelCallBudgetExceeded)),
            )
        finally:
            if provider is not None:
                await provider.close()
        return True

    async def _fail_job(self, job_id: str, error_type: str, *, retryable: bool = True) -> None:
        async with self.session_factory() as session:
            await fail_job(SqlAlchemyUnitOfWork(session), job_id, error_type, retryable=retryable)

    async def _reserve_model_call(self, job_id: str) -> bool:
        async with self.session_factory() as session:
            uow = SqlAlchemyUnitOfWork(session)
            reserved = await uow.jobs.reserve_model_call(job_id, self.worker_id)
            await uow.commit()
            return reserved

    async def prune_retained_data(self) -> int:
        async with self.session_factory() as session:
            return await prune_retained_data(SqlAlchemyUnitOfWork(session))

    async def mark_dormant_topics(self) -> int:
        async with self.session_factory() as session:
            return await mark_dormant_topics(
                SqlAlchemyUnitOfWork(session), self.settings.topic_dormant_after_days
            )

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

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from backend.application.contracts import ClassificationResult, TopicDecision
from backend.application.services.messages import ingest_message
from backend.config import Settings
from backend.domain.entities import ConversationMessage
from backend.infrastructure.database.models import (
    AIDecisionRecord,
    DiscordActionRecord,
    GuildSettingsRecord,
    MessageTopicAssociationRecord,
    ProcessingJobRecord,
    TopicRecord,
)
from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork
from backend.infrastructure.meta_provider import MetaTimeoutError
from backend.worker import ConversationWorker


def worker(factory, provider):
    instance = ConversationWorker.__new__(ConversationWorker)
    instance.settings = Settings(_env_file=None)
    instance.worker_id = "test-worker"
    instance.session_factory = factory

    async def provider_for_guild(_guild):
        return provider

    instance._provider_for_guild = provider_for_guild
    return instance


async def ingest(factory, id, content, created_at):
    async with factory() as session:
        if await session.get(GuildSettingsRecord, "g") is None:
            session.add(GuildSettingsRecord(guild_id="g", enabled=True, allowed_channel_ids=["c"]))
            await session.commit()
        result = await ingest_message(
            SqlAlchemyUnitOfWork(session),
            ConversationMessage(
                guild_id="g",
                channel_id="c",
                message_id=id,
                author_id="a",
                author_name="A",
                content=content,
                created_at=created_at,
            ),
            5,
        )
        return result.message_id


async def test_worker_reassesses_deferred_once_without_duplicate_writes(database_factory):
    calls = []

    class Provider:
        model_id = "fake"

        async def classify(self, message, candidates, context):
            calls.append(message.message_id)
            assert any(item.relation == "followup_clarification" for item in context)
            return ClassificationResult(
                decision=TopicDecision(
                    outcome="new",
                    title="Beta schedule",
                    confidence=0.8,
                    reason="clarified",
                    summary="Acknowledges beta schedule",
                    evidence_message_ids=[message.message_id, "clarify"],
                ),
                model_id=self.model_id,
                latency_ms=1,
            )

    instance = worker(database_factory, Provider())
    now = datetime.now(UTC)
    record_id = await ingest(database_factory, "root", "ok", now - timedelta(seconds=5))
    assert await instance.process_once()
    assert calls == []
    await ingest(database_factory, "clarify", "ý mình là lịch beta", now)
    assert await instance.process_once()
    assert calls == ["root"]
    async with database_factory() as session:
        job = await session.scalar(
            select(ProcessingJobRecord).where(ProcessingJobRecord.message_record_id == record_id)
        )
        assert (job.status, job.reassessment_count, job.model_call_count) == ("SUCCEEDED", 1, 1)
        assert await session.scalar(select(func.count()).select_from(TopicRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(DiscordActionRecord)) == 2
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AIDecisionRecord)
                .where(AIDecisionRecord.message_record_id == record_id)
            )
            == 2
        )
        associations = list(
            await session.scalars(
                select(MessageTopicAssociationRecord).where(
                    MessageTopicAssociationRecord.message_record_id == record_id
                )
            )
        )
        assert len(associations) == 1 and associations[0].topic_id is not None


async def test_worker_model_budget_counts_failed_requests(database_factory):
    calls = []

    class Provider:
        model_id = "fake"

        async def classify(self, *_args):
            calls.append(True)
            raise MetaTimeoutError("synthetic timeout")

    instance = worker(database_factory, Provider())
    await ingest(database_factory, "root", "Plan a beta release", datetime.now(UTC))
    for _ in range(2):
        assert await instance.process_once()
        async with database_factory() as session:
            await session.execute(
                update(ProcessingJobRecord).values(
                    available_at=datetime.now(UTC) - timedelta(seconds=1)
                )
            )
            await session.commit()
    assert not await instance.process_once()
    async with database_factory() as session:
        job = await session.scalar(select(ProcessingJobRecord))
        assert job.status == "DEAD" and job.model_call_count == 2
    assert len(calls) == 2

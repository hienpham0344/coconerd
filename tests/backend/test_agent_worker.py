import logging
from datetime import UTC, datetime, timedelta

import pytest
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
from coconerd_ai.task_routing import TaskConfigurationError, TaskInputError


async def test_worker_failure_log_does_not_include_provider_exception_body(
    database_factory, caplog, monkeypatch
):
    # Alembic's fileConfig disables existing loggers in earlier migration tests.
    monkeypatch.setattr(logging.getLogger("backend.worker"), "disabled", False)

    class Provider:
        model_id = "fake"

        async def classify(self, *_args):
            raise RuntimeError("private-provider-error-and-key")

    instance = worker(database_factory, Provider())
    await ingest(database_factory, "log", "Launch Friday", datetime.now(UTC))
    with caplog.at_level("ERROR", logger="backend.worker"):
        assert await instance.process_once()
    assert "private-provider-error-and-key" not in caplog.text
    records = [record for record in caplog.records if record.name == "backend.worker"]
    assert records[-1].error_type == "RuntimeError"
    assert records[-1].exc_info is None


@pytest.mark.parametrize("failure", [TaskConfigurationError, TaskInputError])
async def test_worker_does_not_retry_invalid_task_contract(database_factory, failure):
    class Provider:
        model_id = "fake"

        async def classify(self, *_args):
            raise failure("invalid task contract")

    instance = worker(database_factory, Provider())
    record_id = await ingest(database_factory, "contract", "Launch Friday", datetime.now(UTC))
    assert await instance.process_once()
    assert not await instance.process_once()
    async with database_factory() as session:
        job = await session.scalar(
            select(ProcessingJobRecord).where(ProcessingJobRecord.message_record_id == record_id)
        )
        assert (job.status, job.model_call_count) == ("DEAD", 1)
        assert await session.scalar(select(func.count()).select_from(DiscordActionRecord)) == 0


async def test_worker_persists_task_route_with_decision(database_factory):
    route = {"task": "topic_classification", "version": "task-routing-v1", "mode": "task"}

    class Provider:
        model_id = "meta-test-model"

        async def classify(self, message, *_args):
            return ClassificationResult(
                decision=TopicDecision(
                    outcome="new",
                    title="Launch",
                    confidence=0.8,
                    reason="launch plan",
                    summary="Launch Friday",
                    evidence_message_ids=[message.message_id],
                ),
                model_id=self.model_id,
                latency_ms=1,
                task_route=route,
            )

    instance = worker(database_factory, Provider())
    record_id = await ingest(database_factory, "trace", "Launch Friday", datetime.now(UTC))
    assert await instance.process_once()
    async with database_factory() as session:
        decision = await session.scalar(
            select(AIDecisionRecord).where(AIDecisionRecord.message_record_id == record_id)
        )
        assert decision.payload["task_route"] == route
        job = await session.scalar(
            select(ProcessingJobRecord).where(ProcessingJobRecord.message_record_id == record_id)
        )
        assert (job.status, job.model_call_count) == ("SUCCEEDED", 1)


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

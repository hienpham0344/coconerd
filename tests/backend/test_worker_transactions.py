"""Worker transaction boundary without a SQLite connection."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend import worker as worker_module
from backend.application.contracts import ClassificationResult, TopicDecision
from backend.application.read_models import MessageReadModel
from backend.infrastructure.meta_provider import MetaOutputTruncatedError, MetaTimeoutError


async def _empty_recent(*_args, **_kwargs):
    return []


async def test_completion_failure_rolls_back_staged_classification(monkeypatch):
    staged = []
    durable = []
    stage_at_failure = []
    failures = []
    processing_commits = []
    rollbacks = []
    created_at = datetime(2026, 1, 1, tzinfo=UTC)

    class Workflow:
        async def ainvoke(self, _state):
            return {
                "classification": ClassificationResult(
                    decision=TopicDecision(
                        outcome="new",
                        title="Launch",
                        summary="Launch timing",
                        confidence=0.8,
                        reason="new topic",
                    ),
                    model_id="fake",
                    candidate_topic_ids=[],
                    latency_ms=1,
                )
            }

    async def get_message(_id):
        return MessageReadModel(
            id="record-1",
            guild_id="guild-1",
            channel_id="channel-1",
            discord_message_id="discord-1",
            author_id="author-1",
            author_name="User",
            content="Launch timing",
            created_at=created_at,
            reply_to_message_id=None,
        )

    async def candidates(_guild):
        return []

    async def none(*_args):
        return None

    async def create(topic):
        staged.append("topic")
        return SimpleNamespace(
            id=topic.id,
            guild_id=topic.guild_id,
            title=topic.title,
            description=topic.description,
            status=topic.status.value,
            version=1,
            discord_thread_id=None,
            sync_paused=False,
        )

    async def stage_episode(*_args):
        staged.append("episode")

    async def stage_association(*_args):
        staged.append("association")

    async def stage_decision(*_args):
        staged.append("decision")

    async def stage_touch(*_args):
        staged.append("touch")

    async def stage_action(*_args, **_kwargs):
        staged.append("action")
        return SimpleNamespace(id="action-1")

    async def stage_summary(*_args):
        staged.append("summary")
        return SimpleNamespace(id="summary-1", version=1)

    async def fail_completion(_job_id, *, owner):
        stage_at_failure.extend(staged)
        raise LookupError("Claimed processing job disappeared")

    async def claim_one(_owner, _now, _lease_expires_at):
        return SimpleNamespace(
            id="job-1", message_record_id="record-1", guild_id="guild-1", followup_message_id=None
        )

    async def claim_commit():
        return None

    async def processing_commit():
        processing_commits.append(True)
        durable.extend(staged)
        staged.clear()

    claim_uow = SimpleNamespace(
        jobs=SimpleNamespace(claim_available=claim_one),
        commit=claim_commit,
    )
    processing_uow = SimpleNamespace(
        messages=SimpleNamespace(
            get=get_message,
            recent_before=_empty_recent,
            evidence_for_topic=_empty_recent,
            add_association=stage_association,
            add_decision=stage_decision,
        ),
        topics=SimpleNamespace(
            search=_empty_recent,
            candidates=candidates,
            create=create,
            add_episode=stage_episode,
            touch=stage_touch,
        ),
        summaries=SimpleNamespace(latest=none, add=stage_summary),
        actions=SimpleNamespace(add=stage_action),
        jobs=SimpleNamespace(complete=fail_completion),
        commit=processing_commit,
    )

    class FakeSession:
        def __init__(self, uow):
            self.uow = uow

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, _exc, _tb):
            if exc_type is not None and self.uow is processing_uow:
                rollbacks.append(True)
                staged.clear()

    sessions = iter([FakeSession(claim_uow), FakeSession(processing_uow)])
    monkeypatch.setattr(worker_module, "SqlAlchemyUnitOfWork", lambda session: session.uow)
    monkeypatch.setattr(
        "backend.application.services.messages.create_topic_workflow",
        lambda _provider: Workflow(),
    )
    worker = worker_module.ConversationWorker.__new__(worker_module.ConversationWorker)
    worker.session_factory = lambda: next(sessions)
    worker.settings = SimpleNamespace(worker_lease_seconds=30)
    worker.worker_id = "worker-1"

    async def provider_for_guild(_guild_id):
        return SimpleNamespace(model_id="fake")

    async def fail_job(job_id, error_type, *, retryable=True):
        assert retryable
        failures.append((job_id, error_type))

    worker._provider_for_guild = provider_for_guild
    worker._fail_job = fail_job
    assert await worker.process_once() is True
    assert {"topic", "episode", "association", "decision", "summary", "action"} <= set(
        stage_at_failure
    )
    assert processing_commits == []
    assert durable == []
    assert staged == []
    assert rollbacks == [True]
    assert failures == [("job-1", "LookupError")]


@pytest.mark.parametrize(
    "error,retryable", [(MetaOutputTruncatedError("budget"), False), (MetaTimeoutError(), True)]
)
async def test_worker_stops_truncation_but_retries_temporary_failure(monkeypatch, error, retryable):
    @asynccontextmanager
    async def session_factory():
        yield SimpleNamespace()

    monkeypatch.setattr(worker_module, "SqlAlchemyUnitOfWork", lambda session: session)
    monkeypatch.setattr(
        worker_module,
        "claim_job",
        AsyncMock(
            return_value=SimpleNamespace(
                id="job-1", message_record_id="record-1", guild_id="g", followup_message_id=None
            )
        ),
    )
    monkeypatch.setattr(worker_module, "process_message_record", AsyncMock(side_effect=error))
    worker = worker_module.ConversationWorker.__new__(worker_module.ConversationWorker)
    worker.session_factory = session_factory
    worker.settings = SimpleNamespace(worker_lease_seconds=30)
    worker.worker_id = "worker-1"
    worker._provider_for_guild = AsyncMock(return_value=SimpleNamespace(model_id="fake"))
    worker._fail_job = AsyncMock()

    assert await worker.process_once() is True

    worker._fail_job.assert_awaited_once_with("job-1", type(error).__name__, retryable=retryable)

"""HTTP -> migrated SQLite -> real worker -> simulated bot delivery, with no external API."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text, update

from alembic import command
from backend.application.contracts import ClassificationResult, MemoryReplacement, TopicDecision
from backend.config import Settings, get_settings
from backend.infrastructure.database.connection import create_session_factory
from backend.infrastructure.database.models import (
    DiscordActionRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    ProcessingJobRecord,
    TopicRecord,
    TopicSummaryRecord,
)
from backend.infrastructure.meta_provider import MetaOutputTruncatedError, MetaTimeoutError
from backend.presentation.api.app import create_app
from backend.worker import ConversationWorker

BOT = {"X-API-Key": "integration-bot-key"}
ADMIN = {"X-Admin-API-Key": "integration-admin-key"}


class ScenarioProvider:
    model_id = "deterministic-integration-provider"

    def __init__(self, failures=()):
        self.failures = list(failures)
        self.calls = 0

    async def classify(self, message, candidates, context):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        existing = bool(candidates)
        decision = TopicDecision(
            outcome="existing" if existing else "new",
            topic_id=candidates[0].id if existing else None,
            title=None if existing else "Atlas release",
            confidence=0.95,
            reason="synthetic deterministic integration decision",
            summary="Thanh phụ trách API." if existing else "Lan phụ trách QA.\nPhát hành thứ Năm",
            decisions=[] if existing else ["Phát hành thứ Năm"],
            evidence_message_ids=[message.message_id],
        )
        if existing:
            decision.memory_replacements = [
                MemoryReplacement(
                    field=field,
                    previous="Phát hành thứ Năm",
                    replacement="Phát hành thứ Sáu",
                    quote="Dời phát hành sang thứ Sáu",
                )
                for field in ("overview", "decisions")
            ]
        return ClassificationResult(decision=decision, model_id=self.model_id, latency_ms=0)


@pytest.fixture
def migrated_settings(tmp_path, monkeypatch, postgres_database_url):
    url = postgres_database_url or f"sqlite+aiosqlite:///{tmp_path / 'bot.db'}"
    monkeypatch.setenv("COCONERD_DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")
        yield Settings(
            _env_file=None,
            database_url=url,
            app_env="test",
            mock_llm=True,
            bot_api_key=BOT["X-API-Key"],
            admin_api_key=ADMIN["X-Admin-API-Key"],
        )
    finally:
        get_settings.cache_clear()


@pytest_asyncio.fixture
async def runtime(migrated_settings, monkeypatch):
    factory = create_session_factory(migrated_settings)
    app = create_app(migrated_settings, factory)
    worker = ConversationWorker(migrated_settings)
    provider = ScenarioProvider()

    async def select_provider(_guild):
        return provider

    monkeypatch.setattr(worker, "_provider_for_guild", select_provider)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                "/api/v1/admin/guilds/g/settings",
                headers=ADMIN,
                json={"enabled": True, "allowed_channel_ids": ["c"], "retention_days": 365},
            )
            assert response.status_code == 200
            yield SimpleNamespace(client=client, worker=worker, factory=factory, provider=provider)
    finally:
        await factory.kw["bind"].dispose()
        await worker.session_factory.kw["bind"].dispose()


def payload(mid="first", content="Atlas: Lan phụ trách QA. Phát hành thứ Năm.", reply=None):
    return dict(
        guild_id="g",
        channel_id="c",
        message_id=mid,
        author_id="a",
        author_name="User",
        content=content,
        created_at=datetime.now(UTC).isoformat(),
        reply_to_message_id=reply,
    )


async def post_message(runtime, body):
    response = await runtime.client.post("/api/v1/messages", headers=BOT, json=body)
    assert response.status_code == 202, response.text
    assert response.headers["X-Request-ID"]


async def claim(runtime, owner="bot"):
    response = await runtime.client.post(
        "/api/v1/actions/claim", headers=BOT, json={"worker_id": owner, "limit": 20}
    )
    assert response.status_code == 200
    return response.json()


async def ack(runtime, action, owner="bot"):
    body = {
        "worker_id": owner,
        "lease_token": action["lease_token"],
        "discord_thread_id": "thread-atlas",
    }
    if action["type"] != "CREATE_THREAD":
        body["discord_message_id"] = "discord-" + action["action_id"]
    response = await runtime.client.post(
        f"/api/v1/actions/{action['action_id']}/complete", headers=BOT, json=body
    )
    assert response.status_code == 200, response.text
    return body


async def test_migrated_http_worker_memory_outbox_retry_and_ack(runtime):
    first = payload()
    await post_message(runtime, first)
    await post_message(runtime, first)
    assert await runtime.worker.process_once()
    await post_message(
        runtime,
        payload("second", "Atlas: Dời phát hành sang thứ Sáu. Thanh phụ trách API.", "first"),
    )
    assert await runtime.worker.process_once()
    assert not await runtime.worker.process_once()
    assert runtime.provider.calls == 2

    async with runtime.factory() as session:
        for model, expected in [
            (MessageRecord, 2),
            (ProcessingJobRecord, 2),
            (MessageTopicAssociationRecord, 2),
            (TopicRecord, 1),
            (TopicSummaryRecord, 2),
            (DiscordActionRecord, 4),
        ]:
            assert await session.scalar(select(func.count()).select_from(model)) == expected
        summaries = list(
            await session.scalars(select(TopicSummaryRecord).order_by(TopicSummaryRecord.version))
        )
        assert summaries[0].data["decisions"] == ["Phát hành thứ Năm"]
        latest = summaries[1]
        assert latest.data["decisions"] == ["Phát hành thứ Sáu"]
        assert "Lan phụ trách QA." in latest.data["overview"]
        assert "Thanh phụ trách API." in latest.data["overview"]
        assert "thứ Năm" not in latest.data["overview"]
        assert latest.source_message_ids == ["first", "second"]
        if session.get_bind().dialect.name == "sqlite":
            assert not (await session.execute(text("PRAGMA foreign_key_check"))).all()
        assert set(await session.scalars(select(ProcessingJobRecord.status))) == {"SUCCEEDED"}
        assert list(await session.scalars(select(ProcessingJobRecord.model_call_count))) == [1, 1]
        topic_id = latest.topic_id

    (create,) = await claim(runtime)
    assert create["type"] == "CREATE_THREAD"
    missing = await runtime.client.post(
        f"/api/v1/actions/{create['action_id']}/complete",
        headers=BOT,
        json={"worker_id": "bot", "discord_thread_id": "thread-atlas"},
    )
    assert missing.status_code == 409
    receipt = await ack(runtime, create)
    repeated = await runtime.client.post(
        f"/api/v1/actions/{create['action_id']}/complete", headers=BOT, json=receipt
    )
    assert repeated.status_code == 200
    (summary_one,) = await claim(runtime)
    assert summary_one["payload"]["version"] == 1
    await ack(runtime, summary_one)
    (append,) = await claim(runtime)
    assert append["type"] == "APPEND_MESSAGE"
    failed = await runtime.client.post(
        f"/api/v1/actions/{append['action_id']}/fail",
        headers=BOT,
        json={
            "worker_id": "bot",
            "lease_token": append["lease_token"],
            "error_type": "DiscordUnavailable",
            "error_message": "synthetic temporary failure",
            "retryable": True,
        },
    )
    assert failed.status_code == 200 and failed.json()["status"] == "PENDING"
    assert await claim(runtime, "restarted-bot") == []
    async with runtime.factory() as session:
        await session.execute(
            update(DiscordActionRecord)
            .where(DiscordActionRecord.id == append["action_id"])
            .values(available_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    (retried,) = await claim(runtime, "restarted-bot")
    assert retried["action_id"] == append["action_id"]
    assert retried["lease_token"] != append["lease_token"]
    await ack(runtime, retried, "restarted-bot")
    (summary_two,) = await claim(runtime)
    assert summary_two["payload"]["version"] == 2
    await ack(runtime, summary_two)
    assert await claim(runtime) == []
    topic = await runtime.client.get(f"/api/v1/topics/{topic_id}?guild_id=g", headers=BOT)
    assert topic.json()["discord_thread_id"] == "thread-atlas"
    wrong_guild = await runtime.client.get(f"/api/v1/topics/{topic_id}?guild_id=other", headers=BOT)
    assert wrong_guild.status_code == 404


async def test_concurrent_duplicate_delivery_is_one_message_and_job(runtime):
    body = payload()
    await asyncio.gather(*(post_message(runtime, body) for _ in range(8)))
    async with runtime.factory() as session:
        assert await session.scalar(select(func.count()).select_from(MessageRecord)) == 1
        assert await session.scalar(select(func.count()).select_from(ProcessingJobRecord)) == 1
    assert runtime.provider.calls == 0


@pytest.mark.parametrize("truncated", [False, True])
async def test_real_worker_error_budget_preserves_message_without_partial_topic(runtime, truncated):
    runtime.provider.failures = (
        [MetaOutputTruncatedError("synthetic")]
        if truncated
        else [MetaTimeoutError("synthetic"), MetaTimeoutError("synthetic")]
    )
    await post_message(runtime, payload())
    assert await runtime.worker.process_once()
    if not truncated:
        async with runtime.factory() as session:
            await session.execute(
                update(ProcessingJobRecord).values(
                    available_at=datetime.now(UTC) - timedelta(seconds=1)
                )
            )
            await session.commit()
        assert await runtime.worker.process_once()
    assert not await runtime.worker.process_once()
    async with runtime.factory() as session:
        job = await session.scalar(select(ProcessingJobRecord))
        assert job.status == "DEAD"
        assert job.model_call_count == (1 if truncated else 2)
        assert await session.scalar(select(func.count()).select_from(MessageRecord)) == 1
        for model in (
            TopicRecord,
            MessageTopicAssociationRecord,
            TopicSummaryRecord,
            DiscordActionRecord,
        ):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_local_messages_never_construct_a_provider(runtime):
    await post_message(runtime, payload("blank", "  "))
    assert await runtime.worker.process_once()
    await post_message(runtime, payload("missing", "ok"))
    assert await runtime.worker.process_once()
    assert runtime.provider.calls == 0
    async with runtime.factory() as session:
        assert set(await session.scalars(select(MessageTopicAssociationRecord.kind))) == {
            "IRRELEVANT",
            "DEFERRED",
        }
        assert set(await session.scalars(select(ProcessingJobRecord.model_call_count))) == {0}
        assert await session.scalar(select(func.count()).select_from(DiscordActionRecord)) == 0

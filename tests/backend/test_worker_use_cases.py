"""Worker policies exercised through repositories on synchronous SQLite.

The adapter avoids the environment's async-driver stall; it does not validate
aiosqlite scheduling or concurrent claims.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from backend.application.services.health import record_heartbeat
from backend.application.services.jobs import claim_job, fail_job
from backend.application.services.model_config import select_worker_settings
from backend.application.services.retention import prune_retained_data
from backend.application.services.topics import mark_dormant_topics
from backend.config import Settings
from backend.infrastructure.database.models import (
    AIDecisionRecord,
    ApiRateLimitRecord,
    Base,
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
from backend.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork


class SyncSessionAdapter:
    def __init__(self, session):
        self.session = session

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def scalars(self, statement):
        return self.session.scalars(statement)

    async def execute(self, statement):
        return self.session.execute(statement)

    async def get(self, model, key):
        return self.session.get(model, key)

    def add(self, record):
        self.session.add(record)

    async def commit(self):
        self.session.commit()

    async def rollback(self):
        self.session.rollback()


@pytest.fixture
def database():
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session, SqlAlchemyUnitOfWork(SyncSessionAdapter(session))
    engine.dispose()


def message(id, guild="g", created_at=None):
    return MessageRecord(
        id=id,
        guild_id=guild,
        channel_id="c",
        discord_message_id=f"discord-{id}",
        author_id="a",
        author_name="User",
        content="private",
        created_at=created_at or datetime.now(UTC),
    )


async def test_heartbeat_upserts_same_worker(database):
    session, uow = database
    await record_heartbeat(uow, "worker", "running")
    await record_heartbeat(uow, "worker", "idle")
    session.expire_all()
    rows = list(session.scalars(select(WorkerHeartbeatRecord)))
    assert len(rows) == 1
    assert rows[0].status == "idle"
    assert rows[0].last_seen_at is not None


async def test_claim_and_failure_retry_budget_and_dead_letter(database):
    session, uow = database
    session.add(message("m"))
    session.flush()
    session.add(ProcessingJobRecord(id="j", guild_id="g", message_record_id="m", max_attempts=2))
    session.commit()
    job = await claim_job(uow, "worker", 30)
    assert job.id == "j"
    await fail_job(uow, "j", "FirstFailure")
    session.expire_all()
    row = session.get(ProcessingJobRecord, "j")
    assert (row.status, row.attempt_count, row.lease_owner, row.error_type) == (
        "PENDING",
        1,
        None,
        "FirstFailure",
    )
    assert row.lease_expires_at is None
    delay = row.available_at.replace(tzinfo=UTC) - datetime.now(UTC)
    assert 0 < delay.total_seconds() <= 2
    row.available_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    assert (await claim_job(uow, "worker", 30)).id == "j"
    await fail_job(uow, "j", "FinalFailure")
    session.expire_all()
    assert session.get(ProcessingJobRecord, "j").status == "DEAD"
    assert await claim_job(uow, "worker", 30) is None
    await fail_job(uow, "missing", "Ignored")


@pytest.mark.parametrize(
    "guild_enabled,global_enabled,expected",
    [(True, True, "guild"), (False, True, "global"), (False, False, "default")],
)
async def test_provider_configuration_enabled_fallback(
    database, guild_enabled, global_enabled, expected
):
    session, uow = database
    session.add_all(
        [
            ModelConfigRecord(
                id="gc",
                scope="guild",
                guild_id="g",
                provider="meta",
                model_id="guild",
                enabled=guild_enabled,
            ),
            ModelConfigRecord(
                id="global",
                scope="global",
                guild_id=None,
                provider="meta",
                model_id="global",
                enabled=global_enabled,
            ),
        ]
    )
    session.commit()
    defaults = Settings(_env_file=None, meta_model_name="default")
    selected = await select_worker_settings(uow, defaults, "g")
    assert selected.meta_model_name == expected
    assert defaults.meta_model_name == "default"


async def test_retention_removes_expired_messages_and_redacts_only_their_actions(database):
    session, uow = database
    now = datetime.now(UTC)
    session.add_all(
        [
            GuildSettingsRecord(guild_id="g", retention_days=7),
            TopicRecord(id="t", guild_id="g", title="Topic"),
            message("old", created_at=now - timedelta(days=8)),
            message("fresh", created_at=now),
            message("other", guild="other", created_at=now - timedelta(days=8)),
            ApiRateLimitRecord(
                client_fingerprint="old", window_start=now - timedelta(hours=2), request_count=1
            ),
            ApiRateLimitRecord(client_fingerprint="new", window_start=now, request_count=1),
        ]
    )
    session.flush()
    session.add_all(
        [
            ProcessingJobRecord(id="j", guild_id="g", message_record_id="old"),
            AIDecisionRecord(
                id="decision",
                guild_id="g",
                message_record_id="old",
                decision_type="new",
                model_id="fake",
                payload={},
            ),
            MessageTopicAssociationRecord(
                id="association",
                guild_id="g",
                message_record_id="old",
                topic_id="t",
                kind="CLASSIFIED",
                confidence=1.0,
            ),
            DiscordActionRecord(
                id="pending",
                guild_id="g",
                channel_id="c",
                topic_id="t",
                action_type="APPEND_MESSAGE",
                status="CLAIMED",
                lease_owner="worker",
                payload={
                    "source_message_id": "discord-old",
                    "source_content": "secret",
                    "other": "keep",
                },
            ),
            DiscordActionRecord(
                id="done",
                guild_id="g",
                channel_id="c",
                topic_id="t",
                action_type="CREATE_THREAD",
                status="SUCCEEDED",
                payload={"source_message_id": "discord-old", "source_content": "secret"},
            ),
            DiscordActionRecord(
                id="fresh",
                guild_id="g",
                channel_id="c",
                topic_id="t",
                action_type="APPEND_MESSAGE",
                status="PENDING",
                payload={"source_message_id": "discord-fresh", "source_content": "keep"},
            ),
            TopicSummaryRecord(
                id="s",
                guild_id="g",
                topic_id="t",
                version=1,
                data={},
                source_message_ids=["discord-old", "discord-fresh"],
            ),
        ]
    )
    session.commit()
    assert await prune_retained_data(uow) == 1
    session.expire_all()
    assert session.get(MessageRecord, "old") is None
    assert session.get(ProcessingJobRecord, "j") is None
    assert session.get(AIDecisionRecord, "decision") is None
    assert session.get(MessageTopicAssociationRecord, "association") is None
    assert session.get(MessageRecord, "fresh") is not None
    assert session.get(MessageRecord, "other") is not None
    pending = session.get(DiscordActionRecord, "pending")
    assert pending.payload == {"source_message_id": "discord-old", "other": "keep"}
    assert (pending.status, pending.error_type, pending.lease_owner, pending.lease_expires_at) == (
        "DEAD",
        "retention_expired",
        None,
        None,
    )
    assert session.get(DiscordActionRecord, "done").status == "SUCCEEDED"
    assert "source_content" not in session.get(DiscordActionRecord, "done").payload
    assert session.get(DiscordActionRecord, "fresh").payload["source_content"] == "keep"
    assert session.get(TopicSummaryRecord, "s").source_message_ids == ["discord-fresh"]
    assert [r.client_fingerprint for r in session.scalars(select(ApiRateLimitRecord))] == ["new"]


async def test_dormancy_only_changes_old_active_topics_and_closes_latest_episode(database):
    session, uow = database
    old = datetime.now(UTC) - timedelta(days=31)
    session.add_all(
        [
            TopicRecord(
                id="active", guild_id="g", title="A", status="ACTIVE", last_activity_at=old
            ),
            TopicRecord(
                id="closed", guild_id="g", title="C", status="CLOSED", last_activity_at=old
            ),
            TopicRecord(
                id="recent",
                guild_id="g",
                title="R",
                status="ACTIVE",
                last_activity_at=datetime.now(UTC),
            ),
        ]
    )
    session.flush()
    session.add_all(
        [
            EpisodeRecord(
                id="older", guild_id="g", topic_id="active", started_at=old - timedelta(days=2)
            ),
            EpisodeRecord(
                id="latest", guild_id="g", topic_id="active", started_at=old - timedelta(days=1)
            ),
        ]
    )
    session.commit()
    assert await mark_dormant_topics(uow, 30) == 1
    session.expire_all()
    assert session.get(TopicRecord, "active").status == "DORMANT"
    assert session.get(TopicRecord, "closed").status == "CLOSED"
    assert session.get(TopicRecord, "recent").status == "ACTIVE"
    assert session.get(EpisodeRecord, "older").ended_at is None
    assert session.get(EpisodeRecord, "latest").ended_at == old.replace(tzinfo=None)


async def test_expired_claim_is_reclaimed_and_exhausted_jobs_become_dead(database):
    session, uow = database
    session.add_all([message("expired"), message("exhausted")])
    session.flush()
    session.add_all(
        [
            ProcessingJobRecord(
                id="expired",
                guild_id="g",
                message_record_id="expired",
                status="CLAIMED",
                lease_owner="old-worker",
                lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                attempt_count=1,
                max_attempts=3,
            ),
            ProcessingJobRecord(
                id="exhausted",
                guild_id="g",
                message_record_id="exhausted",
                status="PENDING",
                attempt_count=3,
                max_attempts=3,
            ),
        ]
    )
    session.commit()
    assert (await claim_job(uow, "new-worker", 30)).id == "expired"
    session.expire_all()
    reclaimed = session.get(ProcessingJobRecord, "expired")
    assert (reclaimed.lease_owner, reclaimed.attempt_count) == ("new-worker", 2)
    assert await claim_job(uow, "new-worker", 30) is None
    session.expire_all()
    assert session.get(ProcessingJobRecord, "exhausted").status == "DEAD"

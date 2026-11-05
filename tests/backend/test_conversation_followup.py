"""Natural conversation can supply evidence for a deferred message without a reply."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from test_worker_use_cases import database as database

from backend.application.contracts import ClassificationResult, TopicCandidate, TopicDecision
from backend.application.decision_policy import classify_locally
from backend.application.read_models import ContextMessage
from backend.application.services.messages import process_message_record
from backend.application.services.topic_tools import TopicTools
from backend.application.topic_retriever import retrieve_topic_candidates
from backend.domain.entities import ConversationMessage
from backend.infrastructure.database.models import (
    DiscordActionRecord,
    MessageRecord,
    MessageTopicAssociationRecord,
    ProcessingJobRecord,
    TopicRecord,
)


def seed(
    session,
    *,
    seconds=30,
    channel="c",
    guild="g",
    reply_to=None,
    assigned=True,
    content="ăn cái gì?",
    count=4,
):
    now = datetime.now(UTC)
    session.add(TopicRecord(id="food", guild_id="g", channel_id="c", title="Trưa nay ăn gì"))
    session.flush()
    for index in range(count):
        message = MessageRecord(
            id=f"hungry-{index}",
            guild_id="g",
            channel_id="c",
            discord_message_id=f"source-{index}",
            author_id="a",
            author_name="A",
            content="hungry",
            created_at=now - timedelta(seconds=seconds + index),
        )
        session.add(message)
        session.flush()
        session.add(
            MessageTopicAssociationRecord(
                id=f"association-{index}",
                guild_id="g",
                message_record_id=message.id,
                kind="DEFERRED",
                confidence=0.3,
                reason="missing context",
            )
        )
        session.add(
            ProcessingJobRecord(
                id=f"job-{index}",
                guild_id="g",
                message_record_id=message.id,
                status="WAITING",
                deferred_until=now + timedelta(minutes=5),
                model_call_count=1,
            )
        )
    session.add(
        MessageRecord(
            id="followup",
            guild_id=guild,
            channel_id=channel,
            discord_message_id="question",
            author_id="b",
            author_name="B",
            content=content,
            created_at=now,
            reply_to_message_id=reply_to,
        )
    )
    session.flush()
    if assigned:
        session.add(
            MessageTopicAssociationRecord(
                id="followup-association",
                guild_id="g",
                message_record_id="followup",
                topic_id="food",
                kind="CLASSIFIED",
                confidence=0.9,
                reason="meal question",
            )
        )
    session.commit()


async def test_assigned_natural_followup_wakes_all_four_hungry_messages(database):
    session, uow = database
    seed(session)
    await uow.jobs.wake_deferred("followup")
    session.expire_all()
    jobs = list(session.scalars(select(ProcessingJobRecord)))
    assert len(jobs) == 4
    assert all(job.status == "PENDING" for job in jobs)
    assert all(job.followup_message_id == "followup" for job in jobs)
    assert all(job.reassessment_count == 1 and job.model_call_count == 1 for job in jobs)
    # Waking is evidence collection, not an automatic assignment.
    associations = list(
        session.scalars(
            select(MessageTopicAssociationRecord).where(
                MessageTopicAssociationRecord.message_record_id != "followup"
            )
        )
    )
    assert all(item.kind == "DEFERRED" and item.topic_id is None for item in associations)
    await uow.jobs.wake_deferred("followup")
    session.expire_all()
    assert all(job.reassessment_count == 1 for job in session.scalars(select(ProcessingJobRecord)))


@pytest.mark.parametrize(
    "changes",
    [
        {"assigned": False},
        {"channel": "other"},
        {"guild": "other"},
        {"seconds": 180},
        {"reply_to": "another-message"},
        {"content": "hungry"},
    ],
)
async def test_unqualified_followup_does_not_wake_deferred_messages(database, changes):
    session, uow = database
    seed(session, **changes)
    await uow.jobs.wake_deferred("followup")
    session.expire_all()
    assert all(job.status == "WAITING" for job in session.scalars(select(ProcessingJobRecord)))


async def test_natural_followup_wake_is_bounded(database):
    session, uow = database
    seed(session, count=8)
    await uow.jobs.wake_deferred("followup")
    session.expire_all()
    statuses = [job.status for job in session.scalars(select(ProcessingJobRecord))]
    assert statuses.count("PENDING") == 6
    assert statuses.count("WAITING") == 2


@pytest.mark.parametrize("change", ["expired", "budget", "reassessed", "final", "closed"])
async def test_natural_followup_preserves_job_and_topic_guards(database, change):
    session, uow = database
    seed(session)
    for job in session.scalars(select(ProcessingJobRecord)):
        if change == "expired":
            job.deferred_until = datetime.now(UTC) - timedelta(seconds=1)
        elif change == "budget":
            job.model_call_count = 2
        elif change == "reassessed":
            job.reassessment_count = 1
        elif change == "final":
            job.status = "SUCCEEDED"
    if change == "closed":
        session.get(TopicRecord, "food").status = "CLOSED"
    session.commit()
    await uow.jobs.wake_deferred("followup")
    session.expire_all()
    assert all(job.status != "PENDING" for job in session.scalars(select(ProcessingJobRecord)))


async def test_wait_finds_already_classified_natural_followup(database):
    session, uow = database
    seed(session)
    job = session.get(ProcessingJobRecord, "job-0")
    job.status = "CLAIMED"
    job.lease_owner = "worker"
    job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=1)
    session.commit()
    assert await uow.jobs.wait_for_context(
        "job-0", datetime.now(UTC) + timedelta(minutes=5), owner="worker"
    )
    session.expire_all()
    job = session.get(ProcessingJobRecord, "job-0")
    assert (job.status, job.followup_message_id, job.reassessment_count) == (
        "PENDING",
        "followup",
        1,
    )


async def test_reassessment_supplies_natural_followup_and_preserves_hungry_text(database):
    session, uow = database
    seed(session)
    record = session.get(MessageRecord, "hungry-0")
    target = ConversationMessage(
        id=record.id,
        guild_id="g",
        channel_id="c",
        message_id=record.discord_message_id,
        author_id="a",
        author_name="A",
        content=record.content,
        created_at=record.created_at,
    )
    gathered = await TopicTools(uow).gather(target, "followup")
    assert any(
        item.message_id == "question" and item.relation == "conversation_followup"
        for item in gathered.messages
    )
    assert gathered.candidates[0].id == "food"
    assert gathered.candidates[0].evidence == "conversation_followup_target"

    class Provider:
        async def classify(self, message, candidates, context):
            assert message.content == "hungry"
            assert any(item.relation == "conversation_followup" for item in context)
            return ClassificationResult(
                decision=TopicDecision(
                    outcome="existing",
                    topic_id="food",
                    confidence=0.8,
                    reason="Hunger precedes the meal question",
                    evidence_message_ids=[message.message_id, "question"],
                ),
                model_id="test",
                latency_ms=0,
            )

    result = await process_message_record(
        uow, target.id, Provider(), followup_message_id="followup"
    )
    await uow.commit()
    assert result.topic_id == "food"
    association = session.scalar(
        select(MessageTopicAssociationRecord).where(
            MessageTopicAssociationRecord.message_record_id == target.id
        )
    )
    assert association.kind == "CLASSIFIED" and association.topic_id == "food"
    action = session.scalar(
        select(DiscordActionRecord).where(DiscordActionRecord.action_type == "CREATE_THREAD")
    )
    assert action.payload["source_content"] == "hungry"
    assert action.payload["source_message_id"] == "source-0"


async def test_classifying_followup_triggers_reassessment(database):
    session, uow = database
    seed(session, assigned=False)

    class Provider:
        async def classify(self, message, candidates, context):
            return ClassificationResult(
                decision=TopicDecision(
                    outcome="existing",
                    topic_id="food",
                    confidence=0.9,
                    reason="Meal coordination",
                    evidence_message_ids=[message.message_id],
                ),
                model_id="test",
                latency_ms=0,
            )

    await process_message_record(uow, "followup", Provider())
    await uow.commit()
    session.expire_all()
    assert all(job.status == "PENDING" for job in session.scalars(select(ProcessingJobRecord)))


def test_followup_topic_survives_cross_language_lexical_ranking():
    target = ConversationMessage(
        guild_id="g",
        channel_id="c",
        message_id="target",
        author_id="a",
        author_name="A",
        content="hungry",
        created_at=datetime.now(UTC),
    )
    candidates = [
        TopicCandidate(id=str(i), title="Hungry games", description="", status="ACTIVE")
        for i in range(6)
    ]
    food = TopicCandidate(
        id="food",
        title="Trưa nay ăn gì",
        description="",
        status="ACTIVE",
        evidence="conversation_followup_target",
    )
    shortlisted = retrieve_topic_candidates(target, [*candidates, food])
    assert len(shortlisted) == 5
    assert shortlisted[0].id == "food"
    assert shortlisted[0].evidence == "conversation_followup_target"


def test_natural_followup_allows_model_to_reassess_a_short_reference():
    target = ConversationMessage(
        guild_id="g",
        channel_id="c",
        message_id="target",
        author_id="a",
        author_name="A",
        content="ok",
        created_at=datetime.now(UTC),
    )
    followup = ContextMessage(
        "question", "b", "B", datetime.now(UTC), "conversation_followup", "Chốt lịch ăn trưa?"
    )
    assert classify_locally(target, [followup]) is None

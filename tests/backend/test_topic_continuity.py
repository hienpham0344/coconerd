"""Nearby turns retain their project context without forcing topic assignment."""

from datetime import UTC, datetime, timedelta

import pytest
from test_worker_use_cases import database as database

from backend.application.contracts import ClassificationResult, TopicCandidate, TopicDecision
from backend.application.decision_policy import validate_classification
from backend.application.services.message_context import build_message_context
from backend.application.services.topic_tools import TopicTools
from backend.application.topic_retriever import retrieve_topic_candidates
from backend.domain.entities import ConversationMessage
from backend.infrastructure.database.models import (
    MessageRecord,
    MessageTopicAssociationRecord,
    TopicRecord,
)

NOW = datetime(2026, 11, 5, 5, 2, tzinfo=UTC)


def target(**changes):
    values = dict(
        guild_id="g",
        channel_id="c",
        message_id="roles",
        author_id="a",
        author_name="A",
        content="về phần này mình 3 role",
        created_at=NOW,
    )
    return ConversationMessage(**(values | changes))


def seed_opening(session, *, seconds=30, guild="g", channel="c", status="ACTIVE"):
    session.add(
        TopicRecord(
            id="hackathon",
            guild_id=guild,
            channel_id=channel,
            title="Họp làm hackathon team1",
            status=status,
        )
    )
    session.add(
        MessageRecord(
            id="opening-record",
            guild_id=guild,
            channel_id=channel,
            discord_message_id="opening",
            author_id="a",
            author_name="A",
            content="ok mai mình sẽ họp để làm cái hackathon team1 nha",
            created_at=NOW - timedelta(seconds=seconds),
        )
    )
    session.flush()
    session.add(
        MessageTopicAssociationRecord(
            id="opening-association",
            guild_id=guild,
            message_record_id="opening-record",
            topic_id="hackathon",
            kind="CLASSIFIED",
            confidence=0.9,
            reason="Hackathon meeting",
        )
    )
    session.commit()


async def test_role_continuation_retains_its_hackathon_topic_over_keyword_decoys(database):
    session, uow = database
    seed_opening(session)
    for index in range(7):
        session.add(TopicRecord(id=f"other-{index}", guild_id="g", title=f"Role khác {index}"))
    session.commit()

    message = target()
    gathered = await TopicTools(uow).gather(message)

    assert gathered.candidates[0].id == "hackathon"
    assert gathered.candidates[0].evidence == "conversation_predecessor_target"
    assert any(
        item.message_id == "opening" and item.relation == "conversation_predecessor"
        for item in gathered.messages
    )
    assert message.content == "về phần này mình 3 role"
    assert len(gathered.candidates) <= 5
    assert sum(len(item.content) for item in gathered.messages) <= 1600


async def test_keyword_matches_cannot_displace_the_immediately_preceding_turn(database):
    session, uow = database
    seed_opening(session, seconds=1)
    for index in range(8):
        session.add(
            MessageRecord(
                id=f"old-{index}",
                guild_id="g",
                channel_id="c",
                discord_message_id=f"old-{index}",
                author_id="b",
                author_name="B",
                content="role " * 70,
                created_at=NOW - timedelta(seconds=10 + index),
            )
        )
    session.commit()

    context = await build_message_context(uow.messages, target())
    assert "opening" in [item.message_id for item in context]
    assert len(context) <= 6
    assert sum(len(item.content) for item in context) <= 1600


@pytest.mark.parametrize(
    "changes",
    [
        {"seconds": 121},
        {"guild": "other"},
        {"channel": "elsewhere"},
        {"status": "CLOSED"},
    ],
)
async def test_predecessor_hint_respects_scope_time_and_topic_lifecycle(database, changes):
    session, uow = database
    seed_opening(session, **changes)
    gathered = await TopicTools(uow).gather(target())
    assert all(item.relation != "conversation_predecessor" for item in gathered.messages)
    assert all(item.evidence != "conversation_predecessor_target" for item in gathered.candidates)


async def test_explicit_reply_does_not_pick_up_an_unrelated_predecessor(database):
    session, uow = database
    seed_opening(session)
    gathered = await TopicTools(uow).gather(target(reply_to_message_id="another-message"))
    assert all(item.evidence != "conversation_predecessor_target" for item in gathered.candidates)


def test_predecessor_candidate_survives_both_ranking_passes():
    candidates = [
        TopicCandidate(id=str(index), title="Frontend role", description="", status="ACTIVE")
        for index in range(7)
    ]
    candidates.append(
        TopicCandidate(
            id="hackathon",
            title="Họp làm hackathon team1",
            description="",
            status="ACTIVE",
            evidence="conversation_predecessor_target",
        )
    )
    first = retrieve_topic_candidates(target(content="ai là frontend?"), candidates)
    second = retrieve_topic_candidates(target(content="tui là frontend"), first)
    assert first[0].id == second[0].id == "hackathon"
    assert second[0].evidence == "conversation_predecessor_target"


def test_nearby_topic_does_not_override_an_independent_new_topic():
    candidate = TopicCandidate(
        id="hackathon",
        title="Họp làm hackathon team1",
        description="",
        status="ACTIVE",
        evidence="conversation_predecessor_target",
    )
    result = ClassificationResult(
        decision=TopicDecision(
            outcome="new",
            title="Ăn trưa",
            confidence=0.9,
            reason="Independent meal plan",
            evidence_message_ids=["roles"],
        ),
        model_id="test",
        latency_ms=0,
    )
    checked = validate_classification(
        result, target(content="Trưa nay ăn bún bò?"), [candidate], []
    )
    assert checked.decision.outcome == "new"
    assert checked.decision.topic_id is None
